"""Offline attachment metadata backed by object storage."""

import sqlalchemy as sa
from alembic import op

revision = "0005_offline_attachments"
down_revision = "0004_offline_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "draft_attachments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "draft_id", sa.Uuid(), sa.ForeignKey("collection_drafts.id"), nullable=False, index=True
        ),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False, unique=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("size > 0"),
    )


def downgrade() -> None:
    op.drop_table("draft_attachments")
