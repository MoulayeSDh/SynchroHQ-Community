import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import Base, get_session
from app.main import create_app
from app.modules.authorization.models import AssignmentScope, Permission, Role, RolePermission
from app.modules.identity.bootstrap import BootstrapInput, bootstrap
from app.modules.identity.models import AuthSession, Tenant, UserCredential
from app.modules.identity.security import hash_password
from app.modules.organizations.models import Organization
from app.modules.territories.models import Territory
from app.modules.users.models import User, UserAssignment


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    monkeypatch.setattr(
        get_settings(), "auth_jwt_secret", "test-only-unique-jwt-secret-32-characters"
    )
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    session.add_all([Permission(code="administration:read"), Permission(code="reports:read")])
    session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        yield client, session
    session.close()
    engine.dispose()


def values() -> BootstrapInput:
    return BootstrapInput("pilot", "Pilot tenant", "admin@example.test", "Pilot admin",
                          "National territory", "National office")


def test_bootstrap_is_once_and_grants_scoped_admin(production):
    client, session = production
    tenant = bootstrap(session, values(), "A-long-private-password-123")
    session.commit()
    assert tenant.code == "PILOT"
    assert session.scalar(select(UserCredential.password_hash)).startswith("$argon2id$")
    with pytest.raises(ValueError, match="already initialized"):
        bootstrap(session, values(), "Another-long-password-123")
    session.rollback()
    response = client.post("/api/session/login", json={
        "identifier": "ADMIN@example.test", "password": "A-long-private-password-123"})
    assert response.status_code == 200
    token = response.json()["token"]
    info = client.get("/api/session", headers={"Authorization": f"Bearer {token}"})
    assert info.status_code == 200
    assert info.json()["tenant_id"] == str(tenant.id)
    assert "administration:read" in info.json()["permissions"]
    assert len(info.json()["territories"]) == 1
    other = Territory(tenant_id=uuid.uuid4(), code="OTHER", name="Other", type_code="NATIONAL")
    session.add(other)
    session.commit()
    assert str(other.id) not in info.text
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/session/logout", headers=headers).status_code == 204
    assert client.get("/api/session", headers=headers).status_code == 401


def test_bad_password_disabled_user_and_tenant_are_refused(production, caplog):
    client, session = production
    tenant = bootstrap(session, values(), "A-long-private-password-123")
    session.commit()
    identifier = "admin@example.test"
    assert client.post("/api/session/login", json={
        "identifier": identifier, "password": "wrong-password"}).status_code == 401
    assert client.post("/api/session/login", json={
        "identifier": "unknown@example.test", "password": "wrong-password"}).status_code == 401
    user = session.scalar(select(User).where(User.subject == identifier))
    user.active = False
    session.commit()
    assert client.post("/api/session/login", json={
        "identifier": identifier, "password": "A-long-private-password-123"}).status_code == 401
    user.active = True
    tenant.active = False
    session.commit()
    assert client.post("/api/session/login", json={
        "identifier": identifier, "password": "A-long-private-password-123"}).status_code == 401
    assert "A-long-private-password-123" not in caplog.text


def test_self_service_password_change_revokes_old_sessions(production, caplog):
    client, session = production
    old_password = "A-long-private-password-123"
    new_password = "Different-private-password-456"
    bootstrap(session, values(), old_password)
    session.commit()

    def sign_in(password):
        return client.post("/api/session/login", json={
            "identifier": "admin@example.test", "password": password,
        })

    first = sign_in(old_password).json()["token"]
    second = sign_in(old_password).json()["token"]
    headers = {"Authorization": f"Bearer {first}"}
    endpoint = "/api/session/change-password"
    assert client.post(endpoint, json={"current_password": old_password,
                                       "new_password": new_password}).status_code == 401
    assert client.post(endpoint, headers=headers, json={
        "current_password": "incorrect", "new_password": new_password,
    }).status_code == 401
    assert client.post(endpoint, headers=headers, json={
        "current_password": old_password, "new_password": "short",
    }).status_code == 400
    assert client.get("/api/session", headers=headers).status_code == 200

    changed = client.post(endpoint, headers=headers, json={
        "current_password": old_password, "new_password": new_password,
    })
    assert changed.status_code == 200
    assert session.scalar(select(UserCredential.password_hash)).startswith("$argon2id$")
    assert sign_in(old_password).status_code == 401
    assert client.get("/api/session", headers=headers).status_code == 401
    assert client.get("/api/session", headers={
        "Authorization": f"Bearer {second}",
    }).status_code == 401
    assert client.get("/api/session", headers={
        "Authorization": f"Bearer {changed.json()['token']}",
    }).status_code == 200
    assert sign_in(new_password).status_code == 200
    assert old_password not in caplog.text and new_password not in caplog.text


