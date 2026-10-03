"""Project validated GPS activities of a confirmed revision into PostGIS."""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def valid_points(answers: dict[str, Any]) -> list[tuple[int, float, float]]:
    activities = answers.get("activities")
    if not isinstance(activities, list):
        return []
    points = []
    for index, activity in enumerate(activities):
        if not isinstance(activity, dict):
            continue
        location = activity.get("location")
        if not isinstance(location, dict):
            continue
        latitude, longitude = location.get("latitude"), location.get("longitude")
        if (
            isinstance(latitude, (int, float))
            and not isinstance(latitude, bool)
            and isinstance(longitude, (int, float))
            and not isinstance(longitude, bool)
            and -90 <= latitude <= 90
            and -180 <= longitude <= 180
        ):
            points.append((index, float(latitude), float(longitude)))
    return points


def record_revision_points(
    session: Session,
    *,
    revision_id: UUID,
    report_id: UUID,
    tenant_id: UUID,
    territory_id: UUID,
    form_id: UUID,
    required_clearance: int,
    period_start: date,
    answers: dict[str, Any],
) -> None:
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return
    statement = text("""
        INSERT INTO report_geo_points (
            revision_id, activity_index, report_id, tenant_id, territory_id,
            form_id, required_clearance, period_start, location
        ) VALUES (
            :revision_id, :activity_index, :report_id, :tenant_id, :territory_id,
            :form_id, :required_clearance, :period_start,
            ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)
        )
    """)
    for index, latitude, longitude in valid_points(answers):
        session.execute(statement, {
            "revision_id": revision_id, "activity_index": index,
            "report_id": report_id, "tenant_id": tenant_id,
            "territory_id": territory_id, "form_id": form_id,
            "required_clearance": required_clearance, "period_start": period_start,
            "latitude": latitude, "longitude": longitude,
        })
