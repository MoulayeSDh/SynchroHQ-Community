"""Append-only comments, correction requests and revision succession."""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007_report_corrections"
down_revision = "0006_confirmed_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("report_comments", "correction_requests"):
        op.create_table(
            name,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("actor_name", sa.String(255), nullable=False),
            sa.Column(
                "report_id", sa.Uuid(), sa.ForeignKey("reports.id"), nullable=False, index=True
            ),
            sa.Column(
                "revision_id", sa.Uuid(), sa.ForeignKey("report_revisions.id"), nullable=False
            ),
            sa.Column("text", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            *(
                [sa.UniqueConstraint("report_id", "revision_id")]
                if name == "correction_requests"
                else []
            ),
        )
    op.create_table(
        "correction_resolutions",
        sa.Column(
            "request_id", sa.Uuid(), sa.ForeignKey("correction_requests.id"), primary_key=True
        ),
        sa.Column(
            "revision_id",
            sa.Uuid(),
            sa.ForeignKey("report_revisions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "report_workflow_operations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("receipt", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
    )
    op.bulk_insert(
        sa.table("permissions", sa.column("id", sa.Uuid()), sa.column("code", sa.String())),
        [
            {"id": uuid.uuid4(), "code": "reports:" + a}
            for a in ("comment", "request-correction", "correct")
        ],
    )
    if op.get_bind().dialect.name == "postgresql":
        for table in (
            "report_comments",
            "correction_requests",
            "correction_resolutions",
            "report_workflow_operations",
        ):
            op.execute(
                f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION reject_official_mutation()"
            )
        op.execute("""
        CREATE OR REPLACE FUNCTION protect_report() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Reports cannot be deleted'; END IF;
          IF (to_jsonb(NEW) - 'current_revision_id') IS DISTINCT FROM
             (to_jsonb(OLD) - 'current_revision_id') THEN
            RAISE EXCEPTION 'Report identity is immutable';
          END IF;
          IF NOT EXISTS (SELECT 1 FROM report_revisions WHERE id = NEW.current_revision_id AND
            report_id = OLD.id) THEN
            RAISE EXCEPTION 'Revision belongs to another report';
          END IF;
          IF OLD.current_revision_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM report_revisions previous
            JOIN report_revisions next ON next.report_id = previous.report_id AND next.number =
            previous.number + 1
            JOIN correction_requests request ON request.report_id = previous.report_id AND
            request.revision_id = previous.id
            JOIN correction_resolutions resolution ON resolution.request_id = request.id AND
            resolution.revision_id = next.id
            WHERE previous.id = OLD.current_revision_id AND next.id = NEW.current_revision_id
          ) THEN RAISE EXCEPTION 'A correction requires the next immutable revision and its
            resolution'; END IF;
          RETURN NEW;
        END $$;
        """)


def downgrade() -> None:
    # Refuse to discard official workflow history through an accidental downgrade.
    raise RuntimeError("Correction history is permanent; restore a database backup to roll back.")
