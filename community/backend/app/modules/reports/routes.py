import hashlib
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Literal

import jwt
import rfc8785
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_session
from app.modules.authorization.models import AssignmentScope, Role
from app.modules.authorization.service import is_allowed, matching_assignments
from app.modules.forms.models import FormVersion
from app.modules.forms.routes import current_user, get_form
from app.modules.forms.validation import validate_answers
from app.modules.geospatial.service import record_revision_points
from app.modules.hierarchy.models import ExpectedReceipt, ExpectedReport, ReportingRequirement
from app.modules.hierarchy.service import allowed as requirement_allowed
from app.modules.organizations.models import Organization
from app.modules.reports.models import (
    ConfirmationProof,
    CorrectionRequest,
    CorrectionResolution,
    Report,
    ReportAttachment,
    ReportAuditEvent,
    ReportComment,
    ReportOperation,
    ReportRevision,
    WorkflowOperation,
)
from app.modules.sync.models import CollectionDraft, DraftAttachment
from app.modules.sync.routes import fail
from app.modules.sync.storage import client as storage_client
from app.modules.users.models import User

router = APIRouter(prefix="/api/reports", tags=["reports"])
CONTEXT_AUDIENCE = "synchrohq-report-context"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AttachmentMetadata(StrictModel):
    attachment_id: uuid.UUID
    file_name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=128)
    size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class CorrectionLink(StrictModel):
    base_revision_id: uuid.UUID
    correction_request_id: uuid.UUID


class ConfirmedPayload(StrictModel):
    schema_version: Literal["synchrohq.report/v1"]
    report_id: uuid.UUID
    revision_id: uuid.UUID
    revision_number: int = Field(ge=1)
    correction: CorrectionLink | None = None
    expected_report_id: uuid.UUID | None = None
    draft_id: uuid.UUID
    device_id: uuid.UUID
    snapshot: dict[str, Any]
    answers: dict[str, Any]
    attachments: list[AttachmentMetadata] = Field(max_length=100)
    created_at: AwareDatetime
    finalized_at: AwareDatetime
    confirmed_at: AwareDatetime


class ConfirmationRequest(StrictModel):
    operation_id: uuid.UUID
    canonical_payload: str = Field(max_length=2097152)
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    context_token: str = Field(max_length=65536)


def report_allowed(session: Session, user: User, report: Report, action: str) -> bool:
    return report.tenant_id == user.tenant_id and is_allowed(
        session,
        user_id=user.id,
        action=action,
        territory_id=report.territory_id,
        required_clearance=report.required_clearance,
    )


