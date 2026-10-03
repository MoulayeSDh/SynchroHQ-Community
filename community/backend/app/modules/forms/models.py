import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

json_type = JSON().with_variant(JSONB(), "postgresql")


class Form(Base):
    __tablename__ = "forms"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        CheckConstraint("required_clearance >= 0"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    territory_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("territories.id"))
    required_clearance: Mapped[int] = mapped_column(default=0)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(default="")
    active: Mapped[bool] = mapped_column(default=True)
    archived: Mapped[bool] = mapped_column(default=False)


class FormVersion(Base):
    __tablename__ = "form_versions"
    __table_args__ = (
        UniqueConstraint("form_id", "version"),
        CheckConstraint("version > 0"),
        CheckConstraint("status IN ('DRAFT', 'PUBLISHED', 'RETIRED')"),
        CheckConstraint(
            "status = 'DRAFT' OR (published_at IS NOT NULL AND published_by IS NOT NULL)"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forms.id"))
    version: Mapped[int]
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    schema_version: Mapped[str] = mapped_column(String(32), default="synchrohq.form/v1")
    data_schema: Mapped[dict[str, Any]] = mapped_column(json_type)
    ui_schema: Mapped[dict[str, Any]] = mapped_column(json_type)
    translations: Mapped[dict[str, Any]] = mapped_column(json_type)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FormAuditEvent(Base):
    __tablename__ = "form_audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    actor_name: Mapped[str] = mapped_column(String(255))
    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forms.id"))
    version: Mapped[int]
    action: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
