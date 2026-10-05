"""Pack profiles of a tenant (ADR-0040): a package root the design must respect and conventions the agents are told;
private to the tenant (RLS), offered as the `pack_profile` preference of its catalog.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-05
"""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE tenant_pack_profile (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenant (id) ON DELETE CASCADE,
      key text NOT NULL CHECK (key ~ '^[a-z][a-z0-9-]{1,40}$'),
      name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
      backend text,
      package_root text,
      conventions text NOT NULL DEFAULT '',
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (tenant_id, key)
    );
    ALTER TABLE tenant_pack_profile ENABLE ROW LEVEL SECURITY;
    ALTER TABLE tenant_pack_profile FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_pack_profile_owner ON tenant_pack_profile TO platform_owner USING (true) WITH CHECK (true);
    CREATE POLICY tenant_pack_profile_tenant ON tenant_pack_profile TO platform_app
      USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant());
    GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_pack_profile TO platform_app;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE tenant_pack_profile;")
