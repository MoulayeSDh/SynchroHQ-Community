# ruff: noqa: F811
import hashlib
import uuid
from datetime import UTC, datetime

import jwt
import pytest
from botocore.exceptions import EndpointConnectionError
from sqlalchemy import func, select
from test_forms import create, env  # noqa: F401

from app.core.config import get_settings
from app.modules.authorization.models import Permission, RolePermission
from app.modules.identity.security import get_current_user_id
from app.modules.sync.models import CollectionDraft, DraftAttachment, SyncAuditEvent, SyncOperation


def setup_sync(env):
    client, session, _, _, _, area, *_, role = env
    _, path = create(client, area)
    version = client.post(path + "/publish").json()
    permission = Permission(code="drafts:sync")
    session.add(permission)
    session.flush()
    session.add(RolePermission(role_id=role.id, permission_id=permission.id))
    session.commit()
    grant = client.post(f"/api/sync/grants/{version['id']}")
    assert grant.status_code == 200, grant.text
    body = {
        "operation_id": str(uuid.uuid4()),
        "draft_id": str(uuid.uuid4()),
        "device_id": str(uuid.uuid4()),
        "form_version_id": version["id"],
        "base_version": 0,
        "client_updated_at": datetime.now(UTC).isoformat(),
        "answers": {},
        "sync_grant": grant.json()["sync_grant"],
    }
    return body, path, permission


def test_retry_returns_persistent_receipt_without_duplicate(env):
    client, session, *_ = env
    body, _, _ = setup_sync(env)
    first = client.post("/api/sync/drafts", json=body)
    assert first.status_code == 200, first.text
    assert first.json()["server_version"] == 1
    assert first.json()["validation"]["valid"] is False  # incomplete draft still saved
    second = client.post("/api/sync/drafts", json=body)
    assert second.json() == first.json()
    assert session.scalar(select(func.count()).select_from(CollectionDraft)) == 1
    assert session.scalar(select(func.count()).select_from(SyncOperation)) == 1
    assert session.scalar(select(func.count()).select_from(SyncAuditEvent)) == 1
    assert client.get(f"/api/sync/drafts/{body['draft_id']}").json()["version"] == 1


def test_payload_change_with_same_operation_is_rejected_and_audited(env):
    client, session, *_ = env
    body, _, _ = setup_sync(env)
    assert client.post("/api/sync/drafts", json=body).status_code == 200
    changed = {**body, "answers": {"needs_support": True}}
    rejected = client.post("/api/sync/drafts", json=changed)
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "OPERATION_ID_REUSED"
    assert (
        session.scalar(select(SyncAuditEvent).where(SyncAuditEvent.code == "OPERATION_ID_REUSED"))
        is not None
    )
    assert client.get(f"/api/sync/drafts/{body['draft_id']}").json()["answers"] == {}


def test_tampered_or_foreign_offline_grant_is_rejected(env):
    client, _, app, _, foreign, *_ = env
    body, _, _ = setup_sync(env)
    tampered = {**body, "sync_grant": body["sync_grant"] + "invalid"}
    result = client.post("/api/sync/drafts", json=tampered)
    assert result.status_code == 403
    assert result.json()["detail"]["code"] == "OFFLINE_GRANT_INVALID"
    app.dependency_overrides[get_current_user_id] = lambda: foreign.id
    result = client.post("/api/sync/drafts", json=body)
    assert result.status_code == 404


def test_conflicting_revision_never_overwrites_and_old_receipt_stays_stable(env):
    client, *_ = env
    body, _, _ = setup_sync(env)
    first = client.post("/api/sync/drafts", json=body).json()
    edit = {
        **body,
        "operation_id": str(uuid.uuid4()),
        "base_version": 1,
        "answers": {"needs_support": False},
    }
    assert client.post("/api/sync/drafts", json=edit).json()["server_version"] == 2
    conflicting = {**edit, "operation_id": str(uuid.uuid4()), "answers": {"needs_support": True}}
    result = client.post("/api/sync/drafts", json=conflicting)
    assert result.status_code == 409 and result.json()["detail"]["code"] == "VERSION_CONFLICT"
    assert client.get(f"/api/sync/drafts/{body['draft_id']}").json()["answers"] == {
        "needs_support": False
    }
    assert client.post("/api/sync/drafts", json=body).json() == first


