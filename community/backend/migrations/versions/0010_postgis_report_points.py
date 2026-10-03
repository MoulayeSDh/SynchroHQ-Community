"""PostGIS point projection for confirmed report activities."""

from alembic import op

revision = "0010_postgis_report_points"
down_revision = "0009_application_shell"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("""
        CREATE TABLE report_geo_points (
            revision_id uuid NOT NULL REFERENCES report_revisions(id),
            activity_index integer NOT NULL CHECK (activity_index >= 0),
            report_id uuid NOT NULL REFERENCES reports(id),
            tenant_id uuid NOT NULL,
            territory_id uuid NOT NULL REFERENCES territories(id),
            form_id uuid NOT NULL REFERENCES forms(id),
            required_clearance integer NOT NULL CHECK (required_clearance >= 0),
            period_start date NOT NULL,
            location geometry(Point,4326) NOT NULL,
            PRIMARY KEY (revision_id, activity_index),
            CONSTRAINT report_geo_coordinates CHECK (
                ST_Y(location) BETWEEN -90 AND 90 AND ST_X(location) BETWEEN -180 AND 180
            )
        )
    """)
    op.execute(
        "CREATE INDEX ix_report_geo_points_location ON report_geo_points USING GIST (location)"
    )
    op.execute(
        "CREATE INDEX ix_report_geo_points_scope ON report_geo_points "
        "(tenant_id, territory_id, period_start)"
    )
    # Existing immutable revisions are projected once; the source payload remains unchanged.
    op.execute("""
        INSERT INTO report_geo_points (
            revision_id, activity_index, report_id, tenant_id, territory_id,
            form_id, required_clearance, period_start, location
        )
        SELECT rr.id, (activity.ordinality - 1)::integer, r.id, r.tenant_id,
               r.territory_id, fv.form_id, r.required_clearance,
               COALESCE(er.period_start, (rr.confirmed_at AT TIME ZONE 'UTC')::date),
               ST_SetSRID(ST_MakePoint(
                   (activity.value #>> '{location,longitude}')::double precision,
                   (activity.value #>> '{location,latitude}')::double precision
               ), 4326)
        FROM report_revisions rr
        JOIN reports r ON r.id = rr.report_id
        JOIN form_versions fv ON fv.id = rr.form_version_id
        LEFT JOIN expected_report_receipts receipt ON receipt.report_id = r.id
        LEFT JOIN expected_reports er ON er.id = receipt.expected_id
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE WHEN jsonb_typeof(rr.payload::jsonb #> '{answers,activities}') = 'array'
                 THEN rr.payload::jsonb #> '{answers,activities}' ELSE '[]'::jsonb END
        ) WITH ORDINALITY AS activity(value, ordinality)
        WHERE jsonb_typeof(activity.value #> '{location,latitude}') = 'number'
          AND jsonb_typeof(activity.value #> '{location,longitude}') = 'number'
          AND (activity.value #>> '{location,latitude}')::double precision BETWEEN -90 AND 90
          AND (activity.value #>> '{location,longitude}')::double precision BETWEEN -180 AND 180
    """)
    op.execute("""
        CREATE TRIGGER immutable_report_geo_points BEFORE UPDATE OR DELETE ON report_geo_points
        FOR EACH ROW EXECUTE FUNCTION reject_official_mutation()
    """)


def downgrade() -> None:
    raise RuntimeError("Confirmed report locations must not be discarded.")
