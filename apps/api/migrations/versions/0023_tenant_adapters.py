"""Source adapters a tenant declares (ADR-0039): a specification of patterns the platform runs itself, private to
the tenant (RLS), listed in its catalog as experimental.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-05
"""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE tenant_adapter (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenant (id) ON DELETE CASCADE,
      key text NOT NULL CHECK (key ~ '^[a-z][a-z0-9-]{1,40}$'),
      name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
      level text NOT NULL DEFAULT 'experimental' CHECK (level IN ('experimental', 'assisted', 'certified')),
      spec jsonb NOT NULL,
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (tenant_id, key)
    );
    ALTER TABLE tenant_adapter ENABLE ROW LEVEL SECURITY;
    ALTER TABLE tenant_adapter FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_adapter_owner ON tenant_adapter TO platform_owner USING (true) WITH CHECK (true);
    CREATE POLICY tenant_adapter_tenant ON tenant_adapter TO platform_app
      USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant());
    GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_adapter TO platform_app;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE tenant_adapter;")