def test_expired_session_and_unassigned_user_have_no_access(production):
    client, session = production
    tenant = bootstrap(session, values(), "A-long-private-password-123")
    session.commit()
    user = User(tenant_id=tenant.id, subject="viewer@example.test", display_name="Viewer")
    session.add(user)
    session.flush()
    session.add(UserCredential(user_id=user.id, password_hash=hash_password("Viewer-password-123"),
                               password_changed_at=datetime.now(UTC)))
    session.commit()
    token = client.post("/api/session/login", json={
        "identifier": "viewer@example.test", "password": "Viewer-password-123"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/session/administration", headers=headers).status_code == 403
    record = session.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
    record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    assert client.get("/api/session", headers=headers).status_code == 401
    assert client.get("/api/session").status_code == 401


def test_production_rejects_unmanaged_tokens_and_disables_existing_sessions(production):
    client, session = production
    bootstrap(session, values(), "A-long-private-password-123")
    session.commit()
    user = session.scalar(select(User).where(User.subject == "admin@example.test"))
    settings = get_settings()
    now = datetime.now(UTC)
    legacy = jwt.encode({
        "sub": str(user.id), "iss": settings.auth_issuer, "aud": settings.auth_audience,
        "iat": now, "exp": now + timedelta(hours=1),
    }, settings.auth_jwt_secret, algorithm="HS256")
    legacy_headers = {"Authorization": f"Bearer {legacy}"}
    assert client.get("/api/session", headers=legacy_headers).status_code == 401
    token = client.post("/api/session/login", json={
        "identifier": user.subject, "password": "A-long-private-password-123"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/session", headers=headers).status_code == 200
    user.active = False
    session.commit()
    assert client.get("/api/session", headers=headers).status_code == 401


def test_another_tenant_cannot_see_the_bootstrap_tenant(production):
    client, session = production
    primary = bootstrap(session, values(), "A-long-private-password-123")
    foreign = Tenant(code="OTHER", name="Other tenant")
    session.add(foreign)
    session.flush()
    area = Territory(tenant_id=foreign.id, code="ROOT", name="Foreign root", type_code="ROOT")
    org = Organization(tenant_id=foreign.id, code="ADMIN", name="Other organization",
                       type_code="OPERATOR")
    role = Role(tenant_id=foreign.id, code="READER", name="Reader")
    user = User(tenant_id=foreign.id, subject="foreign@example.test", display_name="Foreign")
    session.add_all([area, org, role, user])
    session.flush()
    assignment = UserAssignment(user_id=user.id, organization_id=org.id, role_id=role.id,
                                clearance_level=1, valid_from=datetime.now(UTC))
    session.add(assignment)
    session.flush()
    permission = session.scalar(select(Permission).where(Permission.code == "reports:read"))
    session.add_all([
        AssignmentScope(assignment_id=assignment.id, territory_id=area.id, coverage="SELF"),
        RolePermission(role_id=role.id, permission_id=permission.id),
        UserCredential(user_id=user.id, password_hash=hash_password("Foreign-password-123"),
                       password_changed_at=datetime.now(UTC)),
    ])
    session.commit()
    token = client.post("/api/session/login", json={
        "identifier": user.subject, "password": "Foreign-password-123"}).json()["token"]
    info = client.get("/api/session", headers={"Authorization": f"Bearer {token}"})
    assert info.status_code == 200
    assert info.json()["tenant_id"] == str(foreign.id)
    assert len(info.json()["territories"]) == 1
    assert str(primary.id) not in info.text
    assert str(area.id) in info.text


def test_bootstrap_identity_survives_database_reopen(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    monkeypatch.setattr(
        get_settings(), "auth_jwt_secret", "test-only-unique-jwt-secret-32-characters"
    )
    db_url = f"sqlite:///{tmp_path / 'identity.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Permission(code="administration:read"))
        session.commit()
        bootstrap(session, values(), "A-long-private-password-123")
        session.commit()
    engine.dispose()
    reopened = create_engine(db_url)
    with Session(reopened) as session:
        app = create_app()
        app.dependency_overrides[get_session] = lambda: session
        with TestClient(app) as client:
            response = client.post("/api/session/login", json={
                "identifier": "admin@example.test", "password": "A-long-private-password-123"})
            assert response.status_code == 200
            token = response.json()["token"]
            assert client.get("/api/session", headers={
                "Authorization": f"Bearer {token}"}).status_code == 200
    reopened.dispose()