@router.post("/contexts/{version_id}")
def prepare_context(
    version_id: uuid.UUID,
    correction_request_id: uuid.UUID | None = Query(None),
    expected_report_id: uuid.UUID | None = Query(None),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    version = session.get(FormVersion, version_id)
    if version is None:
        fail(404, "FORM_UNAVAILABLE")
    form = get_form(session, user, version.form_id, "forms:read")
    correction = None
    if correction_request_id is not None:
        request = session.get(CorrectionRequest, correction_request_id)
        if request is None:
            fail(404, "CORRECTION_UNAVAILABLE")
        report = get_report(session, user, request.report_id)
        check_correction(session, user, report, request)
        base = session.get(ReportRevision, request.revision_id)
        assert base is not None
        if base.form_version_id != version.id:
            fail(409, "CORRECTION_VERSION_MISMATCH")
        if (
            form.territory_id != report.territory_id
            or form.required_clearance > report.required_clearance
        ):
            fail(409, "REPORT_POLICY_CHANGED")
        correction = {
            "report_id": str(report.id),
            "base_revision_id": str(base.id),
            "correction_request_id": str(request.id),
            "revision_number": base.number + 1,
        }
    if correction:
        assert base is not None
        expected_report_id = (
            uuid.UUID(base.payload["expected_report_id"])
            if base.payload.get("expected_report_id")
            else None
        )
    expected_requirement = None
    if expected_report_id:
        expected = session.get(ExpectedReport, expected_report_id)
        expected_requirement = (
            session.get(ReportingRequirement, expected.requirement_id) if expected else None
        )
        if expected_requirement is None or not requirement_allowed(
            session, user, expected_requirement
        ):
            fail(404, "EXPECTED_REPORT_UNAVAILABLE")
        if (
            expected_requirement.form_id != form.id
            or expected_requirement.territory_id != form.territory_id
        ):
            fail(409, "EXPECTED_REPORT_FORM_MISMATCH")
        if not correction and session.get(ExpectedReceipt, expected_report_id) is not None:
            fail(409, "EXPECTED_REPORT_ALREADY_RECEIVED")
    if (
        version.status not in ({"PUBLISHED", "RETIRED"} if correction else {"PUBLISHED"})
        or not form.active
        or form.archived
    ):
        fail(409, "FORM_VERSION_UNAVAILABLE")
    eligible = matching_assignments(
        session,
        user_id=user.id,
        action="reports:confirm",
        territory_id=form.territory_id,
        required_clearance=report.required_clearance if correction else form.required_clearance,
    )
    creators = matching_assignments(
        session,
        user_id=user.id,
        action="reports:correct" if correction else "reports:create",
        territory_id=form.territory_id,
        required_clearance=report.required_clearance if correction else form.required_clearance,
    )
    creator_ids = {item.id for item in creators}
    assignment = next(
        (
            item
            for item in eligible
            if item.id in creator_ids
            and (
                expected_requirement is None
                or item.organization_id == expected_requirement.organization_id
            )
        ),
        None,
    )
    if assignment is None:
        fail(403, "REPORT_PERMISSION_DENIED")
    organization = session.get(Organization, assignment.organization_id)
    role = session.get(Role, assignment.role_id)
    assert organization is not None and role is not None
    scopes = session.scalars(
        select(AssignmentScope)
        .where(AssignmentScope.assignment_id == assignment.id)
        .order_by(AssignmentScope.territory_id)
    ).all()
    snapshot = {
        "tenant_id": str(user.tenant_id),
        "author": {"id": str(user.id), "display_name": user.display_name},
        "organization": {
            "id": str(organization.id),
            "name": organization.name,
            "code": organization.code,
            "type_code": organization.type_code,
        },
        "assignment": {
            "id": str(assignment.id),
            "role_id": str(role.id),
            "role_code": role.code,
            "clearance_level": assignment.clearance_level,
            "scopes": [
                {"territory_id": str(s.territory_id), "coverage": s.coverage} for s in scopes
            ],
        },
        "form_id": str(form.id),
        "form_version_id": str(version.id),
        "form_version": version.version,
        "territory_id": str(form.territory_id),
        "required_clearance": report.required_clearance if correction else form.required_clearance,
        "auth_method": "community-jwt",
    }
    now = datetime.now(UTC)
    expiry = int(now.timestamp()) + get_settings().offline_edit_seconds
    if assignment.valid_to is not None:
        expiry = min(expiry, int(assignment.valid_to.replace(tzinfo=UTC).timestamp()))
    settings = get_settings()
    token = jwt.encode(
        {
            "sub": str(user.id),
            "snapshot": snapshot,
            "correction": correction,
            "expected_report_id": str(expected_report_id) if expected_report_id else None,
            "purpose": "report-confirmation",
            "iat": int(now.timestamp()),
            "exp": expiry,
            "iss": settings.auth_issuer,
            "aud": CONTEXT_AUDIENCE,
        },
        settings.auth_jwt_secret,
        algorithm="HS256",
    )
    result = {
        "snapshot": snapshot,
        "context_token": token,
        "issued_at": now.isoformat(),
        "expires_at": datetime.fromtimestamp(expiry, UTC).isoformat(),
    }
    if expected_report_id:
        result["expected_report_id"] = str(expected_report_id)
    if correction:
        result["correction"] = correction
        result["sync_grant"] = jwt.encode(
            {
                "sub": str(user.id),
                "tenant_id": str(user.tenant_id),
                "form_version_id": str(version.id),
                "purpose": "offline-correction-draft",
                "correction": correction,
                "iat": int(now.timestamp()),
                "exp": expiry,
                "iss": settings.auth_issuer,
                "aud": settings.offline_grant_audience,
            },
            settings.auth_jwt_secret,
            algorithm="HS256",
        )
    return result


def audit(
    session: Session, user: User, body: ConfirmationRequest, payload: ConfirmedPayload, code: str
) -> None:
    session.add(
        ReportAuditEvent(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            report_id=payload.report_id,
            revision_id=payload.revision_id,
            operation_id=body.operation_id,
            code=code,
            occurred_at=datetime.now(UTC),
        )
    )


@router.post("/confirmations")
def receive_confirmation(
    body: ConfirmationRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        raw = json.loads(body.canonical_payload)
        canonical = rfc8785.dumps(raw)
        payload = ConfirmedPayload.model_validate(raw)
    except (ValueError, ValidationError, rfc8785.CanonicalizationError) as exc:
        raise HTTPException(422, detail={"code": "REPORT_PAYLOAD_INVALID"}) from exc
    if canonical.decode() != body.canonical_payload:
        fail(422, "REPORT_NOT_CANONICAL")
    if hashlib.sha256(canonical).hexdigest() != body.payload_hash:
        fail(422, "CONFIRMATION_HASH_MISMATCH")
    request_hash = hashlib.sha256(rfc8785.dumps(body.model_dump(mode="json"))).hexdigest()
    session.execute(select(User.id).where(User.id == user.id).with_for_update())
    previous = session.get(ReportOperation, body.operation_id)
    if previous is not None:
        if previous.tenant_id != user.tenant_id or previous.owner_id != user.id:
            fail(404, "OPERATION_UNAVAILABLE")
        if previous.request_hash != request_hash:
            audit(session, user, body, payload, "OPERATION_ID_REUSED")
            session.commit()
            fail(409, "OPERATION_ID_REUSED")
        return previous.receipt
    try:
        settings = get_settings()
        context = jwt.decode(
            body.context_token,
            settings.auth_jwt_secret,
            algorithms=["HS256"],
            audience=CONTEXT_AUDIENCE,
            issuer=settings.auth_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
        if context.get("sub") != str(user.id) or context.get("purpose") != "report-confirmation":
            fail(403, "REPORT_CONTEXT_INVALID")
        if context.get("snapshot") != payload.snapshot:
            fail(422, "REPORT_SNAPSHOT_MISMATCH")
    except jwt.PyJWTError as exc:
        raise HTTPException(403, detail={"code": "REPORT_CONTEXT_EXPIRED_OR_INVALID"}) from exc
    correction_report = None
    correction_request = None
    if payload.correction is not None:
        correction_report = session.scalar(
            select(Report).where(Report.id == payload.report_id).with_for_update()
        )
        correction_request = session.get(
            CorrectionRequest, payload.correction.correction_request_id
        )
        if correction_report is None or correction_request is None:
            fail(404, "CORRECTION_UNAVAILABLE")
        check_correction(session, user, correction_report, correction_request)
        base = session.get(ReportRevision, payload.correction.base_revision_id)
        expected_link = {
            "report_id": str(payload.report_id),
            **payload.correction.model_dump(mode="json"),
            "revision_number": payload.revision_number,
        }
        if (
            context.get("correction") != expected_link
            or base is None
            or base.id != correction_request.revision_id
            or base.number + 1 != payload.revision_number
            or str(base.form_version_id) != payload.snapshot.get("form_version_id")
            or str(correction_report.territory_id) != payload.snapshot.get("territory_id")
            or correction_report.required_clearance != payload.snapshot.get("required_clearance")
        ):
            fail(409, "CORRECTION_CONTEXT_MISMATCH")
    elif payload.revision_number != 1 or context.get("correction") is not None:
        fail(409, "CORRECTION_CONTEXT_MISMATCH")
    if context.get("expected_report_id") != (
        str(payload.expected_report_id) if payload.expected_report_id else None
    ):
        fail(409, "EXPECTED_REPORT_CONTEXT_MISMATCH")
    expected = None
    if payload.expected_report_id is not None:
        expected = session.scalar(
            select(ExpectedReport)
            .where(ExpectedReport.id == payload.expected_report_id)
            .with_for_update()
        )
        requirement = (
            session.get(ReportingRequirement, expected.requirement_id) if expected else None
        )
        if requirement is None or not requirement_allowed(session, user, requirement):
            fail(404, "EXPECTED_REPORT_UNAVAILABLE")
        if (
            str(requirement.form_id) != payload.snapshot.get("form_id")
            or str(requirement.organization_id) != payload.snapshot["organization"]["id"]
            or str(requirement.territory_id) != payload.snapshot["territory_id"]
        ):
            fail(409, "EXPECTED_REPORT_TARGET_MISMATCH")
        accepted = session.get(ExpectedReceipt, payload.expected_report_id)
        if correction_report:
            if accepted is None or accepted.report_id != correction_report.id:
                fail(409, "EXPECTED_REPORT_ALREADY_RECEIVED")
        elif accepted:
            fail(409, "EXPECTED_REPORT_ALREADY_RECEIVED")
    snapshot = payload.snapshot
    if snapshot.get("tenant_id") != str(user.tenant_id):
        fail(403, "REPORT_CONTEXT_INVALID")
    if not (payload.created_at <= payload.finalized_at <= payload.confirmed_at):
        fail(422, "REPORT_DATES_INVALID")
    if not (context["iat"] <= payload.confirmed_at.timestamp() <= context["exp"]):
        fail(403, "REPORT_CONFIRMATION_OUTSIDE_SESSION")
    version = session.get(FormVersion, uuid.UUID(snapshot["form_version_id"]))
    if version is None:
        fail(404, "FORM_UNAVAILABLE")
    form = get_form(session, user, version.form_id, "forms:read")
    if form.required_clearance > snapshot["required_clearance"]:
        fail(409, "REPORT_POLICY_CHANGED")
    if str(form.territory_id) != snapshot["territory_id"]:
        fail(409, "REPORT_TERRITORY_CHANGED")
    if version.status not in {"PUBLISHED", "RETIRED"} or not form.active or form.archived:
        fail(409, "FORM_VERSION_UNAVAILABLE")
    if (
        version.status == "RETIRED"
        and correction_report is None
        and (
            version.retired_at is None
            or payload.created_at > version.retired_at.replace(tzinfo=UTC)
        )
    ):
        fail(409, "FORM_VERSION_UNAVAILABLE")
    if payload.confirmed_at.timestamp() > datetime.now(UTC).timestamp() + 300:
        fail(422, "REPORT_DATES_INVALID")
    for action in (
        ("reports:correct" if correction_report else "reports:create"),
        "reports:confirm",
    ):
        eligible = matching_assignments(
            session,
            user_id=user.id,
            action=action,
            territory_id=form.territory_id,
            required_clearance=max(form.required_clearance, snapshot["required_clearance"]),
        )
        if not any(str(item.id) == snapshot["assignment"]["id"] for item in eligible):
            audit(session, user, body, payload, "REPORT_SYNC_REJECTED")
            session.commit()
            fail(403, "REPORT_PERMISSION_REVOKED")
    validation = validate_answers(version.data_schema, payload.answers)
    if not validation.valid:
        raise HTTPException(
            422, detail={"code": "REPORT_ANSWERS_INVALID", "validation": validation.model_dump()}
        )
    draft = session.get(CollectionDraft, payload.draft_id)
    if draft is None or draft.owner_id != user.id or draft.tenant_id != user.tenant_id:
        fail(409, "REPORT_DRAFT_NOT_RECEIVED")
    if draft.form_version_id != version.id or draft.answers != payload.answers:
        fail(409, "REPORT_DRAFT_MISMATCH")
    metadata = [item.model_dump(mode="json") for item in payload.attachments]
    if metadata != payload.answers.get("attachments", []):
        fail(422, "REPORT_ATTACHMENTS_MISMATCH")
    if len({item.attachment_id for item in payload.attachments}) != len(metadata):
        fail(422, "REPORT_ATTACHMENTS_MISMATCH")
    files: list[DraftAttachment] = []
    for item in payload.attachments:
        stored = session.get(DraftAttachment, item.attachment_id)
        if stored is None:
            fail(409, "REPORT_ATTACHMENT_NOT_RECEIVED")
        if (
            stored.owner_id != user.id
            or stored.tenant_id != user.tenant_id
            or stored.draft_id != draft.id
            or stored.file_name != item.file_name
            or stored.mime_type != item.mime_type
            or stored.size != item.size
            or stored.sha256 != item.sha256
        ):
            fail(422, "REPORT_ATTACHMENTS_MISMATCH")
        files.append(stored)
    if (
        (correction_report is None and session.get(Report, payload.report_id) is not None)
        or session.get(ReportRevision, payload.revision_id) is not None
        or session.scalar(
            select(ReportRevision.id).where(ReportRevision.source_draft_id == draft.id)
        )
    ):
        fail(409, "REPORT_IDENTIFIER_CONFLICT")
    now = datetime.now(UTC)
    report = correction_report or Report(
        id=payload.report_id,
        tenant_id=user.tenant_id,
        author_id=user.id,
        territory_id=form.territory_id,
        required_clearance=snapshot["required_clearance"],
        current_revision_id=None,
        created_at=payload.created_at,
    )
    session.add(report)
    session.flush()
    revision = ReportRevision(
        id=payload.revision_id,
        report_id=report.id,
        number=payload.revision_number,
        form_version_id=version.id,
        source_draft_id=draft.id,
        payload=raw,
        canonical_payload=body.canonical_payload,
        payload_hash=body.payload_hash,
        confirmed_at=payload.confirmed_at,
        server_received_at=now,
    )
    session.add(revision)
    session.flush()
    if correction_request:
        session.add(
            CorrectionResolution(
                request_id=correction_request.id, revision_id=revision.id, created_at=now
            )
        )
        session.flush()
    report.current_revision_id = revision.id
    linked_expected = expected
    if linked_expected is None and correction_report is not None:
        linked_expected = session.scalar(
            select(ExpectedReport)
            .join(ExpectedReceipt, ExpectedReceipt.expected_id == ExpectedReport.id)
            .where(ExpectedReceipt.report_id == report.id)
        )
    record_revision_points(
        session,
        revision_id=revision.id,
        report_id=report.id,
        tenant_id=report.tenant_id,
        territory_id=report.territory_id,
        form_id=form.id,
        required_clearance=report.required_clearance,
        period_start=(
            linked_expected.period_start
            if linked_expected is not None
            else payload.confirmed_at.date()
        ),
        answers=payload.answers,
    )
    session.add(
        ConfirmationProof(
            revision_id=revision.id,
            author_id=user.id,
            device_id=payload.device_id,
            payload_hash=body.payload_hash,
            auth_method=snapshot["auth_method"],
            context_token=body.context_token,
            confirmed_at=payload.confirmed_at,
            server_received_at=now,
        )
    )
    for stored_file in files:
        session.add(
            ReportAttachment(
                revision_id=revision.id,
                attachment_id=stored_file.id,
                file_name=stored_file.file_name,
                mime_type=stored_file.mime_type,
                size=stored_file.size,
                sha256=stored_file.sha256,
                storage_key=stored_file.storage_key,
            )
        )
    if expected is not None and correction_report is None:
        session.add(
            ExpectedReceipt(
                expected_id=expected.id,
                report_id=report.id,
                revision_id=revision.id,
                received_at=now,
            )
        )
    receipt = {
        "operation_id": str(body.operation_id),
        "report_id": str(report.id),
        "revision_id": str(revision.id),
        "payload_hash": body.payload_hash,
        "server_received_at": now.isoformat(),
    }
    session.add(
        ReportOperation(
            id=body.operation_id,
            tenant_id=user.tenant_id,
            owner_id=user.id,
            revision_id=revision.id,
            request_hash=request_hash,
            receipt=receipt,
        )
    )
    for code in (
        "REPORT_REVISION_CREATED" if correction_report else "REPORT_CREATED",
        "REPORT_FINALIZED",
        "REPORT_CONFIRMED",
        "REPORT_SYNC_ACCEPTED",
        "CURRENT_REVISION_CHANGED",
    ):
        audit(session, user, body, payload, code)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, detail={"code": "REPORT_IDENTIFIER_CONFLICT"}) from exc
    return receipt


def get_report(session: Session, user: User, report_id: uuid.UUID) -> Report:
    report = session.get(Report, report_id)
    if report is None or not report_allowed(session, user, report, "reports:read"):
        fail(404, "REPORT_UNAVAILABLE")
    return report


@router.get("")
def list_reports(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    own: bool = Query(False),
) -> list[dict[str, Any]]:
    reports = session.scalars(
        select(Report).where(Report.tenant_id == user.tenant_id).order_by(Report.created_at.desc())
    )
    visible = [
        r
        for r in reports
        if (not own or r.author_id == user.id) and report_allowed(session, user, r, "reports:read")
    ]
    return [
        {
            "id": str(r.id),
            "current_revision_id": str(r.current_revision_id),
            "territory_id": str(r.territory_id),
            "required_clearance": r.required_clearance,
            "created_at": r.created_at.isoformat(),
        }
        for r in visible[offset : offset + limit]
    ]


@router.get("/{report_id}")
def read_report(
    report_id: uuid.UUID,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    report = get_report(session, user, report_id)
    session.add(
        ReportAuditEvent(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            report_id=report.id,
            revision_id=report.current_revision_id,
            operation_id=uuid.uuid4(),
            code="REPORT_VIEWED",
            occurred_at=datetime.now(UTC),
        )
    )
    session.commit()
    return serialize_report(session, user, report)


def revision_definition(session: Session, revision: ReportRevision) -> dict[str, Any] | None:
    version = session.get(FormVersion, revision.form_version_id)
    if version is None:
        return None
    return {
        "schema_version": version.schema_version,
        "data_schema": version.data_schema,
        "ui_schema": version.ui_schema,
        "translations": version.translations,
    }


def serialize_report(session: Session, user: User, report: Report) -> dict[str, Any]:
    revisions = session.scalars(
        select(ReportRevision)
        .where(ReportRevision.report_id == report.id)
        .order_by(ReportRevision.number)
    ).all()
    return {
        "id": str(report.id),
        "viewer_id": str(user.id),
        "current_revision_id": str(report.current_revision_id),
        "capabilities": {
            "review": report_allowed(session, user, report, "reports:review"),
            "comment": report_allowed(session, user, report, "reports:comment"),
            "request_correction": report_allowed(
                session, user, report, "reports:request-correction"
            ),
            "correct": report.author_id == user.id
            and report_allowed(session, user, report, "reports:correct")
            and report_allowed(session, user, report, "reports:confirm"),
        },
        "comments": [
            {
                "id": str(c.id),
                "revision_id": str(c.revision_id),
                "author": c.actor_name,
                "text": c.text,
                "created_at": c.created_at.isoformat(),
            }
            for c in session.scalars(
                select(ReportComment)
                .where(ReportComment.report_id == report.id)
                .order_by(ReportComment.created_at)
            )
        ],
        "corrections": [
            {
                "id": str(c.id),
                "revision_id": str(c.revision_id),
                "author": c.actor_name,
                "text": c.text,
                "created_at": c.created_at.isoformat(),
                "state": "RESOLVED" if session.get(CorrectionResolution, c.id) else "OPEN",
            }
            for c in session.scalars(
                select(CorrectionRequest)
                .where(CorrectionRequest.report_id == report.id)
                .order_by(CorrectionRequest.created_at)
            )
        ],
        "revisions": [
            {
                "id": str(r.id),
                "number": r.number,
                "form_definition": revision_definition(session, r),
                "state": "CONFIRMED" if r.id == report.current_revision_id else "SUPERSEDED",
                "payload": r.payload,
                "canonical_payload": r.canonical_payload,
                "payload_hash": r.payload_hash,
                "server_received_at": r.server_received_at.isoformat(),
            }
            for r in revisions
        ],
    }


@router.get("/{report_id}/attachments/{attachment_id}")
def download_attachment(
    report_id: uuid.UUID,
    attachment_id: uuid.UUID,
    revision_id: uuid.UUID | None = Query(None),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    report = get_report(session, user, report_id)
    selected_revision = revision_id or report.current_revision_id
    revision = session.get(ReportRevision, selected_revision)
    if revision is None or revision.report_id != report.id:
        fail(404, "ATTACHMENT_UNAVAILABLE")
    item = session.get(ReportAttachment, (selected_revision, attachment_id))
    if item is None:
        fail(404, "ATTACHMENT_UNAVAILABLE")
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        response = storage_client().get_object(
            Bucket=get_settings().s3_bucket, Key=item.storage_key
        )
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(503, detail={"code": "OBJECT_STORAGE_UNAVAILABLE"}) from exc

    def chunks() -> Iterator[bytes]:
        stream = response["Body"]
        try:
            while chunk := stream.read(65536):
                yield chunk
        finally:
            stream.close()

    return StreamingResponse(
        chunks(),
        media_type=item.mime_type,
        headers={
            "Content-Disposition": "attachment",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def check_correction(
    session: Session, user: User, report: Report, request: CorrectionRequest
) -> None:
    if not report_allowed(session, user, report, "reports:read"):
        fail(404, "REPORT_UNAVAILABLE")
    if report.author_id != user.id or not all(
        report_allowed(session, user, report, a) for a in ("reports:correct", "reports:confirm")
    ):
        fail(403, "CORRECTION_PERMISSION_DENIED")
    if (
        request.report_id != report.id
        or request.revision_id != report.current_revision_id
        or session.get(CorrectionResolution, request.id) is not None
    ):
        fail(409, "CORRECTION_ALREADY_RESOLVED")


class WorkflowRequest(StrictModel):
    operation_id: uuid.UUID
    revision_id: uuid.UUID
    text: str = Field(min_length=1, max_length=4000)


def write_workflow(
    session: Session, user: User, report_id: uuid.UUID, body: WorkflowRequest, correction: bool
) -> dict[str, Any]:
    digest = hashlib.sha256(
        rfc8785.dumps(
            {"report_id": str(report_id), "correction": correction, **body.model_dump(mode="json")}
        )
    ).hexdigest()
    session.execute(select(User.id).where(User.id == user.id).with_for_update())
    previous = session.get(WorkflowOperation, body.operation_id)
    if previous:
        if previous.tenant_id != user.tenant_id or previous.owner_id != user.id:
            fail(404, "OPERATION_UNAVAILABLE")
        if previous.request_hash != digest:
            accepted_revision = session.get(
                ReportRevision, uuid.UUID(previous.receipt["revision_id"])
            )
            assert accepted_revision is not None
            session.add(
                ReportAuditEvent(
                    tenant_id=user.tenant_id,
                    actor_id=user.id,
                    report_id=accepted_revision.report_id,
                    revision_id=accepted_revision.id,
                    operation_id=body.operation_id,
                    code="OPERATION_ID_REUSED",
                    occurred_at=datetime.now(UTC),
                )
            )
            session.commit()
            fail(409, "OPERATION_ID_REUSED")
        return previous.receipt
    report = session.scalar(select(Report).where(Report.id == report_id).with_for_update())
    if report is None or not report_allowed(session, user, report, "reports:read"):
        fail(404, "REPORT_UNAVAILABLE")
    action = "reports:request-correction" if correction else "reports:comment"
    if not report_allowed(session, user, report, action):
        fail(403, "REPORT_PERMISSION_DENIED")
    revision = session.get(ReportRevision, body.revision_id)
    if revision is None or revision.report_id != report.id:
        fail(404, "REVISION_UNAVAILABLE")
    if not body.text.strip():
        fail(422, "REASON_REQUIRED")
    if correction and (
        report.current_revision_id != revision.id
        or session.scalar(
            select(CorrectionRequest.id).where(CorrectionRequest.revision_id == revision.id)
        )
    ):
        fail(409, "CORRECTION_ALREADY_REQUESTED")
    now = datetime.now(UTC)
    identifier = uuid.uuid4()
    model = CorrectionRequest if correction else ReportComment
    session.add(
        model(
            id=identifier,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            actor_name=user.display_name,
            report_id=report.id,
            revision_id=revision.id,
            text=body.text.strip(),
            created_at=now,
        )
    )
    receipt = {
        "operation_id": str(body.operation_id),
        "id": str(identifier),
        "revision_id": str(revision.id),
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
            revision_id=revision.id,
            operation_id=body.operation_id,
            code="CORRECTION_REQUESTED" if correction else "REPORT_COMMENTED",
            occurred_at=now,
        )
    )
    session.commit()
    return receipt


@router.post("/{report_id}/comments")
def comment(
    report_id: uuid.UUID,
    body: WorkflowRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return write_workflow(session, user, report_id, body, False)


@router.post("/{report_id}/correction-requests")
def request_correction(
    report_id: uuid.UUID,
    body: WorkflowRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return write_workflow(session, user, report_id, body, True)
