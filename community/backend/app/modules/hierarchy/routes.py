import hashlib
import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import rfc8785
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.modules.authorization.service import matching_assignments
from app.modules.forms.models import Form, FormVersion
from app.modules.forms.routes import current_user, get_form
from app.modules.hierarchy.models import ExpectedReport, ReportingRequirement, ReportReview
from app.modules.hierarchy.service import allowed, category, generate, visible_requirements
from app.modules.organizations.models import Organization
from app.modules.reports.models import (
    CorrectionRequest,
    CorrectionResolution,
    Report,
    ReportAuditEvent,
    ReportRevision,
    WorkflowOperation,
)
from app.modules.reports.routes import get_report, report_allowed, serialize_report
from app.modules.sync.routes import fail
from app.modules.territories.models import Territory
from app.modules.users.models import User

router = APIRouter(prefix="/api/reports/workflow", tags=["hierarchy"])


class RequirementInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    form_id: uuid.UUID
    organization_id: uuid.UUID
    territory_id: uuid.UUID
    cadence: Literal["DAILY", "WEEKLY", "MONTHLY"]
    active_from: date
    active_until: date | None = None
    timezone: str = Field(default="Africa/Nouakchott", max_length=64)
    deadline_hour: int = Field(default=18, ge=0, le=23)
    deadline_days: int = Field(default=0, ge=0, le=31)


