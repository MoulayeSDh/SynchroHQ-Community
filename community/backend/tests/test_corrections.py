# ruff: noqa: F811
import copy
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from test_reports import prepare, request_for
from test_sync import env  # noqa: F401

from app.modules.authorization.models import AssignmentScope, Permission, RolePermission
from app.modules.forms.models import FormVersion
from app.modules.identity.security import get_current_user_id
from app.modules.reports.models import ReportRevision
from app.modules.users.models import User, UserAssignment


def setup_workflow(env):
    client, session, *_, role = env
    draft, payload, body = prepare(env)
    assert client.post("/api/reports/confirmations", json=body).status_code == 200
    for action in ("comment", "request-correction", "correct"):
        p = Permission(code="reports:" + action)
        session.add(p)
        session.flush()
        session.add(RolePermission(role_id=role.id, permission_id=p.id))
    session.commit()
    return draft, payload, body


def request_change(client, payload):
    body = {
        "operation_id": str(uuid.uuid4()),
        "revision_id": payload["revision_id"],
        "text": "Préciser la visite de terrain.",
    }
    response = client.post(
        "/api/reports/" + payload["report_id"] + "/correction-requests", json=body
    )
    assert response.status_code == 200, response.text
    return body, response.json()


@pytest.mark.parametrize("retired", [False, True])
def test_new_revision_resolves_request_preserves_history_and_retries(env, retired):
    client, session, *_ = env
    draft, first, original = setup_workflow(env)
    comment = {
        "operation_id": str(uuid.uuid4()),
        "revision_id": first["revision_id"],
        "text": "À vérifier.",
    }
    url = "/api/reports/" + first["report_id"]
    noted = client.post(url + "/comments", json=comment)
    assert noted.status_code == 200
    assert client.post(url + "/comments", json=comment).json() == noted.json()
    assert (
        client.post(url + "/comments", json={**comment, "text": "Autre texte"}).status_code == 409
    )
    change, receipt = request_change(client, first)
    assert client.post(url + "/correction-requests", json=change).json() == receipt
    assert (
        client.post(
            url + "/correction-requests", json={**change, "operation_id": str(uuid.uuid4())}
        ).status_code
        == 409
    )
    if retired:
        version = session.get(FormVersion, uuid.UUID(draft["form_version_id"]))
        version.status = "RETIRED"
        version.retired_at = datetime.now(UTC) - timedelta(seconds=2)
        session.commit()
    context = client.post(
        "/api/reports/contexts/" + draft["form_version_id"],
        params={"correction_request_id": receipt["id"]},
    )
    assert context.status_code == 200, context.text
    grant = context.json()
    next_draft = copy.deepcopy(draft)
    next_draft.update(
        operation_id=str(uuid.uuid4()),
        draft_id=str(uuid.uuid4()),
        base_version=0,
        sync_grant=grant["sync_grant"],
    )
    next_draft["answers"]["executive_summary"] = "Résumé corrigé avec précision de la visite."
    synced = client.post("/api/sync/drafts", json=next_draft)
    assert synced.status_code == 200, synced.text
    now = datetime.now(UTC).isoformat()
    second = {
        **first,
        "revision_id": str(uuid.uuid4()),
        "revision_number": 2,
        "draft_id": next_draft["draft_id"],
        "snapshot": grant["snapshot"],
        "answers": next_draft["answers"],
        "created_at": now,
        "finalized_at": now,
        "confirmed_at": now,
        "correction": {
            "base_revision_id": first["revision_id"],
            "correction_request_id": receipt["id"],
        },
    }
    body = request_for(second, grant["context_token"])
    confirmed = client.post("/api/reports/confirmations", json=body)
    assert confirmed.status_code == 200, confirmed.text
    assert client.post("/api/reports/confirmations", json=body).json() == confirmed.json()
    viewed = client.get(url).json()
    assert viewed["current_revision_id"] == second["revision_id"]
    assert viewed["corrections"][0]["state"] == "RESOLVED"
    assert viewed["comments"][0]["revision_id"] == first["revision_id"]
    assert viewed["revisions"][0]["payload"] == first
    assert viewed["revisions"][0]["payload_hash"] == original["payload_hash"]
    assert viewed["revisions"][0]["state"] == "SUPERSEDED"
    assert len(viewed["revisions"]) == 2
    assert (
        client.post(
            "/api/reports/contexts/" + draft["form_version_id"],
            params={"correction_request_id": receipt["id"]},
        ).status_code
        == 409
    )
    session.expire_all()
    assert len(session.scalars(select(ReportRevision)).all()) == 2


def test_permissions_and_revision_binding_are_checked(env):
    client, session, application, user, foreign, *_, role = env
    draft, payload, _ = setup_workflow(env)
    change, receipt = request_change(client, payload)
    url = "/api/reports/" + payload["report_id"]
    assert (
        client.post(
            url + "/comments",
            json={**change, "operation_id": str(uuid.uuid4()), "revision_id": str(uuid.uuid4())},
        ).status_code
        == 404
    )
    assert (
        client.post(
            url + "/comments", json={**change, "operation_id": str(uuid.uuid4()), "text": "   "}
        ).status_code
        == 422
    )
    permission = session.scalar(select(Permission).where(Permission.code == "reports:correct"))
    mapping = session.get(RolePermission, (role.id, permission.id))
    session.delete(mapping)
    session.commit()
    assert (
        client.post(
            "/api/reports/contexts/" + draft["form_version_id"],
            params={"correction_request_id": receipt["id"]},
        ).status_code
        == 403
    )
    application.dependency_overrides[get_current_user_id] = lambda: foreign.id
    assert client.get(url).status_code == 404
    assert (
        client.post(
            url + "/comments", json={**change, "operation_id": str(uuid.uuid4())}
        ).status_code
        == 404
    )


def test_same_tenant_reviewer_cannot_confirm_another_authors_correction(env):
    client, session, application, user, *_ = env
    draft, payload, _ = setup_workflow(env)
    _, receipt = request_change(client, payload)
    original = session.scalar(select(UserAssignment).where(UserAssignment.user_id == user.id))
    peer = User(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        subject="reviewer",
        display_name="Reviewer",
        active=True,
    )
    session.add(peer)
    session.flush()
    assignment = UserAssignment(
        **{
            c.name: getattr(original, c.name)
            for c in UserAssignment.__table__.columns
            if c.name not in {"id", "user_id"}
        },
        id=uuid.uuid4(),
        user_id=peer.id,
    )
    session.add(assignment)
    session.flush()
    for scope in session.scalars(
        select(AssignmentScope).where(AssignmentScope.assignment_id == original.id)
    ):
        session.add(
            AssignmentScope(
                assignment_id=assignment.id,
                territory_id=scope.territory_id,
                coverage=scope.coverage,
            )
        )
    session.commit()
    application.dependency_overrides[get_current_user_id] = lambda: peer.id
    assert client.get("/api/reports/" + payload["report_id"]).status_code == 200
    denied = client.post(
        "/api/reports/contexts/" + draft["form_version_id"],
        params={"correction_request_id": receipt["id"]},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "CORRECTION_PERMISSION_DENIED"
