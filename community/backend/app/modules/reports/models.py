import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.forms.models import json_type


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (CheckConstraint("required_clearance >= 0"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    territory_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("territories.id"))
    required_clearance: Mapped[int]
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("report_revisions.id", name="fk_report_current_revision", use_alter=True)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReportRevision(Base):
    __tablename__ = "report_revisions"
    __table_args__ = (UniqueConstraint("report_id", "number"), CheckConstraint("number > 0"))
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reports.id"), index=True)
    number: Mapped[int]
    form_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("form_versions.id"))
    source_draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collection_drafts.id"), unique=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(json_type)
    canonical_payload: Mapped[str]
    payload_hash: Mapped[str] = mapped_column(String(64))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    server_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConfirmationProof(Base):
    __tablename__ = "confirmation_proofs"
    revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("report_revisions.id"), primary_key=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    device_id: Mapped[uuid.UUID]
    payload_hash: Mapped[str] = mapped_column(String(64))
    auth_method: Mapped[str] = mapped_column(String(64))
    context_token: Mapped[str]
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    server_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReportAttachment(Base):
    __tablename__ = "report_attachments"
    revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("report_revisions.id"), primary_key=True
    )
    attachment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("draft_attachments.id"), primary_key=True
    )
    file_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(128))
    size: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(512))


class ReportOperation(Base):
    __tablename__ = "report_operations"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("report_revisions.id"))
    request_hash: Mapped[str] = mapped_column(String(64))
    receipt: Mapped[dict[str, Any]] = mapped_column(json_type)


class ReportAuditEvent(Base):
    __tablename__ = "report_audit_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    report_id: Mapped[uuid.UUID]
    revision_id: Mapped[uuid.UUID]
    operation_id: Mapped[uuid.UUID]
    code: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReportComment(Base):
    __tablename__ = "report_comments"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    actor_name: Mapped[str] = mapped_column(String(255))
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reports.id"), index=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("report_revisions.id"))
    text: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CorrectionRequest(Base):
    __tablename__ = "correction_requests"
    __table_args__ = (UniqueConstraint("report_id", "revision_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    actor_name: Mapped[str] = mapped_column(String(255))
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reports.id"), index=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("report_revisions.id"))
    text: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CorrectionResolution(Base):
    __tablename__ = "correction_resolutions"
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("correction_requests.id"), primary_key=True
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("report_revisions.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkflowOperation(Base):
    __tablename__ = "report_workflow_operations"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    request_hash: Mapped[str] = mapped_column(String(64))
    receipt: Mapped[dict[str, Any]] = mapped_column(json_type)
