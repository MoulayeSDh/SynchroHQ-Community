import calendar
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.authorization.service import is_allowed
from app.modules.forms.models import Form
from app.modules.hierarchy.models import ExpectedReceipt, ExpectedReport, ReportingRequirement
from app.modules.users.models import User


def allowed(
    session: Session, user: User, requirement: ReportingRequirement, action: str = "reports:read"
) -> bool:
    form = session.get(Form, requirement.form_id)
    return (
        requirement.tenant_id == user.tenant_id
        and form is not None
        and is_allowed(
            session,
            user_id=user.id,
            action=action,
            territory_id=requirement.territory_id,
            required_clearance=max(requirement.required_clearance, form.required_clearance),
        )
    )


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def periods(
    requirement: ReportingRequirement, start: date, end: date
) -> Iterator[tuple[date, date, datetime]]:
    current = max(start, requirement.active_from)
    end = min(end, requirement.active_until or end)
    if requirement.cadence == "WEEKLY":
        current -= timedelta(days=current.weekday())
    elif requirement.cadence == "MONTHLY":
        current = current.replace(day=1)
    while current <= end:
        if requirement.cadence == "DAILY":
            last = current
        elif requirement.cadence == "WEEKLY":
            last = current + timedelta(days=6)
        else:
            last = current.replace(day=calendar.monthrange(current.year, current.month)[1])
        # No partial first/last reporting period: configuration remains explicit.
        if (
            current >= requirement.active_from
            and last <= (requirement.active_until or last)
            and last >= start
        ):
            due_day = last + timedelta(days=requirement.deadline_days)
            due = datetime.combine(
                due_day, time(requirement.deadline_hour), ZoneInfo(requirement.timezone)
            ).astimezone(UTC)
            yield current, last, due
        current = last + timedelta(days=1)


def generate(
    session: Session, requirement: ReportingRequirement, start: date, end: date
) -> list[ExpectedReport]:
    result = []
    for first, last, due in periods(requirement, start, end):
        identifier = uuid.uuid5(requirement.id, first.isoformat())
        item = session.get(ExpectedReport, identifier)
        if item is None:
            item = ExpectedReport(
                id=identifier,
                requirement_id=requirement.id,
                period_start=first,
                period_end=last,
                expected_by=due,
            )
            session.add(item)
        result.append(item)
    session.flush()
    return result


def category(
    session: Session, expected: ExpectedReport, now: datetime
) -> tuple[str, ExpectedReceipt | None]:
    receipt = session.get(ExpectedReceipt, expected.id)
    if receipt:
        return (
            "RECEIVED" if utc(receipt.received_at) <= utc(expected.expected_by) else "LATE"
        ), receipt
    return ("MISSING" if utc(now) > utc(expected.expected_by) else "EXPECTED"), None


def visible_requirements(session: Session, user: User) -> list[ReportingRequirement]:
    return [
        r
        for r in session.scalars(
            select(ReportingRequirement).where(ReportingRequirement.tenant_id == user.tenant_id)
        )
        if allowed(session, user, r)
    ]
