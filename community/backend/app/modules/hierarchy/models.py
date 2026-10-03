import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ReportingRequirement(Base):
    __tablename__ = "reporting_requirements"
    __table_args__ = (
        UniqueConstraint("form_id", "organization_id", "territory_id", "cadence", "active_from"),
        CheckConstraint("cadence IN ('DAILY', 'WEEKLY', 'MONTHLY')"),
        CheckConstraint("deadline_hour >= 0 AND deadline_hour <= 23"),
        CheckConstraint("deadline_days >= 0 AND deadline_days <= 31"),
        CheckConstraint("active_until IS NULL OR active_until >= active_from"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forms.id"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    territory_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("territories.id"))
    required_clearance: Mapped[int]
    cadence: Mapped[str] = mapped_column(String(16))
    active_from: Mapped[date] = mapped_column(Date)
    active_until: Mapped[date | None] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String(64))
    deadline_hour: Mapped[int]
    deadline_days: Mapped[int]
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExpectedReport(Base):
    __tablename__ = "expected_reports"
    __table_args__ = (UniqueConstraint("requirement_id", "period_start"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    requirement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reporting_requirements.id"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    expected_by: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExpectedReceipt(Base):
    __tablename__ = "expected_report_receipts"
    expected_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("expected_reports.id"), primary_key=True
    )
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reports.id"), unique=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("report_revisions.id"), unique=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReportReview(Base):
    __tablename__ = "report_reviews"
    __table_args__ = (UniqueConstraint("revision_id", "reviewer_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("report_revisions.id"))
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
