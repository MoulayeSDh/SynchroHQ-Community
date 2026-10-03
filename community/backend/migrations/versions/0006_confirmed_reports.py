"""Immutable confirmed reports and persistent acknowledgements."""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006_confirmed_reports"
down_revision = "0005_offline_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    data = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("author_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("territory_id", sa.Uuid(), sa.ForeignKey("territories.id"), nullable=False),
        sa.Column("required_clearance", sa.Integer(), nullable=False),
        sa.Column("current_revision_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("required_clearance >= 0"),
    )
    op.create_table(
        "report_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("report_id", sa.Uuid(), sa.ForeignKey("reports.id"), nullable=False, index=True),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("form_version_id", sa.Uuid(), sa.ForeignKey("form_versions.id"), nullable=False),
        sa.Column(
            "source_draft_id",
            sa.Uuid(),
            sa.ForeignKey("collection_drafts.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("payload", data, nullable=False),
        sa.Column("canonical_payload", sa.String(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("server_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("report_id", "number"),
        sa.CheckConstraint("number > 0"),
    )
    op.create_foreign_key(
        "fk_report_current_revision",
        "reports",
        "report_revisions",
        ["current_revision_id"],
        ["id"],
        use_alter=True,
    )
    op.create_table(
        "confirmation_proofs",
        sa.Column("revision_id", sa.Uuid(), sa.ForeignKey("report_revisions.id"), primary_key=True),
        sa.Column("author_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("auth_method", sa.String(64), nullable=False),
        sa.Column("context_token", sa.String(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("server_received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "report_attachments",
        sa.Column("revision_id", sa.Uuid(), sa.ForeignKey("report_revisions.id"), primary_key=True),
        sa.Column(
            "attachment_id", sa.Uuid(), sa.ForeignKey("draft_attachments.id"), primary_key=True
        ),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
    )
    op.create_table(
        "report_operations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("revision_id", sa.Uuid(), sa.ForeignKey("report_revisions.id"), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("receipt", data, nullable=False),
    )
    op.create_table(
        "report_audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.bulk_insert(
        sa.table("permissions", sa.column("id", sa.Uuid()), sa.column("code", sa.String())),
        [
            {"id": uuid.uuid4(), "code": "reports:" + action}
            for action in ("create", "confirm", "read")
        ],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
        CREATE FUNCTION reject_official_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'Confirmed report content and audit are immutable';
        END $$;
        """)
        for table in (
            "report_revisions",
            "confirmation_proofs",
            "report_attachments",
            "report_operations",
            "report_audit_events",
        ):
            op.execute(
                f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION reject_official_mutation()"
            )
        op.execute("""
        CREATE FUNCTION protect_report() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Reports cannot be deleted';
          END IF;
          IF OLD.current_revision_id IS NOT NULL OR
             (to_jsonb(NEW) - 'current_revision_id') IS DISTINCT FROM
             (to_jsonb(OLD) - 'current_revision_id') THEN
            RAISE EXCEPTION 'Report is already confirmed';
          END IF;
          IF NOT EXISTS (SELECT 1 FROM report_revisions
                         WHERE id = NEW.current_revision_id AND report_id = OLD.id) THEN
            RAISE EXCEPTION 'Revision belongs to another report';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER immutable_reports BEFORE UPDATE OR DELETE ON reports
          FOR EACH ROW EXECUTE FUNCTION protect_report();
        CREATE FUNCTION protect_confirmed_source() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF EXISTS (SELECT 1 FROM report_revisions WHERE source_draft_id = OLD.id) THEN
            RAISE EXCEPTION 'Confirmed source cannot be modified';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER immutable_confirmed_source BEFORE UPDATE OR DELETE ON collection_drafts
          FOR EACH ROW EXECUTE FUNCTION protect_confirmed_source();
        CREATE FUNCTION protect_confirmed_file() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF EXISTS (SELECT 1 FROM report_attachments WHERE attachment_id = OLD.id) THEN
            RAISE EXCEPTION 'Confirmed attachment cannot be modified';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER immutable_confirmed_file BEFORE UPDATE OR DELETE ON draft_attachments
          FOR EACH ROW EXECUTE FUNCTION protect_confirmed_file();
        """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for trigger, table in (
            ("immutable_reports", "reports"),
            ("immutable_confirmed_source", "collection_drafts"),
            ("immutable_confirmed_file", "draft_attachments"),
        ):
            op.execute(f"DROP TRIGGER {trigger} ON {table}")
        for table in (
            "report_revisions",
            "confirmation_proofs",
            "report_attachments",
            "report_operations",
            "report_audit_events",
        ):
            op.execute(f"DROP TRIGGER immutable_{table} ON {table}")
        for function in (
            "reject_official_mutation",
            "protect_report",
            "protect_confirmed_source",
            "protect_confirmed_file",
        ):
            op.execute(f"DROP FUNCTION {function}()")
    for table in (
        "report_audit_events",
        "report_operations",
        "report_attachments",
        "confirmation_proofs",
    ):
        op.drop_table(table)
    op.drop_constraint("fk_report_current_revision", "reports", type_="foreignkey")
    op.drop_table("report_revisions")
    op.drop_table("reports")
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions "
        "WHERE code IN ('reports:create','reports:confirm','reports:read'))"
    )
    op.execute(
        "DELETE FROM permissions WHERE code IN ('reports:create','reports:confirm','reports:read')"
    )
