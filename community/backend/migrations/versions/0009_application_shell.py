"""Explicit read-only administration permission for the application shell."""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0009_application_shell"
down_revision = "0008_operational_hierarchy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text("INSERT INTO permissions (id, code) VALUES (:id, :code)").bindparams(
            id=uuid.uuid5(uuid.NAMESPACE_URL, "synchrohq:permission:administration:read"),
            code="administration:read",
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE code='administration:read')"
        )
    )
    op.execute(sa.text("DELETE FROM permissions WHERE code='administration:read'"))