def test_accepted_retry_stays_reproducible_but_new_operation_is_blocked(env):
    client, session, *_, role = env
    body, _, permission = setup_sync(env)
    receipt = client.post("/api/sync/drafts", json=body).json()
    session.delete(session.get(RolePermission, (role.id, permission.id)))
    session.commit()
    assert client.post("/api/sync/drafts", json=body).json() == receipt
    new_operation = {**body, "operation_id": str(uuid.uuid4()), "base_version": 1}
    result = client.post("/api/sync/drafts", json=new_operation)
    assert result.status_code == 403
    assert result.json()["detail"]["code"] == "SYNC_PERMISSION_REVOKED"
    assert session.scalar(select(func.count()).select_from(CollectionDraft)) == 1


def test_retired_form_and_foreign_identity_are_blocked(env):
    client, _, app, _, foreign, *_ = env
    body, path, _ = setup_sync(env)
    assert client.post("/api/sync/drafts", json=body).status_code == 200
    app.dependency_overrides[get_current_user_id] = lambda: foreign.id
    assert client.post("/api/sync/drafts", json=body).status_code == 404
    assert client.get(f"/api/sync/drafts/{body['draft_id']}").status_code == 404
    app.dependency_overrides[get_current_user_id] = lambda: env[3].id
    assert client.post(path + "/retire").status_code == 200
    after_retirement = {**body, "operation_id": str(uuid.uuid4()), "base_version": 1}
    assert client.post("/api/sync/drafts", json=after_retirement).status_code == 200
    assert client.post(f"/api/sync/grants/{body['form_version_id']}").status_code == 409


@pytest.mark.parametrize(
    "field,value",
    [("base_version", -1), ("device_id", "bad"), ("client_updated_at", "2026-09-28T08:00:00")],
)
def test_invalid_operation_contract(env, field, value):
    client, *_ = env
    body, _, _ = setup_sync(env)
    body[field] = value
    assert client.post("/api/sync/drafts", json=body).status_code == 422


def test_attachment_bytes_are_verified_stored_and_idempotent(env, monkeypatch):
    client, session, *_ = env
    body, _, _ = setup_sync(env)
    attachment_id = uuid.uuid4()
    content = b"%PDF-1.4\nSynchroHQ\n%%EOF"
    digest = hashlib.sha256(content).hexdigest()
    metadata = {
        "attachment_id": str(attachment_id),
        "file_name": "preuve.pdf",
        "mime_type": "application/pdf",
        "size": len(content),
        "sha256": digest,
    }
    body["answers"] = {"attachments": [metadata]}
    assert client.post("/api/sync/drafts", json=body).status_code == 200
    stored: list[tuple[bytes, str, str]] = []

    def capture(stream, key, mime_type):
        stream.seek(0)
        stored.append((stream.read(), key, mime_type))

    monkeypatch.setattr("app.modules.sync.routes.put_object", capture)
    path = f"/api/sync/drafts/{body['draft_id']}/attachments/{attachment_id}"
    data = {key: str(value) for key, value in metadata.items() if key != "attachment_id"}
    files = {"file": (metadata["file_name"], content, metadata["mime_type"])}
    first = client.put(path, data=data, files=files)
    assert first.status_code == 200, first.text
    assert first.json()["sha256"] == digest
    assert stored == [
        (
            content,
            f"{env[3].tenant_id}/drafts/{body['draft_id']}/{attachment_id}",
            "application/pdf",
        )
    ]
    second = client.put(path, data=data, files=files)
    assert second.json() == first.json()
    assert len(stored) == 1
    assert session.scalar(select(func.count()).select_from(DraftAttachment)) == 1


