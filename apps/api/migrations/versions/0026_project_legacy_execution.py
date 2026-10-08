"""How a project's legacy runs for the golden master (ADR-0052): automatic (by its inputs), from recorded traces or
on a live system of the customer (an IBM i first), with where that system is. The credentials live in the secrets
store (ADR-0007): only their path here.

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-07
"""

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE project_legacy_execution (
      tenant_id uuid NOT NULL,
      project_id uuid PRIMARY KEY,
      mode text NOT NULL DEFAULT 'auto' CHECK (mode IN ('auto', 'traces', 'live')),
      kind text CHECK (kind IN ('ibmi')),
      config jsonb NOT NULL DEFAULT '{}'::jsonb,
      vault_path text,
      status text NOT NULL DEFAULT 'untested' CHECK (status IN ('untested', 'ok', 'failed')),
      last_checked_at timestamptz,
      last_check_detail text,
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      CHECK (mode <> 'live' OR kind IS NOT NULL),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE
    );
    CREATE TRIGGER project_legacy_execution_updated_at BEFORE UPDATE ON project_legacy_execution
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    ALTER TABLE project_legacy_execution ENABLE ROW LEVEL SECURITY;
    ALTER TABLE project_legacy_execution FORCE ROW LEVEL SECURITY;
    CREATE POLICY project_legacy_execution_owner ON project_legacy_execution TO platform_owner
      USING (true) WITH CHECK (true);
    CREATE POLICY project_legacy_execution_tenant ON project_legacy_execution TO platform_app
      USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant());
    GRANT SELECT, INSERT, UPDATE, DELETE ON project_legacy_execution TO platform_app;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE project_legacy_execution;")
