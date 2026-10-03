import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.forms.models import json_type


class CollectionDraft(Base):
    """Mutable working copy; never a confirmed report or an official revision."""

    __tablename__ = "collection_drafts"
    __table_args__ = (CheckConstraint("version > 0"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    form_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("form_versions.id"))
    version: Mapped[int]
    answers: Mapped[dict[str, Any]] = mapped_column(json_type)
    client_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    server_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SyncOperation(Base):
    __tablename__ = "sync_operations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collection_drafts.id"))
    payload_hash: Mapped[str] = mapped_column(String(64))
    receipt: Mapped[dict[str, Any]] = mapped_column(json_type)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SyncAuditEvent(Base):
    __tablename__ = "sync_audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    operation_id: Mapped[uuid.UUID]
    draft_id: Mapped[uuid.UUID]
    code: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DraftAttachment(Base):
    __tablename__ = "draft_attachments"
    __table_args__ = (CheckConstraint("size > 0"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collection_drafts.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(128))
    size: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
