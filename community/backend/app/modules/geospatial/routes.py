"""Spatial read API: authorize territories before querying PostGIS points."""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.modules.authorization.service import matching_assignments
from app.modules.forms.routes import current_user
from app.modules.sync.routes import fail
from app.modules.territories.models import Territory
from app.modules.users.models import User

router = APIRouter(prefix="/api/reports/geospatial", tags=["geospatial"])


@router.get("/points")
def points(
    start: date,
    end: date,
    territory_id: uuid.UUID | None = None,
    form_id: uuid.UUID | None = None,
    limit: int = Query(default=500, ge=1, le=500),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if end < start or (end - start).days > 365:
        fail(422, "PERIOD_RANGE_INVALID")
    # Resolve Phase 2 permission, descendants and clearance first. The resulting
    # territory/clearance pairs are predicates inside every PostGIS query below.
    scope: dict[uuid.UUID, int] = {}
    for identifier in session.scalars(
        select(Territory.id).where(
            Territory.tenant_id == user.tenant_id,
            Territory.active.is_(True),
        )
    ):
        if territory_id is not None and identifier != territory_id:
            continue
        matches = matching_assignments(
            session,
            user_id=user.id,
            action="reports:read",
            territory_id=identifier,
            required_clearance=0,
        )
        if matches:
            scope[identifier] = max(item.clearance_level for item in matches)
    if not scope:
        return {
            "start": str(start), "end": str(end), "total": 0,
            "truncated": False, "items": [], "available_forms": [],
        }
    params: dict[str, Any] = {"tenant": user.tenant_id, "start": start, "end": end, "limit": limit}
    clauses = []
    for index, (identifier, clearance) in enumerate(scope.items()):
        clauses.append(
            f"(p.territory_id = :territory_{index} "
            f"AND p.required_clearance <= :clearance_{index})"
        )
        params[f"territory_{index}"] = identifier
        params[f"clearance_{index}"] = clearance
    predicate = " OR ".join(clauses)
    # Keep the filter choices independent of the selected period and form. A
    # zero-result selection must still be reversible without clearing all filters.
    forms = session.execute(text(f"""
        SELECT DISTINCT p.form_id, form.name
        FROM report_geo_points p
        JOIN reports r ON r.id = p.report_id AND r.current_revision_id = p.revision_id
        JOIN forms form ON form.id = p.form_id
        WHERE p.tenant_id = :tenant AND r.tenant_id = :tenant
          AND ({predicate})
        ORDER BY form.name, p.form_id
    """), params).mappings()
    available_forms = [
        {"id": str(row["form_id"]), "name": row["name"]}
        for row in forms
    ]
    form_clause = " AND p.form_id = :form_id" if form_id is not None else ""
    if form_id is not None:
        params["form_id"] = form_id
    source = f"""
        FROM report_geo_points p
        JOIN reports r ON r.id = p.report_id AND r.current_revision_id = p.revision_id
        JOIN report_revisions rr ON rr.id = p.revision_id
        JOIN territories territory ON territory.id = p.territory_id
        JOIN forms form ON form.id = p.form_id
        WHERE p.tenant_id = :tenant AND r.tenant_id = :tenant
          AND p.period_start BETWEEN :start AND :end
          AND ({predicate}){form_clause}
    """
    total: int = session.execute(text(f"SELECT count(*) {source}"), params).scalar_one()
    rows = session.execute(text(f"""
        SELECT p.report_id, p.revision_id, rr.number AS revision_number,
               p.activity_index, p.territory_id, territory.name AS territory_name,
               p.form_id, form.name AS form_name, p.period_start,
               ST_Y(p.location) AS latitude, ST_X(p.location) AS longitude
        {source}
        ORDER BY p.period_start DESC, p.report_id, p.activity_index
        LIMIT :limit
    """), params).mappings()
    return {
        "start": str(start), "end": str(end), "total": total,
        "truncated": total > limit,
        "available_forms": available_forms,
        "items": [
            {
                "report_id": str(row["report_id"]),
                "revision_id": str(row["revision_id"]),
                "revision_number": row["revision_number"],
                "activity_index": row["activity_index"],
                "territory_id": str(row["territory_id"]),
                "territory_name": row["territory_name"],
                "form_id": str(row["form_id"]),
                "form_name": row["form_name"],
                "period_start": row["period_start"].isoformat(),
                "latitude": row["latitude"],
                "longitude": row["longitude"],
            }
            for row in rows
        ],
    }