def test_attachment_rejects_checksum_and_metadata_mismatch(env, monkeypatch):
    client, _, *_ = env
    body, _, _ = setup_sync(env)
    attachment_id = uuid.uuid4()
    content = b"expected"
    digest = hashlib.sha256(content).hexdigest()
    metadata = {
        "attachment_id": str(attachment_id),
        "file_name": "preuve.pdf",
        "mime_type": "application/pdf",
        "size": len(content),
        "sha256": digest,
    }
    body["answers"] = {"attachments": [metadata]}
    assert client.post("/api/sync/drafts", json=body).status_code == 200
    monkeypatch.setattr("app.modules.sync.routes.put_object", lambda *_: None)
    path = f"/api/sync/drafts/{body['draft_id']}/attachments/{attachment_id}"
    data = {key: str(value) for key, value in metadata.items() if key != "attachment_id"}
    checksum = client.put(
        path, data=data, files={"file": ("preuve.pdf", b"tampered", "application/pdf")}
    )
    assert checksum.status_code == 422
    assert checksum.json()["detail"]["code"] == "ATTACHMENT_CHECKSUM_MISMATCH"
    mismatch = client.put(
        path,
        data={**data, "file_name": "other.pdf"},
        files={"file": ("other.pdf", content, "application/pdf")},
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["detail"]["code"] == "ATTACHMENT_METADATA_MISMATCH"


@pytest.mark.parametrize("retired", [False, True])
def test_expired_grant_is_strictly_rejected(env, retired):
    client, session, *_ = env
    body, path, _ = setup_sync(env)
    if retired:
        assert client.post(path + "/retire").status_code == 200
    settings = get_settings()
    claims = jwt.decode(
        body["sync_grant"],
        settings.auth_jwt_secret,
        algorithms=["HS256"],
        audience=settings.offline_grant_audience,
        issuer=settings.auth_issuer,
    )
    claims["iat"] = int(datetime.now(UTC).timestamp()) - 120
    claims["exp"] = int(datetime.now(UTC).timestamp()) - 60
    body["sync_grant"] = jwt.encode(claims, settings.auth_jwt_secret, algorithm="HS256")
    response = client.post("/api/sync/drafts", json=body)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "OFFLINE_GRANT_INVALID"
    assert session.scalar(select(func.count()).select_from(CollectionDraft)) == 0


def test_attachment_storage_failure_retry_and_access_boundaries(env, monkeypatch):
    client, session, app, user, foreign, *_, role = env
    body, _, permission = setup_sync(env)
    content = b"pdf evidence"
    attachment_id = str(uuid.uuid4())
    metadata = {
        "attachment_id": attachment_id,
        "file_name": "evidence.pdf",
        "mime_type": "application/pdf",
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    body["answers"] = {"attachments": [metadata]}
    assert client.post("/api/sync/drafts", json=body).status_code == 200
    path = f"/api/sync/drafts/{body['draft_id']}/attachments/{attachment_id}"
    data = {key: str(value) for key, value in metadata.items() if key != "attachment_id"}
    files = {"file": ("evidence.pdf", content, "application/pdf")}

    def unavailable(*args):
        raise EndpointConnectionError(endpoint_url="http://storage.invalid")

    monkeypatch.setattr("app.modules.sync.routes.put_object", unavailable)
    assert client.put(path, data=data, files=files).status_code == 503
    assert session.scalar(select(func.count()).select_from(DraftAttachment)) == 0
    monkeypatch.setattr("app.modules.sync.routes.put_object", lambda *args: None)
    accepted = client.put(path, data=data, files=files)
    assert accepted.status_code == 200
    assert (
        client.put(path, data={**data, "file_name": "changed.pdf"}, files=files).status_code == 409
    )
    session.delete(session.get(RolePermission, (role.id, permission.id)))
    session.commit()
    assert client.put(path, data=data, files=files).json() == accepted.json()
    assert (
        client.put(
            path.replace(attachment_id, str(uuid.uuid4())), data=data, files=files
        ).status_code
        == 403
    )
    app.dependency_overrides[get_current_user_id] = lambda: foreign.id
    assert client.put(path, data=data, files=files).status_code == 404
