import hashlib
import tempfile
import uuid
from datetime import UTC, datetime
from typing import Any, NoReturn

import jwt
import rfc8785
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_session
from app.modules.authorization.service import is_allowed
from app.modules.forms.models import FormVersion
from app.modules.forms.routes import allowed, current_user, get_form
from app.modules.forms.validation import validate_answers
from app.modules.reports.models import (
    CorrectionRequest,
    CorrectionResolution,
    Report,
    ReportRevision,
)
from app.modules.sync.models import CollectionDraft, DraftAttachment, SyncAuditEvent, SyncOperation
from app.modules.sync.storage import put_object
from app.modules.users.models import User

router = APIRouter(prefix="/api/sync", tags=["sync"])


class DraftOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: uuid.UUID
    draft_id: uuid.UUID
    device_id: uuid.UUID
    form_version_id: uuid.UUID
    base_version: int = Field(ge=0)
    client_updated_at: AwareDatetime
    answers: dict[str, Any]
    sync_grant: str


def fail(status: int, code: str) -> NoReturn:
    raise HTTPException(status, detail={"code": code})


def authorize(session: Session, user: User, version_id: uuid.UUID, sync_grant: str) -> FormVersion:
    version = session.get(FormVersion, version_id)
    if version is None:
        fail(404, "FORM_UNAVAILABLE")
    assert version is not None
    # Forms read is necessary but never grants the ability to synchronize answers.
    try:
        form = get_form(session, user, version.form_id, "forms:read")
    except HTTPException as exc:
        raise HTTPException(exc.status_code, detail={"code": "FORM_UNAVAILABLE"}) from exc
    if not allowed(session, user, form, "drafts:sync"):
        fail(403, "SYNC_PERMISSION_REVOKED")
    settings = get_settings()
    try:
        grant = jwt.decode(
            sync_grant,
            settings.auth_jwt_secret,
            algorithms=["HS256"],
            audience=settings.offline_grant_audience,
            issuer=settings.auth_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
        valid_grant = (
            grant.get("purpose") in {"offline-draft", "offline-correction-draft"}
            and grant.get("sub") == str(user.id)
            and grant.get("tenant_id") == str(user.tenant_id)
            and grant.get("form_version_id") == str(version.id)
        )
        issued_at = datetime.fromtimestamp(int(grant["iat"]), UTC)
    except (jwt.PyJWTError, KeyError, TypeError, ValueError, OverflowError) as exc:
        raise HTTPException(403, detail={"code": "OFFLINE_GRANT_INVALID"}) from exc
    if not valid_grant:
        fail(403, "OFFLINE_GRANT_INVALID")
    correction = grant.get("purpose") == "offline-correction-draft"
    if correction:
        try:
            link = grant["correction"]
            request = session.get(CorrectionRequest, uuid.UUID(link["correction_request_id"]))
            report = session.get(Report, uuid.UUID(link["report_id"]))
            base = session.get(ReportRevision, uuid.UUID(link["base_revision_id"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(403, detail={"code": "OFFLINE_GRANT_INVALID"}) from exc
        if (
            request is None
            or report is None
            or base is None
            or report.tenant_id != user.tenant_id
            or report.author_id != user.id
            or request.report_id != report.id
            or request.revision_id != base.id
            or report.current_revision_id != base.id
            or base.form_version_id != version.id
            or session.get(CorrectionResolution, request.id) is not None
            or not all(
                is_allowed(
                    session,
                    user_id=user.id,
                    action=a,
                    territory_id=report.territory_id,
                    required_clearance=report.required_clearance,
                )
                for a in ("reports:read", "reports:correct", "reports:confirm")
            )
        ):
            fail(403, "CORRECTION_PERMISSION_DENIED")
    if not form.active or form.archived:
        fail(409, "FORM_VERSION_UNAVAILABLE")
    if version.status == "RETIRED":
        retired_at = version.retired_at
        if retired_at is not None and retired_at.tzinfo is None:
            retired_at = retired_at.replace(tzinfo=UTC)
        if not correction and (retired_at is None or issued_at > retired_at):
            fail(409, "FORM_VERSION_UNAVAILABLE")
    elif version.status != "PUBLISHED":
        fail(409, "FORM_VERSION_UNAVAILABLE")
    return version


def audit(session: Session, user: User, body: DraftOperation, code: str) -> None:
    session.add(
        SyncAuditEvent(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            operation_id=body.operation_id,
            draft_id=body.draft_id,
            code=code,
            occurred_at=datetime.now(UTC),
        )
    )


@router.post("/drafts")
def synchronize(
    body: DraftOperation,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        digest = hashlib.sha256(rfc8785.dumps(body.model_dump(mode="json"))).hexdigest()
    except (ValueError, rfc8785.CanonicalizationError) as exc:
        raise HTTPException(422, detail={"code": "NON_CANONICAL_PAYLOAD"}) from exc
    # The lock makes the idempotency lookup and the first write one serialized decision.
    session.execute(select(User.id).where(User.id == user.id).with_for_update())
    previous = session.get(SyncOperation, body.operation_id)
    if previous is not None:
        if previous.owner_id != user.id or previous.tenant_id != user.tenant_id:
            fail(404, "OPERATION_UNAVAILABLE")
        if previous.payload_hash != digest:
            audit(session, user, body, "OPERATION_ID_REUSED")
            session.commit()
            fail(409, "OPERATION_ID_REUSED")
        return previous.receipt
    if session.scalar(
        select(ReportRevision.id).where(ReportRevision.source_draft_id == body.draft_id)
    ):
        fail(409, "DRAFT_CONFIRMED_IMMUTABLE")
    version = authorize(session, user, body.form_version_id, body.sync_grant)
    validation = validate_answers(version.data_schema, body.answers)
    draft = session.get(CollectionDraft, body.draft_id)
    if draft is not None:
        if draft.owner_id != user.id or draft.tenant_id != user.tenant_id:
            fail(404, "DRAFT_UNAVAILABLE")
        if draft.form_version_id != body.form_version_id:
            fail(409, "FORM_VERSION_MISMATCH")
    if body.base_version != (draft.version if draft else 0):
        audit(session, user, body, "VERSION_CONFLICT")
        session.commit()
        fail(409, "VERSION_CONFLICT")
    now = datetime.now(UTC)
    if draft is None:
        draft = CollectionDraft(
            id=body.draft_id,
            tenant_id=user.tenant_id,
            owner_id=user.id,
            form_version_id=version.id,
            version=1,
            answers=body.answers,
            client_updated_at=body.client_updated_at,
            server_updated_at=now,
        )
        session.add(draft)
    else:
        draft.version += 1
        draft.answers = body.answers
        draft.client_updated_at = body.client_updated_at
        draft.server_updated_at = now
    session.flush()
    receipt = {
        "operation_id": str(body.operation_id),
        "draft_id": str(draft.id),
        "server_version": draft.version,
        "server_received_at": now.isoformat(),
        "payload_hash": digest,
        "validation": validation.model_dump(),
    }
    session.add(
        SyncOperation(
            id=body.operation_id,
            tenant_id=user.tenant_id,
            owner_id=user.id,
            draft_id=draft.id,
            payload_hash=digest,
            receipt=receipt,
            received_at=now,
        )
    )
    audit(session, user, body, "DRAFT_SYNC_ACCEPTED")
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, detail={"code": "IDENTIFIER_CONFLICT"}) from exc
    return receipt


@router.get("/drafts/{draft_id}")
def read_draft(
    draft_id: uuid.UUID, user: User = Depends(current_user), session: Session = Depends(get_session)
) -> dict[str, Any]:
    draft = session.get(CollectionDraft, draft_id)
    if draft is None or draft.owner_id != user.id or draft.tenant_id != user.tenant_id:
        fail(404, "DRAFT_UNAVAILABLE")
    assert draft is not None
    version = session.get(FormVersion, draft.form_version_id)
    if version is None:
        fail(404, "FORM_UNAVAILABLE")
    assert version is not None
    form = get_form(session, user, version.form_id, "forms:read")
    if not allowed(session, user, form, "drafts:sync"):
        fail(403, "SYNC_PERMISSION_REVOKED")
    return {
        "id": str(draft.id),
        "form_version_id": str(draft.form_version_id),
        "version": draft.version,
        "answers": draft.answers,
        "server_updated_at": draft.server_updated_at.isoformat(),
    }


def attachment_receipt(item: DraftAttachment) -> dict[str, Any]:
    return {
        "attachment_id": str(item.id),
        "draft_id": str(item.draft_id),
        "sha256": item.sha256,
        "size": item.size,
        "server_received_at": item.received_at.replace(tzinfo=UTC).isoformat(),
    }


@router.put("/drafts/{draft_id}/attachments/{attachment_id}")
def upload_attachment(
    draft_id: uuid.UUID,
    attachment_id: uuid.UUID,
    file_name: str = Form(min_length=1, max_length=255),
    mime_type: str = Form(min_length=1, max_length=128),
    size: int = Form(gt=0),
    sha256: str = Form(pattern=r"^[a-f0-9]{64}$"),
    file: UploadFile = File(),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    settings = get_settings()
    if size > settings.attachment_max_bytes:
        fail(413, "ATTACHMENT_TOO_LARGE")
    session.execute(select(User.id).where(User.id == user.id).with_for_update())
    existing = session.get(DraftAttachment, attachment_id)
    if existing is not None:
        if existing.owner_id != user.id or existing.tenant_id != user.tenant_id:
            fail(404, "ATTACHMENT_UNAVAILABLE")
        if (
            existing.draft_id != draft_id
            or existing.file_name != file_name
            or existing.mime_type != mime_type
            or existing.size != size
            or existing.sha256 != sha256
        ):
            fail(409, "ATTACHMENT_ID_REUSED")
        return attachment_receipt(existing)
    draft = session.get(CollectionDraft, draft_id)
    if draft is None or draft.owner_id != user.id or draft.tenant_id != user.tenant_id:
        fail(404, "DRAFT_UNAVAILABLE")
    version = session.get(FormVersion, draft.form_version_id)
    if version is None:
        fail(404, "FORM_UNAVAILABLE")
    form = get_form(session, user, version.form_id, "forms:read")
    if not allowed(session, user, form, "drafts:sync"):
        fail(403, "SYNC_PERMISSION_REVOKED")
    attachments = draft.answers.get("attachments", [])
    if not isinstance(attachments, list):
        fail(422, "ATTACHMENT_METADATA_MISMATCH")
    if mime_type not in {"image/jpeg", "image/png", "application/pdf"}:
        fail(422, "ATTACHMENT_MIME_UNSUPPORTED")
    metadata = next(
        (
            item
            for item in attachments
            if isinstance(item, dict) and item.get("attachment_id") == str(attachment_id)
        ),
        None,
    )
    expected = {
        "attachment_id": str(attachment_id),
        "file_name": file_name,
        "mime_type": mime_type,
        "size": size,
        "sha256": sha256,
    }
    if metadata != expected or file.content_type != mime_type:
        fail(422, "ATTACHMENT_METADATA_MISMATCH")
    digest = hashlib.sha256()
    actual_size = 0
    with tempfile.SpooledTemporaryFile(max_size=settings.attachment_max_bytes) as temporary:
        while chunk := file.file.read(1024 * 1024):
            actual_size += len(chunk)
            if actual_size > settings.attachment_max_bytes:
                fail(413, "ATTACHMENT_TOO_LARGE")
            digest.update(chunk)
            temporary.write(chunk)
        if actual_size != size or digest.hexdigest() != sha256:
            fail(422, "ATTACHMENT_CHECKSUM_MISMATCH")
        storage_key = f"{user.tenant_id}/drafts/{draft_id}/{attachment_id}"
        try:
            put_object(temporary, storage_key, mime_type)
        except (BotoCoreError, ClientError) as exc:
            raise HTTPException(503, detail={"code": "OBJECT_STORAGE_UNAVAILABLE"}) from exc
    now = datetime.now(UTC)
    item = DraftAttachment(
        id=attachment_id,
        tenant_id=user.tenant_id,
        owner_id=user.id,
        draft_id=draft_id,
        file_name=file_name,
        mime_type=mime_type,
        size=size,
        sha256=sha256,
        storage_key=storage_key,
        received_at=now,
    )
    session.add(item)
    session.add(
        SyncAuditEvent(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            operation_id=attachment_id,
            draft_id=draft_id,
            code="ATTACHMENT_SYNC_ACCEPTED",
            occurred_at=now,
        )
    )
    session.commit()
    return attachment_receipt(item)


@router.post("/grants/{version_id}")
def create_grant(
    version_id: uuid.UUID,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    version = session.get(FormVersion, version_id)
    if version is None:
        fail(404, "FORM_UNAVAILABLE")
    assert version is not None
    form = get_form(session, user, version.form_id, "forms:read")
    if not allowed(session, user, form, "drafts:sync"):
        fail(403, "SYNC_PERMISSION_REVOKED")
    if not form.active or form.archived or version.status != "PUBLISHED":
        fail(409, "FORM_VERSION_UNAVAILABLE")
    settings = get_settings()
    now = datetime.now(UTC)
    expires = now.timestamp() + settings.offline_edit_seconds
    token = jwt.encode(
        {
            "sub": str(user.id),
            "tenant_id": str(user.tenant_id),
            "form_version_id": str(version.id),
            "purpose": "offline-draft",
            "iat": int(now.timestamp()),
            "exp": int(expires),
            "iss": settings.auth_issuer,
            "aud": settings.offline_grant_audience,
        },
        settings.auth_jwt_secret,
        algorithm="HS256",
    )
    return {
        "sync_grant": token,
        "expires_at": datetime.fromtimestamp(expires, UTC).isoformat(),
    }
