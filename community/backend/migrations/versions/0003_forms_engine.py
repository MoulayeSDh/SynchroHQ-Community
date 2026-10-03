"""Versioned forms, publication audit and database immutability guard."""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003_forms_engine"
down_revision: str | None = "40f51019423f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forms",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("territory_id", sa.Uuid(), sa.ForeignKey("territories.id"), nullable=False),
        sa.Column("required_clearance", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("tenant_id", "code"),
        sa.CheckConstraint("required_clearance >= 0"),
    )
    op.create_table(
        "form_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("form_id", sa.Uuid(), sa.ForeignKey("forms.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("data_schema", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
        sa.Column("ui_schema", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
        sa.Column("translations", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("published_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("form_id", "version"),
        sa.CheckConstraint("version > 0"),
        sa.CheckConstraint("status IN ('DRAFT', 'PUBLISHED', 'RETIRED')"),
        sa.CheckConstraint(
            "status = 'DRAFT' OR (published_at IS NOT NULL AND published_by IS NOT NULL)"
        ),
    )
    op.create_table(
        "form_audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("actor_name", sa.String(255), nullable=False),
        sa.Column("form_id", sa.Uuid(), sa.ForeignKey("forms.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    permissions = sa.table(
        "permissions", sa.column("id", sa.Uuid()), sa.column("code", sa.String())
    )
    op.bulk_insert(
        permissions,
        [
            {"id": uuid.uuid4(), "code": f"forms:{action}"}
            for action in ("read", "manage", "publish")
        ],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
        CREATE FUNCTION protect_form_version() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.status <> 'DRAFT' THEN
              RAISE EXCEPTION 'Published form versions cannot be deleted';
            END IF;
            RETURN OLD;
          END IF;
          IF OLD.status <> 'DRAFT' AND
             (to_jsonb(NEW) - 'status' - 'retired_at') IS DISTINCT FROM
             (to_jsonb(OLD) - 'status' - 'retired_at') THEN
            RAISE EXCEPTION 'Published form content is immutable';
          END IF;
          IF NEW.status <> OLD.status AND NOT
             ((OLD.status = 'DRAFT' AND NEW.status = 'PUBLISHED') OR
              (OLD.status = 'PUBLISHED' AND NEW.status = 'RETIRED')) THEN
            RAISE EXCEPTION 'Invalid form version transition';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER form_version_immutable BEFORE UPDATE OR DELETE ON form_versions
        FOR EACH ROW EXECUTE FUNCTION protect_form_version();
        """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER form_version_immutable ON form_versions")
        op.execute("DROP FUNCTION protect_form_version()")
    op.drop_table("form_audit_events")
    op.drop_table("form_versions")
    op.drop_table("forms")
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM permissions WHERE code IN "
        "('forms:read', 'forms:manage', 'forms:publish'))"
    )
    op.execute(
        "DELETE FROM permissions WHERE code IN ('forms:read', 'forms:manage', 'forms:publish')"
    )
