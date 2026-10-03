# ruff: noqa: F811
import copy
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
import rfc8785
from sqlalchemy import func, select
from test_forms import CASES
from test_sync import env, setup_sync  # noqa: F401

from app.core.config import get_settings
from app.modules.authorization.models import AssignmentScope, Permission, RolePermission
from app.modules.identity.security import get_current_user_id
from app.modules.reports.models import ConfirmationProof, Report, ReportOperation, ReportRevision
from app.modules.users.models import UserAssignment


def prepare(env, attachments=False, monkeypatch=None):
    client, session, _, user, _, _, *_, role = env
    draft, _, _ = setup_sync(env)
    permissions = [Permission(code="reports:" + action) for action in ("create", "confirm", "read")]
    session.add_all(permissions)
    session.flush()
    session.add_all([RolePermission(role_id=role.id, permission_id=p.id) for p in permissions])
    session.commit()
    context_response = client.post("/api/reports/contexts/" + draft["form_version_id"])
    assert context_response.status_code == 200, context_response.text
    context = context_response.json()
    draft["answers"] = copy.deepcopy(CASES[0]["answers"])
    if attachments:
        content = b"%PDF-1.4\nConfirmed evidence\n%%EOF"
        metadata = {
            "attachment_id": str(uuid.uuid4()),
            "file_name": "proof.pdf",
            "mime_type": "application/pdf",
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        draft["answers"]["attachments"] = [metadata]
    assert client.post("/api/sync/drafts", json=draft).status_code == 200
    now = datetime.now(UTC).isoformat()
    payload = {
        "schema_version": "synchrohq.report/v1",
        "report_id": str(uuid.uuid4()),
        "revision_id": str(uuid.uuid4()),
        "revision_number": 1,
        "draft_id": draft["draft_id"],
        "device_id": draft["device_id"],
        "snapshot": context["snapshot"],
        "answers": draft["answers"],
        "attachments": draft["answers"].get("attachments", []),
        "created_at": now,
        "finalized_at": now,
        "confirmed_at": now,
    }
    request = request_for(payload, context["context_token"])
    return draft, payload, request


def request_for(payload, token, operation_id=None):
    canonical = rfc8785.dumps(payload)
    return {
        "operation_id": operation_id or str(uuid.uuid4()),
        "canonical_payload": canonical.decode(),
        "payload_hash": hashlib.sha256(canonical).hexdigest(),
        "context_token": token,
    }


def test_confirmation_retry_freezes_snapshot_and_rejects_source_edits(env):
    client, session, _, user, *_ = env
    draft, payload, request = prepare(env)
    first = client.post("/api/reports/confirmations", json=request)
    assert first.status_code == 200, first.text
    assert first.json()["payload_hash"] == request["payload_hash"]
    user.display_name = "New name after confirmation"
    session.commit()
    assert client.post("/api/reports/confirmations", json=request).json() == first.json()
    viewed = client.get("/api/reports/" + payload["report_id"])
    assert viewed.status_code == 200
    assert viewed.json()["revisions"][0]["payload"] == payload
    assert len(client.get("/api/reports").json()) == 1
    for model in (Report, ReportRevision, ConfirmationProof, ReportOperation):
        assert session.scalar(select(func.count()).select_from(model)) == 1
    draft.update(operation_id=str(uuid.uuid4()), base_version=1)
    draft["answers"] = {}
    response = client.post("/api/sync/drafts", json=draft)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "DRAFT_CONFIRMED_IMMUTABLE"
    assert (
        client.patch("/api/reports/" + payload["report_id"], json={"answers": {}}).status_code
        == 405
    )


@pytest.mark.parametrize(
    "change,expected",
    [
        ("hash", "CONFIRMATION_HASH_MISMATCH"),
        ("snapshot", "REPORT_SNAPSHOT_MISMATCH"),
        ("answers", "REPORT_ANSWERS_INVALID"),
        ("canonical", "REPORT_NOT_CANONICAL"),
    ],
)
def test_rejects_tampered_proof_invalid_answers_and_noncanonical_content(env, change, expected):
    client, session, *_ = env
    _, payload, request = prepare(env)
    if change == "hash":
        request["payload_hash"] = "0" * 64
    elif change == "snapshot":
        payload["snapshot"]["author"]["display_name"] = "Forged author"
        request = request_for(payload, request["context_token"])
    elif change == "answers":
        payload["answers"] = {}
        request = request_for(payload, request["context_token"])
    else:
        request["canonical_payload"] = json.dumps(payload, indent=2)
        request["payload_hash"] = hashlib.sha256(request["canonical_payload"].encode()).hexdigest()
    response = client.post("/api/reports/confirmations", json=request)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == expected
    assert session.scalar(select(func.count()).select_from(Report)) == 0


def test_revoked_permission_blocks_new_confirmation_but_persistent_retry_survives(env):
    client, session, *_, role = env
    _, _, request = prepare(env)
    permission = session.scalar(select(Permission).where(Permission.code == "reports:confirm"))
    mapping = session.get(RolePermission, (role.id, permission.id))
    session.delete(mapping)
    session.commit()
    rejected = client.post("/api/reports/confirmations", json=request)
    assert rejected.status_code == 403
    assert rejected.json()["detail"]["code"] == "REPORT_PERMISSION_REVOKED"
    session.add(RolePermission(role_id=role.id, permission_id=permission.id))
    session.commit()
    accepted = client.post("/api/reports/confirmations", json=request)
    assert accepted.status_code == 200
    session.delete(session.get(RolePermission, (role.id, permission.id)))
    session.commit()
    assert client.post("/api/reports/confirmations", json=request).json() == accepted.json()


def test_expired_context_and_reused_operation_cannot_change_confirmation(env):
    client, session, *_ = env
    _, payload, request = prepare(env)
    settings = get_settings()
    claims = jwt.decode(
        request["context_token"],
        settings.auth_jwt_secret,
        algorithms=["HS256"],
        audience="synchrohq-report-context",
        issuer=settings.auth_issuer,
    )
    claims["exp"] = int((datetime.now(UTC) - timedelta(seconds=1)).timestamp())
    expired = {
        **request,
        "context_token": jwt.encode(claims, settings.auth_jwt_secret, algorithm="HS256"),
    }
    assert client.post("/api/reports/confirmations", json=expired).status_code == 403
    assert client.post("/api/reports/confirmations", json=request).status_code == 200
    payload["answers"]["executive_summary"] = "Changed after confirmation"
    changed = request_for(payload, request["context_token"], request["operation_id"])
    response = client.post("/api/reports/confirmations", json=changed)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "OPERATION_ID_REUSED"
    assert session.scalar(select(func.count()).select_from(ReportRevision)) == 1


def test_read_and_download_deny_foreign_tenant_scope_and_insufficient_clearance(env):
    client, session, app, user, foreign, _, other_area, *_ = env
    _, payload, request = prepare(env)
    assert client.post("/api/reports/confirmations", json=request).status_code == 200
    report_path = "/api/reports/" + payload["report_id"]
    attachment_path = report_path + "/attachments/" + str(uuid.uuid4())
    app.dependency_overrides[get_current_user_id] = lambda: foreign.id
    assert client.get(report_path).status_code == 404
    assert client.get(attachment_path).status_code == 404
    assert client.get("/api/reports").json() == []
    app.dependency_overrides[get_current_user_id] = lambda: user.id
    assignment = session.scalar(select(UserAssignment).where(UserAssignment.user_id == user.id))
    assignment.clearance_level = 0
    session.commit()
    assert client.get(report_path).status_code == 404
    assignment.clearance_level = 4
    scope = session.scalar(
        select(AssignmentScope).where(AssignmentScope.assignment_id == assignment.id)
    )
    scope.territory_id = other_area.id
    session.commit()
    assert client.get(report_path).status_code == 404
    assert client.get("/api/reports").json() == []


def test_confirmation_waits_for_all_files_then_links_exact_checksum(env, monkeypatch):
    client, session, *_ = env
    draft, payload, request = prepare(env, attachments=True)
    rejected = client.post("/api/reports/confirmations", json=request)
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "REPORT_ATTACHMENT_NOT_RECEIVED"
    metadata = payload["attachments"][0]
    monkeypatch.setattr("app.modules.sync.routes.put_object", lambda *_: None)
    upload = client.put(
        f"/api/sync/drafts/{draft['draft_id']}/attachments/{metadata['attachment_id']}",
        data={k: str(v) for k, v in metadata.items() if k != "attachment_id"},
        files={"file": ("proof.pdf", b"%PDF-1.4\nConfirmed evidence\n%%EOF", "application/pdf")},
    )
    assert upload.status_code == 200, upload.text
    assert client.post("/api/reports/confirmations", json=request).status_code == 200
    assert client.get("/api/reports/" + payload["report_id"]).json()["revisions"][0]["payload"][
        "attachments"
    ] == [metadata]
