"""Explicit reporting obligations and reviewer acknowledgements."""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0008_operational_hierarchy"
down_revision = "0007_report_corrections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reporting_requirements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("form_id", sa.Uuid(), sa.ForeignKey("forms.id"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("territory_id", sa.Uuid(), sa.ForeignKey("territories.id"), nullable=False),
        sa.Column("required_clearance", sa.Integer(), nullable=False),
        sa.Column("cadence", sa.String(16), nullable=False),
        sa.Column("active_from", sa.Date(), nullable=False),
        sa.Column("active_until", sa.Date()),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("deadline_hour", sa.Integer(), nullable=False),
        sa.Column("deadline_days", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("form_id", "organization_id", "territory_id", "cadence", "active_from"),
        sa.CheckConstraint("cadence IN ('DAILY', 'WEEKLY', 'MONTHLY')"),
        sa.CheckConstraint("deadline_hour >= 0 AND deadline_hour <= 23"),
        sa.CheckConstraint("deadline_days >= 0 AND deadline_days <= 31"),
        sa.CheckConstraint("active_until IS NULL OR active_until >= active_from"),
    )
    op.create_table(
        "expected_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "requirement_id", sa.Uuid(), sa.ForeignKey("reporting_requirements.id"), nullable=False
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("expected_by", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("requirement_id", "period_start"),
    )
    op.create_table(
        "expected_report_receipts",
        sa.Column("expected_id", sa.Uuid(), sa.ForeignKey("expected_reports.id"), primary_key=True),
        sa.Column("report_id", sa.Uuid(), sa.ForeignKey("reports.id"), nullable=False, unique=True),
        sa.Column(
            "revision_id",
            sa.Uuid(),
            sa.ForeignKey("report_revisions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "report_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("revision_id", sa.Uuid(), sa.ForeignKey("report_revisions.id"), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("revision_id", "reviewer_id"),
    )
    op.bulk_insert(
        sa.table("permissions", sa.column("id", sa.Uuid()), sa.column("code", sa.String())),
        [{"id": uuid.uuid4(), "code": code} for code in ("reports:review", "reporting:manage")],
    )
    if op.get_bind().dialect.name == "postgresql":
        for table in (
            "reporting_requirements",
            "expected_reports",
            "expected_report_receipts",
            "report_reviews",
        ):
            op.execute(
                f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION reject_official_mutation()"
            )


def downgrade() -> None:
    raise RuntimeError("Reporting obligations and review history must not be discarded.")
