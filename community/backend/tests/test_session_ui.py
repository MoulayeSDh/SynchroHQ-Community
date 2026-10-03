# ruff: noqa: F811
from datetime import UTC, datetime, timedelta

from test_forms import create, env  # noqa: F401

from app.core.config import get_settings
from app.modules.authorization.models import Permission, RolePermission
from app.modules.identity.security import get_current_user_id
from app.modules.users.models import UserAssignment


def test_metadata_scope_clearance_and_expired_assignment(env):
    client, session, app, user, foreign, area, other, *_ = env
    form_id, _path = create(client, area)
    assert client.get("/api/forms/" + form_id).json()["actions"] == {
        "manage": True,
        "publish": True,
        "collect": False,
    }
    info = client.get("/api/session").json()
    assert {t["id"] for t in info["territories"]} == {str(area.id)}
    assert "forms:manage" in info["permissions"]
    assert str(other.id) not in str(info)
    listing = client.get("/api/forms").json()
    assert listing[0]["actions"] == {"manage": True, "publish": True, "collect": False}
    assignment = session.query(UserAssignment).filter_by(user_id=user.id).one()
    assignment.clearance_level = 0
    session.commit()
    assert client.get("/api/forms").json() == []
    assignment.valid_to = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    assert client.get("/api/session").json()["permissions"] == []
    app.dependency_overrides[get_current_user_id] = lambda: foreign.id
    assert client.get("/api/session").json()["territories"] == []


def test_directory_requires_separate_permission_and_excludes_other_territories(env):
    client, session, _, _, _, area, other, *_, role = env
    assert client.get("/api/session/administration").status_code == 403
    permission = Permission(code="administration:read")
    session.add(permission)
    session.flush()
    session.add(RolePermission(role_id=role.id, permission_id=permission.id))
    session.commit()
    response = client.get("/api/session/administration")
    assert response.status_code == 200
    assert {t["id"] for t in response.json()["territories"]} == {str(area.id)}
    assert str(other.id) not in response.text


def test_demo_is_opt_in_development_only_and_has_no_arbitrary_identity(env, monkeypatch):
    client, *_ = env
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_login_enabled", False)
    assert client.get("/api/session/demo").status_code == 404
    assert client.post("/api/session/demo", json={"account": "admin"}).status_code == 404
    monkeypatch.setattr(settings, "demo_login_enabled", True)
    monkeypatch.setattr(settings, "app_env", "production")
    assert client.get("/api/session/demo").status_code == 404
    assert client.post("/api/session/demo", json={"account": "admin"}).status_code == 404
    monkeypatch.setattr(settings, "app_env", "development")
    assert client.get("/api/session/demo").json() == []
    assert client.post("/api/session/demo", json={"account": "arbitrary"}).status_code == 422
