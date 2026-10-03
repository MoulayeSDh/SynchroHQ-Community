import copy
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import Base, get_session
from app.main import create_app
from app.modules.authorization.models import AssignmentScope, Permission, Role, RolePermission
from app.modules.forms.models import FormAuditEvent, FormVersion
from app.modules.forms.schemas import Envelope
from app.modules.forms.validation import validate_answers, validate_envelope
from app.modules.identity.security import get_current_user_id
from app.modules.organizations.models import Organization
from app.modules.territories.models import Territory
from app.modules.users.models import User, UserAssignment

FIXTURES = Path(__file__).resolve().parents[2] / "forms"
PILOT = json.loads((FIXTURES / "pilot-form.json").read_text(encoding="utf-8"))
CASES = json.loads((FIXTURES / "validation-cases.json").read_text(encoding="utf-8"))


@pytest.fixture
def env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    tenant = uuid.uuid4()
    area = Territory(tenant_id=tenant, code="A", name="A", type_code="WILAYA")
    other_area = Territory(tenant_id=tenant, code="B", name="B", type_code="WILAYA")
    foreign_area = Territory(tenant_id=uuid.uuid4(), code="F", name="F", type_code="WILAYA")
    user = User(tenant_id=tenant, subject="forms-admin", display_name="Forms administrator")
    foreign_user = User(tenant_id=foreign_area.tenant_id, subject="foreign", display_name="Foreign")
    role = Role(tenant_id=tenant, code="FORMS_ADMIN", name="Forms admin")
    org = Organization(tenant_id=tenant, code="O", name="O", type_code="ADMIN")
    permissions = [Permission(code=f"forms:{v}") for v in ("read", "manage", "publish")]
    session.add_all([area, other_area, foreign_area, user, foreign_user, role, org, *permissions])
    session.flush()
    assignment = UserAssignment(
        user_id=user.id,
        organization_id=org.id,
        role_id=role.id,
        clearance_level=2,
        valid_from=datetime.now(UTC) - timedelta(days=1),
    )
    session.add(assignment)
    session.flush()
    session.add(AssignmentScope(assignment_id=assignment.id, territory_id=area.id, coverage="SELF"))
    session.add_all([RolePermission(role_id=role.id, permission_id=p.id) for p in permissions])
    session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user_id] = lambda: user.id
    with TestClient(app) as client:
        yield client, session, app, user, foreign_user, area, other_area, foreign_area, role
    session.close()
    engine.dispose()


def create(client, area):
    response = client.post(
        "/api/forms",
        json={
            "code": "pilot",
            "name": "Pilot",
            "territory_id": str(area.id),
            "required_clearance": 1,
        },
    )
    assert response.status_code == 201, response.text
    form_id = response.json()["id"]
    response = client.post(f"/api/forms/{form_id}/versions", json=PILOT)
    assert response.status_code == 201, response.text
    return form_id, f"/api/forms/{form_id}/versions/1"


def test_full_lifecycle_and_stateless_validation(env):
    client, session, _, user, _, area, *_ = env
    form_id, path = create(client, area)
    assert client.patch(path, json=PILOT).status_code == 200
    published = client.post(path + "/publish")
    assert published.status_code == 200, published.text
    assert published.json()["published_by"] == str(user.id)
    assert published.json()["published_at"]
    assert client.patch(path, json=PILOT).status_code == 409
    assert client.post(path + "/publish").status_code == 409
    assert client.get(path).json()["data_schema"] == PILOT["data_schema"]
    for case in CASES:
        result = client.post(path + "/validate", json={"answers": case["answers"]})
        assert result.status_code == 200
        assert result.json()["valid"] == case["valid"], case["name"]
    assert client.post(path + "/retire").json()["status"] == "RETIRED"
    assert client.patch(path, json=PILOT).status_code == 409
    assert client.post(path + "/publish").status_code == 409
    assert client.post(path + "/retire").status_code == 409
    assert client.get(path).json()["translations"] == PILOT["translations"]
    clone = client.post(f"/api/forms/{form_id}/versions", json=PILOT)
    assert clone.status_code == 201 and clone.json()["version"] == 2
    assert clone.json()["status"] == "DRAFT"
    events = list(session.scalars(select(FormAuditEvent).order_by(FormAuditEvent.occurred_at)))
    assert [e.action for e in events] == ["FORM_VERSION_PUBLISHED", "FORM_VERSION_RETIRED"]
    assert events[0].actor_name == user.display_name
    assert len(list(session.scalars(select(FormVersion)))) == 2


