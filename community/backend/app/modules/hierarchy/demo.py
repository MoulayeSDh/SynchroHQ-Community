"""Synthetic actors and explicit obligations; development environment only."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.modules.authorization.models import AssignmentScope, Permission, Role, RolePermission
from app.modules.forms.models import Form, FormVersion
from app.modules.hierarchy.models import ReportingRequirement
from app.modules.hierarchy.service import generate
from app.modules.organizations.models import Organization
from app.modules.territories.models import Territory
from app.modules.users.models import User, UserAssignment


def main() -> None:
    settings = get_settings()
    if settings.app_env != "development":
        raise SystemExit("Development only")
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, "synchrohq:phase6b-demo")

    def ident(name: str) -> uuid.UUID:
        return uuid.uuid5(namespace, name)

    now = datetime.now(UTC)
    period = (now - timedelta(days=1)).date()
    root = Path(__file__).resolve().parents[5]
    pilot = json.loads((root / "community/forms/pilot-form.json").read_text(encoding="utf-8"))
    roles = {
        "AUTHOR": [
            "forms:read",
            "drafts:sync",
            "reports:create",
            "reports:confirm",
            "reports:correct",
            "reports:read",
        ],
        "REVIEWER": [
            "reports:read",
            "reports:comment",
            "reports:request-correction",
            "reports:review",
        ],
        "CENTRAL": ["reports:read"],
        "ADMIN": [
            "administration:read",
            "forms:read",
            "forms:manage",
            "forms:publish",
            "reports:read",
            "reporting:manage",
        ],
    }
    with SessionLocal() as session:

        def add(entity: Any) -> None:
            if session.get(type(entity), entity.id) is None:
                session.add(entity)
                session.flush()

        for code, parent, kind in (
            ("NATIONAL", None, "NATIONAL"),
            ("WILAYA_A", "NATIONAL", "WILAYA"),
            ("WILAYA_B", "NATIONAL", "WILAYA"),
            ("MOUGHATAA_A1", "WILAYA_A", "MOUGHATAA"),
        ):
            add(
                Territory(
                    id=ident(code),
                    tenant_id=namespace,
                    code=code,
                    name=code,
                    type_code=kind,
                    parent_id=ident(parent) if parent else None,
                )
            )
        for code, actions in roles.items():
            role = Role(id=ident("role:" + code), tenant_id=namespace, code=code, name=code)
            add(role)
            for action in actions:
                permission = session.scalar(select(Permission).where(Permission.code == action))
                assert permission is not None, "Apply migrations first"
                if session.get(RolePermission, (role.id, permission.id)) is None:
                    session.add(RolePermission(role_id=role.id, permission_id=permission.id))
        actors = {}

        def actor(
            code: str, role: str, territory: str, coverage: str, clearance: int, orgcode: str
        ) -> User:
            org = Organization(
                id=ident("org:" + orgcode),
                tenant_id=namespace,
                code=orgcode,
                name=orgcode,
                type_code="ADMIN",
            )
            add(org)
            user = User(
                id=ident("user:" + code),
                tenant_id=namespace,
                subject="phase6b:" + code,
                display_name=code,
            )
            add(user)
            assignment = UserAssignment(
                id=ident("assignment:" + code),
                user_id=user.id,
                organization_id=org.id,
                role_id=ident("role:" + role),
                clearance_level=clearance,
                valid_from=now - timedelta(days=1),
            )
            add(assignment)
            if session.get(AssignmentScope, (assignment.id, ident(territory))) is None:
                session.add(
                    AssignmentScope(
                        assignment_id=assignment.id,
                        territory_id=ident(territory),
                        coverage=coverage,
                    )
                )
            token = jwt.encode(
                {
                    "sub": str(user.id),
                    "iss": settings.auth_issuer,
                    "aud": settings.auth_audience,
                    "exp": now + timedelta(hours=4),
                },
                settings.auth_jwt_secret,
                algorithm="HS256",
            )
            actors[code] = {
                "id": str(user.id),
                "token": token,
                "organization_id": str(org.id),
                "territory_id": str(ident(territory)),
            }
            return user

        admin = actor("admin", "ADMIN", "NATIONAL", "DESCENDANTS", 4, "CENTRAL_ADMIN")
        actor("reviewer", "REVIEWER", "MOUGHATAA_A1", "DESCENDANTS", 2, "ADMIN_A1")
        actor("regional", "REVIEWER", "WILAYA_A", "DESCENDANTS", 3, "ADMIN_WILAYA_A")
        actor("central", "CENTRAL", "NATIONAL", "DESCENDANTS", 4, "CENTRAL")
        actor("other_wilaya", "REVIEWER", "WILAYA_B", "DESCENDANTS", 3, "ADMIN_WILAYA_B")
        obligations = []
        for number in range(1, 11):
            territory = f"COMMUNE_A1{number:02}"
            add(
                Territory(
                    id=ident(territory),
                    tenant_id=namespace,
                    code=territory,
                    name=territory,
                    type_code="COMMUNE",
                    parent_id=ident("MOUGHATAA_A1"),
                )
            )
            actor(f"author_{number}", "AUTHOR", territory, "SELF", 1, "MAIRIE_" + territory)
            form = Form(
                id=ident("form:" + territory),
                tenant_id=namespace,
                territory_id=ident(territory),
                required_clearance=1,
                code="daily-" + territory,
                name="Rapport quotidien " + territory,
            )
            add(form)
            version = FormVersion(
                id=ident("version:" + territory),
                form_id=form.id,
                version=1,
                status="PUBLISHED",
                **pilot,
                published_at=now,
                published_by=admin.id,
            )
            add(version)
            requirement = ReportingRequirement(
                id=ident(f"requirement:{territory}:{period}"),
                tenant_id=namespace,
                form_id=form.id,
                organization_id=uuid.UUID(actors[f"author_{number}"]["organization_id"]),
                territory_id=ident(territory),
                required_clearance=1,
                cadence="DAILY",
                active_from=period,
                active_until=period,
                timezone="Africa/Nouakchott",
                deadline_hour=23 if number <= 8 else 18,
                deadline_days=1 if number <= 8 else 0,
                created_by=admin.id,
                created_at=now,
            )
            add(requirement)
            expected = generate(session, requirement, period, period)[0]
            obligations.append(
                {
                    "author": f"author_{number}",
                    "expected_id": str(expected.id),
                    "form_id": str(form.id),
                    "version_id": str(version.id),
                    "territory_id": str(ident(territory)),
                    "expected_by": expected.expected_by.isoformat(),
                }
            )
        session.commit()
    directory = root / ".local"
    directory.mkdir(exist_ok=True)
    (directory / "hierarchy-demo.json").write_text(
        json.dumps(
            {
                "tenant_id": str(namespace),
                "period": str(period),
                "actors": actors,
                "obligations": obligations,
            }
        ),
        encoding="utf-8",
    )
    print("Hierarchy demo ready: credentials in .local/hierarchy-demo.json (4 hours).")


if __name__ == "__main__":
    main()
