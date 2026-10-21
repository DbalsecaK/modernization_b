"""A person's classification of a legacy statement (ADR-0056): a business statement no rule cites blocks C1, and the
reviewer may decide it is infrastructure (error plumbing, a trace) with a reason. Kept apart from the classification
the phase stores, so a new classification does not erase it and every decision has its author; private to the tenant
(RLS).

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-21
"""

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE statement_override (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenant (id) ON DELETE CASCADE,
      project_id uuid NOT NULL REFERENCES project (id) ON DELETE CASCADE,
      file text NOT NULL CHECK (length(file) BETWEEN 1 AND 500),
      line_start integer NOT NULL CHECK (line_start > 0),
      line_end integer NOT NULL CHECK (line_end >= line_start),
      label text NOT NULL CHECK (label IN ('infrastructure', 'control_flow')),
      reason text NOT NULL CHECK (length(reason) BETWEEN 10 AND 2000),
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (project_id, file, line_start, line_end)
    );
    ALTER TABLE statement_override ENABLE ROW LEVEL SECURITY;
    ALTER TABLE statement_override FORCE ROW LEVEL SECURITY;
    CREATE POLICY statement_override_owner ON statement_override TO platform_owner USING (true) WITH CHECK (true);
    CREATE POLICY statement_override_tenant ON statement_override TO platform_app
      USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant());
    GRANT SELECT, INSERT, UPDATE, DELETE ON statement_override TO platform_app;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE statement_override;")
