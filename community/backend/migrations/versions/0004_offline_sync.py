"""Working drafts and transactional idempotent synchronization."""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004_offline_sync"
down_revision = "0003_forms_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    data = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "collection_drafts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("form_version_id", sa.Uuid(), sa.ForeignKey("form_versions.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("answers", data, nullable=False),
        sa.Column("client_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("server_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0"),
    )
    op.create_table(
        "sync_operations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("draft_id", sa.Uuid(), sa.ForeignKey("collection_drafts.id"), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("receipt", data, nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "sync_audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.bulk_insert(
        sa.table("permissions", sa.column("id", sa.Uuid()), sa.column("code", sa.String())),
        [{"id": uuid.uuid4(), "code": "drafts:sync"}],
    )


def downgrade() -> None:
    op.drop_table("sync_audit_events")
    op.drop_table("sync_operations")
    op.drop_table("collection_drafts")
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM permissions WHERE code = 'drafts:sync')"
    )
    op.execute("DELETE FROM permissions WHERE code = 'drafts:sync'")
