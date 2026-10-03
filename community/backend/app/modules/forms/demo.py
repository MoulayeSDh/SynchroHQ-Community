"""Create a scoped, synthetic development tenant and import/publish the pilot via HTTP.

Run from community/backend: python -m app.modules.forms.demo
Credentials are saved under .local/ (gitignored), never printed to logs.
"""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

import jwt
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.modules.authorization.models import AssignmentScope, Permission, Role, RolePermission
from app.modules.organizations.models import Organization
from app.modules.territories.models import Territory
from app.modules.users.models import User, UserAssignment


def main() -> None:
    settings = get_settings()
    if settings.app_env != "development":
        raise SystemExit("The demo is restricted to APP_ENV=development")
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, "synchrohq:phase3-demo")

    def ident(name: str) -> uuid.UUID:
        return uuid.uuid5(namespace, name)

    with SessionLocal() as session:
        entities: list[Territory | Organization | Role | User] = [
            Territory(
                id=ident("area"),
                tenant_id=namespace,
                code="DEMO",
                name="Territoire pilote",
                type_code="WILAYA",
            ),
            Organization(
                id=ident("org"),
                tenant_id=namespace,
                code="DEMO",
                name="Organisation pilote",
                type_code="ADMIN",
            ),
            Role(id=ident("role"), tenant_id=namespace, code="FORMS_ADMIN", name="Forms admin"),
            User(
                id=ident("user"),
                tenant_id=namespace,
                subject="phase3-demo",
                display_name="Administrateur démo Phase 3",
            ),
        ]
        for entity in entities:
            if session.get(type(entity), entity.id) is None:
                session.add(entity)
        session.flush()
        assignment_id = ident("assignment")
        if session.get(UserAssignment, assignment_id) is None:
            session.add(
                UserAssignment(
                    id=assignment_id,
                    user_id=ident("user"),
                    organization_id=ident("org"),
                    role_id=ident("role"),
                    clearance_level=1,
                    valid_from=datetime.now(UTC) - timedelta(minutes=1),
                )
            )
            session.flush()
            session.add(
                AssignmentScope(
                    assignment_id=assignment_id, territory_id=ident("area"), coverage="SELF"
                )
            )
        for action in (
            "forms:read",
            "forms:manage",
            "forms:publish",
            "drafts:sync",
            "reports:create",
            "reports:confirm",
            "reports:read",
            "reports:comment",
            "reports:request-correction",
            "reports:correct",
        ):
            permission = session.scalar(select(Permission).where(Permission.code == action))
            if permission is None:
                raise SystemExit("Apply alembic upgrade head first")
            if session.get(RolePermission, (ident("role"), permission.id)) is None:
                session.add(RolePermission(role_id=ident("role"), permission_id=permission.id))
        session.commit()

    token = jwt.encode(
        {
            "sub": str(ident("user")),
            "iss": settings.auth_issuer,
            "aud": settings.auth_audience,
            "exp": datetime.now(UTC) + timedelta(hours=2),
        },
        settings.auth_jwt_secret,
        algorithm="HS256",
    )

    def api(path: str, body: object | None = None) -> object:
        request = Request(
            os.environ.get("FORMS_DEMO_API_URL", "http://localhost:8001") + "/api/forms" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urlopen(request, timeout=15) as response:
            return json.load(response)

    forms = api("")
    assert isinstance(forms, list)
    form = next((f for f in forms if f["code"] == "daily-territorial-report"), None)
    if form is None:
        form = api(
            "",
            {
                "code": "daily-territorial-report",
                "name": "Rapport quotidien territorial",
                "territory_id": str(ident("area")),
                "required_clearance": 1,
            },
        )
    assert isinstance(form, dict)
    versions = api(f"/{form['id']}/versions")
    assert isinstance(versions, list)
    root = Path(__file__).resolve().parents[5]
    pilot = json.loads((root / "community/forms/pilot-form.json").read_text(encoding="utf-8"))
    matching = [
        v
        for v in versions
        if v["status"] == "PUBLISHED" and all(v[key] == pilot[key] for key in pilot)
    ]
    if not matching:
        version = api(f"/{form['id']}/versions", pilot)
        assert isinstance(version, dict)
        api(f"/{form['id']}/versions/{version['version']}/publish", {})
    directory = root / ".local"
    directory.mkdir(exist_ok=True)
    (directory / "forms-demo.json").write_text(
        json.dumps({"token": token, "territory_id": str(ident("area")), "form_id": form["id"]}),
        encoding="utf-8",
    )
    print("Demo ready. Credentials: .local/forms-demo.json (expires in 2 hours).")


if __name__ == "__main__":
    main()