@router.post("/requirements")
def create_requirement(
    body: RequirementInput,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    form = get_form(session, user, body.form_id, "forms:manage")
    if not matching_assignments(
        session,
        user_id=user.id,
        action="reporting:manage",
        territory_id=body.territory_id,
        required_clearance=form.required_clearance,
    ):
        fail(403, "REPORTING_PERMISSION_DENIED")
    organization = session.get(Organization, body.organization_id)
    if organization is None or organization.tenant_id != user.tenant_id or not organization.active:
        fail(404, "ORGANIZATION_UNAVAILABLE")
    if body.territory_id != form.territory_id:
        fail(422, "REQUIREMENT_FORM_TERRITORY_MISMATCH")
    if body.active_until and body.active_until < body.active_from:
        fail(422, "REQUIREMENT_DATES_INVALID")
    try:
        ZoneInfo(body.timezone)
    except ZoneInfoNotFoundError:
        fail(422, "TIMEZONE_INVALID")
    session.execute(select(User.id).where(User.id == user.id).with_for_update())
    # A shared form lock serializes configuration by different administrators.
    session.execute(select(Form.id).where(Form.id == form.id).with_for_update())
    previous = session.get(ReportingRequirement, body.id)
    if previous:
        if previous.tenant_id != user.tenant_id:
            fail(404, "REQUIREMENT_UNAVAILABLE")
        if any(getattr(previous, key) != value for key, value in body.model_dump().items()):
            fail(409, "REQUIREMENT_ID_REUSED")
        return {"id": str(previous.id)}
    overlaps = session.scalars(
        select(ReportingRequirement).where(
            ReportingRequirement.form_id == body.form_id,
            ReportingRequirement.organization_id == body.organization_id,
            ReportingRequirement.territory_id == body.territory_id,
            ReportingRequirement.cadence == body.cadence,
        )
    )
    if any(
        r.active_from <= (body.active_until or date.max)
        and (r.active_until or date.max) >= body.active_from
        for r in overlaps
    ):
        fail(409, "REQUIREMENT_PERIOD_OVERLAP")
    session.add(
        ReportingRequirement(
            **body.model_dump(),
            tenant_id=user.tenant_id,
            required_clearance=form.required_clearance,
            created_by=user.id,
            created_at=datetime.now(UTC),
        )
    )
    session.commit()
    return {"id": str(body.id)}


@router.post("/requirements/materialize")
def materialize(
    start: date,
    end: date,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, int]:
    if end < start or (end - start).days > 365:
        fail(422, "PERIOD_RANGE_INVALID")
    count = 0
    for requirement in visible_requirements(session, user):
        if not allowed(session, user, requirement, "reporting:manage"):
            continue
        session.execute(
            select(ReportingRequirement.id)
            .where(ReportingRequirement.id == requirement.id)
            .with_for_update()
        )
        count += len(generate(session, requirement, start, end))
    session.commit()
    return {"expected": count}


@router.get("/expected")
def expected_reports(
    start: date,
    end: date,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if end < start or (end - start).days > 365:
        fail(422, "PERIOD_RANGE_INVALID")
    now = datetime.now(UTC)
    rows = []
    counts = {s: 0 for s in ("EXPECTED", "RECEIVED", "MISSING", "LATE")}
    for requirement in visible_requirements(session, user):
        # Materialize the immutable projection of an already authorized requirement.
        session.execute(
            select(ReportingRequirement.id)
            .where(ReportingRequirement.id == requirement.id)
            .with_for_update()
        )
        generate(session, requirement, start, end)
        for expected in session.scalars(
            select(ExpectedReport)
            .where(
                ExpectedReport.requirement_id == requirement.id,
                ExpectedReport.period_end >= start,
                ExpectedReport.period_start <= end,
            )
            .order_by(ExpectedReport.period_start)
        ):
            status, receipt = category(session, expected, now)
            counts[status] += 1
            creators = matching_assignments(
                session,
                user_id=user.id,
                action="reports:create",
                territory_id=requirement.territory_id,
                required_clearance=requirement.required_clearance,
            )
            territory = session.get(Territory, requirement.territory_id)
            form = session.get(Form, requirement.form_id)
            organization = session.get(Organization, requirement.organization_id)
            assert territory is not None and form is not None and organization is not None
            rows.append(
                {
                    "id": str(expected.id),
                    "requirement_id": str(requirement.id),
                    "form_id": str(requirement.form_id),
                    "organization_id": str(requirement.organization_id),
                    "territory_id": str(requirement.territory_id),
                    "territory_name": territory.name,
                    "form_name": form.name,
                    "organization_name": organization.name,
                    "period_start": expected.period_start.isoformat(),
                    "period_end": expected.period_end.isoformat(),
                    "expected_by": expected.expected_by.isoformat(),
                    "timezone": requirement.timezone,
                    "cadence": requirement.cadence,
                    "status": status,
                    "report_id": str(receipt.report_id) if receipt else None,
                    "received_at": receipt.received_at.isoformat() if receipt else None,
                    "can_create": not receipt
                    and any(a.organization_id == requirement.organization_id for a in creators),
                    "explanation": (
                        "Accusé serveur reçu avant ou à l’échéance"
                        if status == "RECEIVED"
                        else "Accusé serveur reçu après l’échéance"
                        if status == "LATE"
                        else "Échéance dépassée sans accusé serveur lié"
                        if status == "MISSING"
                        else "Échéance à venir, aucun accusé serveur lié"
                    ),
                }
            )
    session.commit()
    return {"as_of": now.isoformat(), "total": len(rows), "counts": counts, "items": rows}


def state(session: Session, report: Report, revision: ReportRevision, user: User) -> str:
    requests = session.scalars(
        select(CorrectionRequest).where(CorrectionRequest.report_id == report.id)
    )
    if any(session.get(CorrectionResolution, r.id) is None for r in requests):
        return "CORRECTION_REQUESTED"
    review = session.scalar(
        select(ReportReview.id).where(
            ReportReview.revision_id == revision.id, ReportReview.reviewer_id == user.id
        )
    )
    if review or not report_allowed(session, user, report, "reports:review"):
        return "CONFIRMED" if revision.number == 1 or review else "CORRECTED"
    return "CORRECTED" if revision.number > 1 else "TO_REVIEW"


@router.get("/inbox")
def inbox(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
    own: bool = False,
    start: date | None = None,
    end: date | None = None,
    territory_id: uuid.UUID | None = None,
    form_id: uuid.UUID | None = None,
    author_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    status: Literal["RECEIVED", "TO_REVIEW", "CORRECTION_REQUESTED", "CORRECTED", "CONFIRMED"]
    | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> list[dict[str, Any]]:
    result: list[tuple[Report, str]] = []
    for report in session.scalars(
        select(Report)
        .where(Report.tenant_id == user.tenant_id)
        .order_by(Report.created_at.desc(), Report.id)
    ):
        if not report_allowed(session, user, report, "reports:read"):
            continue
        revision = session.get(ReportRevision, report.current_revision_id)
        if revision is None:
            continue
        version = session.get(FormVersion, revision.form_version_id)
        assert version is not None
        report_state = state(session, report, revision, user)
        # Restrict by Authorization first; filters never grant access.
        if (
            own
            and report.author_id != user.id
            or territory_id
            and report.territory_id != territory_id
            or form_id
            and version.form_id != form_id
        ):
            continue
        if (
            author_id
            and report.author_id != author_id
            or organization_id
            and revision.payload["snapshot"]["organization"]["id"] != str(organization_id)
        ):
            continue
        expected_id = revision.payload.get("expected_report_id")
        expected = session.get(ExpectedReport, uuid.UUID(expected_id)) if expected_id else None
        if expected:
            report_date = expected.period_start
        else:
            try:
                report_date = date.fromisoformat(
                    revision.payload["answers"].get("report_date", str(report.created_at.date()))
                )
            except TypeError, ValueError:
                report_date = report.created_at.date()
        report_period_end = expected.period_end if expected else report_date
        if (
            start
            and report_period_end < start
            or end
            and report_date > end
            or status
            and status != "RECEIVED"
            and status != report_state
        ):
            continue
        result.append((report, report_state))
    records = []
    for report, workflow_state in result[offset : offset + limit]:
        revision = session.get(ReportRevision, report.current_revision_id)
        assert revision is not None
        version = session.get(FormVersion, revision.form_version_id)
        assert version is not None
        form = session.get(Form, version.form_id)
        territory = session.get(Territory, report.territory_id)
        assert form is not None and territory is not None
        expected_id = revision.payload.get("expected_report_id")
        expected = session.get(ExpectedReport, uuid.UUID(expected_id)) if expected_id else None
        records.append(
            {
                **serialize_report(session, user, report),
                "workflow_state": workflow_state,
                "territory_id": str(report.territory_id),
                "territory_name": territory.name,
                "form_id": str(form.id),
                "form_name": form.name,
                "author_id": str(report.author_id),
                "period_end": expected.period_end.isoformat()
                if expected
                else revision.payload["answers"].get(
                    "report_date", report.created_at.date().isoformat()
                ),
                "period": expected.period_start.isoformat()
                if expected
                else revision.payload["answers"].get(
                    "report_date", report.created_at.date().isoformat()
                ),
            }
        )
    return records


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: uuid.UUID
    revision_id: uuid.UUID


@router.post("/{report_id}/review")
def review(
    report_id: uuid.UUID,
    body: ReviewInput,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    digest = hashlib.sha256(
        rfc8785.dumps(
            {"report_id": str(report_id), "action": "review", **body.model_dump(mode="json")}
        )
    ).hexdigest()
    session.execute(select(User.id).where(User.id == user.id).with_for_update())
    previous = session.get(WorkflowOperation, body.operation_id)
    if previous:
        if previous.tenant_id != user.tenant_id or previous.owner_id != user.id:
            fail(404, "OPERATION_UNAVAILABLE")
        if previous.request_hash != digest:
            fail(409, "OPERATION_ID_REUSED")
        return previous.receipt
    report = get_report(session, user, report_id)
    session.execute(select(Report.id).where(Report.id == report.id).with_for_update())
    if not report_allowed(session, user, report, "reports:review"):
        fail(403, "REPORT_PERMISSION_DENIED")
    if report.current_revision_id != body.revision_id:
        fail(409, "CURRENT_REVISION_CHANGED")
    session.refresh(report)
    if report.current_revision_id != body.revision_id:
        fail(409, "CURRENT_REVISION_CHANGED")
    now = datetime.now(UTC)
    existing = session.scalar(
        select(ReportReview).where(
            ReportReview.revision_id == body.revision_id, ReportReview.reviewer_id == user.id
        )
    )
    if existing is None:
        session.add(
            ReportReview(
                id=uuid.uuid4(), revision_id=body.revision_id, reviewer_id=user.id, reviewed_at=now
            )
        )
    receipt = {
        "operation_id": str(body.operation_id),
        "revision_id": str(body.revision_id),
        "server_received_at": now.isoformat(),
    }
    session.add(
        WorkflowOperation(
            id=body.operation_id,
            tenant_id=user.tenant_id,
            owner_id=user.id,
            request_hash=digest,
            receipt=receipt,
        )
    )
    session.add(
        ReportAuditEvent(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            report_id=report.id,
            revision_id=body.revision_id,
            operation_id=body.operation_id,
            code="REPORT_REVIEWED",
            occurred_at=now,
        )
    )
    session.commit()
    return receipt
