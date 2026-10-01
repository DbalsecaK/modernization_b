"""Integrations of the tenant (spec 7.1, 7.6; ADR-0018; plan M7).

A tenant connects its external tools once (Figma now; Jira, Azure DevOps and Git in M7b) and its projects use them.
The token lives in the secrets store; the row keeps only its path. New tenant permission `integrations.manage`, held by
the tenant administrator.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-01
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE tenant_integration (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenant (id) ON DELETE CASCADE,
      kind text NOT NULL CHECK (kind IN ('figma', 'jira', 'azure_devops', 'github', 'gitlab')),
      name text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
      -- Where the token lives in the secrets store (ADR-0007); never the token itself.
      vault_path text,
      -- Who the token belongs to, as the tool reports it (a handle, never a credential).
      account text,
      status text NOT NULL DEFAULT 'untested' CHECK (status IN ('untested', 'ok', 'failed')),
      last_tested_at timestamptz,
      last_test_detail text,
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (tenant_id, name)
    );
    CREATE INDEX tenant_integration_kind ON tenant_integration (tenant_id, kind);
    ALTER TABLE tenant_integration ENABLE ROW LEVEL SECURITY;
    ALTER TABLE tenant_integration FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_integration_owner ON tenant_integration TO platform_owner USING (true) WITH CHECK (true);
    CREATE POLICY tenant_integration_tenant ON tenant_integration TO platform_app
      USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant());
    GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_integration TO platform_app;

    INSERT INTO permission (key, description)
      VALUES ('integrations.manage', 'Connect the tenant''s external tools (Figma, Jira, Azure DevOps)');
    INSERT INTO permission_scope (permission_key, scope) VALUES ('integrations.manage', 'tenant');
    INSERT INTO role_permission (tenant_id, role_id, role_scope, permission_key)
      SELECT tenant_id, id, scope, 'integrations.manage' FROM role WHERE key = 'tenantAdmin' AND scope = 'tenant'
      ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
    DELETE FROM role_permission WHERE permission_key = 'integrations.manage';
    DELETE FROM permission_scope WHERE permission_key = 'integrations.manage';
    DELETE FROM permission WHERE key = 'integrations.manage';
    DROP TABLE tenant_integration;
    """)