def test_tenant_scope_clearance_and_unknown_resources(env):
    client, _, app, user, foreign_user, area, other, foreign_area, _ = env
    form_id, path = create(client, area)
    assert len(client.get("/api/forms").json()) == 1
    for territory, clearance in [(other, 0), (foreign_area, 0), (area, 3)]:
        response = client.post(
            "/api/forms",
            json={
                "code": "forbidden",
                "name": "Forbidden",
                "territory_id": str(territory.id),
                "required_clearance": clearance,
            },
        )
        assert response.status_code == 403
    app.dependency_overrides[get_current_user_id] = lambda: foreign_user.id
    assert client.get("/api/forms").json() == []
    assert client.get(f"/api/forms/{form_id}").status_code == 404
    for suffix in ("", "/publish", "/retire", "/validate"):
        response = (
            client.get(path) if not suffix else client.post(path + suffix, json={"answers": {}})
        )
        assert response.status_code == 404
    assert client.patch(path, json=PILOT).status_code == 404
    app.dependency_overrides[get_current_user_id] = lambda: user.id
    assert client.get(path.rsplit("/", 1)[0] + "/99").status_code == 404


@pytest.mark.parametrize("action", ["read", "manage", "publish"])
def test_permissions_are_independent(env, action):
    client, session, _, _, _, area, *_, role = env
    form_id, path = create(client, area)
    permission = session.scalar(select(Permission).where(Permission.code == f"forms:{action}"))
    grant = session.get(RolePermission, (role.id, permission.id))
    session.delete(grant)
    session.commit()
    if action == "read":
        assert client.get("/api/forms").json() == []
        assert client.get(path).status_code == 403
        assert client.post(path + "/validate", json={"answers": {}}).status_code == 403
        assert client.post(path + "/publish").status_code == 200
    elif action == "manage":
        assert client.patch(path, json=PILOT).status_code == 403
        assert client.post(f"/api/forms/{form_id}/versions", json=PILOT).status_code == 403
        assert client.get(path).status_code == 200
    else:
        assert client.post(path + "/publish").status_code == 403
        assert client.patch(path, json=PILOT).status_code == 200


def test_invalid_envelopes_and_duplicate_codes(env):
    client, _, _, _, _, area, *_ = env
    form_id, path = create(client, area)
    invalid = copy.deepcopy(PILOT)
    invalid["data_schema"]["properties"]["remote"] = {"$ref": "https://example.com/schema"}
    assert client.patch(path, json=invalid).status_code == 422
    invalid = copy.deepcopy(PILOT)
    invalid["data_schema"]["properties"]["activities"]["maxItems"] = 100000
    assert client.post(f"/api/forms/{form_id}/versions", json=invalid).status_code == 422
    invalid = copy.deepcopy(PILOT)
    invalid["translations"]["ar"] = {}
    assert client.patch(path, json=invalid).status_code == 422
    invalid = copy.deepcopy(PILOT)
    invalid["data_schema"]["type"] = "not-a-type"
    assert client.patch(path, json=invalid).status_code == 422
    assert (
        client.post(
            "/api/forms", json={"code": "pilot", "name": "Duplicate", "territory_id": str(area.id)}
        ).status_code
        == 409
    )


def test_unauthenticated_and_inactive_users(env):
    client, session, app, user, *_ = env
    user.active = False
    session.commit()
    assert client.get("/api/forms").status_code == 401
    del app.dependency_overrides[get_current_user_id]
    assert client.get("/api/forms").status_code == 401


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_shared_validation_contract(case):
    validate_envelope(Envelope.model_validate(PILOT))
    result = validate_answers(PILOT["data_schema"], case["answers"])
    assert result.valid == case["valid"]
    if case["name"] == "support-required":
        assert any(e.path == "/support_request" and e.code == "required" for e in result.errors)
    if case["name"] == "negative-quantity":
        assert any(
            e.path == "/activities/0/quantity" and e.code == "minimum" for e in result.errors
        )


def test_configured_limits(monkeypatch):
    monkeypatch.setattr(get_settings(), "form_schema_max_bytes", 20)
    with pytest.raises(Exception) as error:
        validate_envelope(Envelope.model_validate(PILOT))
    assert error.value.status_code == 422


@pytest.mark.parametrize(
    "key,value",
    [
        ("title_key", []),
        ("order", []),
        ("fields", []),
    ],
)
def test_malformed_ui_is_rejected(env, key, value):
    client, _, _, _, _, area, *_ = env
    _, path = create(client, area)
    invalid = copy.deepcopy(PILOT)
    invalid["ui_schema"][key] = value
    assert client.patch(path, json=invalid).status_code == 422


def test_widget_and_visibility_shapes_are_rejected(env):
    client, _, _, _, _, area, *_ = env
    _, path = create(client, area)
    for field, replacement in [
        ("/needs_support", {"widget": []}),
        ("/needs_support", {"widget": "textarea"}),
        ("/support_request", {"visible_when": {"path": [], "equals": True}}),
    ]:
        invalid = copy.deepcopy(PILOT)
        invalid["ui_schema"]["fields"][field].update(replacement)
        assert client.patch(path, json=invalid).status_code == 422


@pytest.mark.parametrize(
    "setting,value",
    [
        ("form_schema_max_fields", 2),
        ("form_schema_max_depth", 1),
        ("form_array_max_items", 2),
    ],
)
def test_schema_complexity_limits(monkeypatch, setting, value):
    from fastapi import HTTPException

    monkeypatch.setattr(get_settings(), setting, value)
    with pytest.raises(HTTPException) as error:
        validate_envelope(Envelope.model_validate(PILOT))
    assert error.value.status_code == 422
