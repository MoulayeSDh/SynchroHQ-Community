import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.modules.forms.models import Form
from app.modules.forms.routes import current_user
from app.modules.hierarchy.models import ExpectedReceipt, ExpectedReport, ReportingRequirement
from app.modules.hierarchy.service import generate, visible_requirements
from app.modules.sync.routes import fail
from app.modules.territories.models import Territory
from app.modules.users.models import User

router = APIRouter(prefix="/api/reports/analytics", tags=["analytics"])
STATUSES = ("EXPECTED", "RECEIVED", "LATE", "MISSING")


@router.get("/overview")
def overview(
    start: date,
    end: date,
    territory_id: uuid.UUID | None = None,
    form_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if end < start or (end - start).days > 365:
        fail(422, "PERIOD_RANGE_INVALID")
    as_of = datetime.now(UTC)
    # Authorization is evaluated before any analytical query. A supplied filter never expands scope.
    authorized = visible_requirements(session, user)
    available_forms = []
    available_territories = []
    for identifier in sorted({item.form_id for item in authorized}):
        form = session.get(Form, identifier)
        if form is not None:
            available_forms.append({"id": str(identifier), "name": form.name})
    for identifier in sorted({item.territory_id for item in authorized}):
        territory = session.get(Territory, identifier)
        if territory is not None:
            available_territories.append({"id": str(identifier), "name": territory.name})
    requirements = [
        item
        for item in authorized
        if (territory_id is None or item.territory_id == territory_id)
        and (form_id is None or item.form_id == form_id)
    ]
    for requirement in requirements:
        session.execute(
            select(ReportingRequirement.id)
            .where(ReportingRequirement.id == requirement.id)
            .with_for_update()
        )
        generate(session, requirement, start, end)

    counts = dict.fromkeys(STATUSES, 0)
    if not requirements:
        session.commit()
        return {
            "start": start.isoformat(), "end": end.isoformat(), "as_of": as_of.isoformat(),
            "timezone": "UTC", "total": 0, "counts": counts,
            "by_period": [], "by_territory": [],
            "available_forms": available_forms, "available_territories": available_territories,
        }

    received_before_snapshot = ExpectedReceipt.received_at <= as_of
    status = case(
        (
            received_before_snapshot,
            case(
                (ExpectedReceipt.received_at <= ExpectedReport.expected_by, "RECEIVED"),
                else_="LATE",
            ),
        ),
        (ExpectedReport.expected_by < as_of, "MISSING"),
        else_="EXPECTED",
    ).label("status")
    visible = (
        select(
            ExpectedReport.id.label("expected_id"),
            ExpectedReport.period_start.label("period_start"),
            ReportingRequirement.territory_id.label("territory_id"),
            status,
        )
        .join(ReportingRequirement, ReportingRequirement.id == ExpectedReport.requirement_id)
        .outerjoin(ExpectedReceipt, ExpectedReceipt.expected_id == ExpectedReport.id)
        .where(
            ReportingRequirement.tenant_id == user.tenant_id,
            ReportingRequirement.id.in_([item.id for item in requirements]),
            ExpectedReport.period_end >= start,
            ExpectedReport.period_start <= end,
        )
        .subquery()
    )
    for state, count in session.execute(
        select(visible.c.status, func.count(visible.c.expected_id)).group_by(visible.c.status)
    ):
        counts[state] = count
    periods = session.execute(
        select(visible.c.period_start, visible.c.status, func.count(visible.c.expected_id))
        .group_by(visible.c.period_start, visible.c.status)
        .order_by(visible.c.period_start)
    )
    by_period: dict[str, dict[str, Any]] = {}
    for period, state, count in periods:
        key = period.isoformat()
        row = by_period.setdefault(key, {"period_start": key, "counts": dict.fromkeys(STATUSES, 0)})
        row["counts"][state] = count
    territories = session.execute(
        select(
            visible.c.territory_id,
            Territory.name,
            visible.c.status,
            func.count(visible.c.expected_id),
        )
        .join(Territory, Territory.id == visible.c.territory_id)
        .group_by(visible.c.territory_id, Territory.name, visible.c.status)
        .order_by(Territory.name, visible.c.territory_id)
    )
    by_territory: dict[str, dict[str, Any]] = {}
    for identifier, name, state, count in territories:
        key = str(identifier)
        row = by_territory.setdefault(
            key, {"territory_id": key, "territory_name": name,
                  "counts": dict.fromkeys(STATUSES, 0)}
        )
        row["counts"][state] = count
    session.commit()
    return {
        "start": start.isoformat(), "end": end.isoformat(), "as_of": as_of.isoformat(),
        "timezone": "UTC", "total": sum(counts.values()), "counts": counts,
        "by_period": list(by_period.values()), "by_territory": list(by_territory.values()),
        "available_forms": available_forms, "available_territories": available_territories,
    }
