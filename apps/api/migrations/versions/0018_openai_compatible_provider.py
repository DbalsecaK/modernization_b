"""Local models (M15, ADR-0030): the `openai-compatible` provider.

- provider_connection: the provider may be `openai-compatible`, with its server's base URL (the API key, optional, is
  in the secrets store).
- model_version and model_offering: besides the global catalog (tenant_id NULL), a tenant's own models for its
  openai-compatible connections, visible only to that tenant (RLS: global rows or the tenant's). The slug of a global
  version stays unique; a tenant's slug is unique within the tenant.
- price_version and effort_mapping: visible only when their offering is (RLS through the offering).

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-02
"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

CATALOG_TENANT_TABLES = ("model_version", "model_offering")
THROUGH_OFFERING = ("price_version", "effort_mapping")


def upgrade() -> None:
    op.execute("""
    ALTER TABLE provider_connection DROP CONSTRAINT provider_connection_provider_check;
    ALTER TABLE provider_connection
      ADD CONSTRAINT provider_connection_provider_check CHECK (provider IN ('openrouter', 'openai-compatible')),
      ADD COLUMN base_url text CHECK (length(base_url) BETWEEN 8 AND 500),
      ADD CONSTRAINT provider_connection_base_url_required
        CHECK ((provider = 'openai-compatible') = (base_url IS NOT NULL));

    ALTER TABLE model_version ADD COLUMN tenant_id uuid REFERENCES tenant (id);
    ALTER TABLE model_version DROP CONSTRAINT model_version_provider_slug_key;
    CREATE UNIQUE INDEX model_version_global_slug_key ON model_version (provider_slug) WHERE tenant_id IS NULL;
    CREATE UNIQUE INDEX model_version_tenant_slug_key ON model_version (tenant_id, provider_slug)
      WHERE tenant_id IS NOT NULL;

    ALTER TABLE model_offering DROP CONSTRAINT model_offering_provider_check;
    ALTER TABLE model_offering
      ADD CONSTRAINT model_offering_provider_check CHECK (provider IN ('openrouter', 'openai-compatible')),
      ADD COLUMN tenant_id uuid REFERENCES tenant (id),
      -- NULL once the connection is deleted: offerings with usage stay for the ledger, unavailable.
      ADD COLUMN connection_id uuid,
      ADD FOREIGN KEY (connection_id, tenant_id) REFERENCES provider_connection (id, tenant_id),
      ADD CONSTRAINT model_offering_owner_check CHECK (
        (provider = 'openrouter' AND tenant_id IS NULL AND connection_id IS NULL)
        OR (provider = 'openai-compatible' AND tenant_id IS NOT NULL)
      );
    CREATE INDEX ix_model_offering_connection ON model_offering (connection_id) WHERE connection_id IS NOT NULL;
    """)
    # The tenant's own rows for everything; the global catalog for reading, adding and refreshing (as before), never
    # for deleting.
    for table, own, shared in (
        *((t, "tenant_id = app_current_tenant()", "tenant_id IS NULL") for t in CATALOG_TENANT_TABLES),
        *(
            (
                t,
                f"EXISTS (SELECT 1 FROM model_offering o WHERE o.id = {t}.offering_id AND o.tenant_id IS NOT NULL)",  # noqa: S608
                f"EXISTS (SELECT 1 FROM model_offering o WHERE o.id = {t}.offering_id AND o.tenant_id IS NULL)",  # noqa: S608
            )
            for t in THROUGH_OFFERING
        ),
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_owner ON {table} TO platform_owner USING (true) WITH CHECK (true)")
        op.execute(f"CREATE POLICY {table}_tenant ON {table} TO platform_app USING ({own}) WITH CHECK ({own})")
        op.execute(f"CREATE POLICY {table}_global_read ON {table} FOR SELECT TO platform_app USING ({shared})")
        op.execute(f"CREATE POLICY {table}_global_add ON {table} FOR INSERT TO platform_app WITH CHECK ({shared})")
        op.execute(
            f"CREATE POLICY {table}_global_update ON {table} FOR UPDATE TO platform_app USING ({shared}) "
            f"WITH CHECK ({shared})"
        )
    op.execute("GRANT DELETE ON model_version, model_offering, price_version, effort_mapping TO platform_app")


def downgrade() -> None:
    op.execute("REVOKE DELETE ON model_version, model_offering, price_version, effort_mapping FROM platform_app")
    for table in (*CATALOG_TENANT_TABLES, *THROUGH_OFFERING):
        for policy in ("global_update", "global_add", "global_read", "tenant", "owner"):
            op.execute(f"DROP POLICY {table}_{policy} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("""
    -- The usage ledger is append-only and may reference local models: refuse instead of losing data.
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM provider_connection WHERE provider = 'openai-compatible')
         OR EXISTS (SELECT 1 FROM model_offering WHERE tenant_id IS NOT NULL)
         OR EXISTS (SELECT 1 FROM model_version WHERE tenant_id IS NOT NULL) THEN
        RAISE EXCEPTION 'openai-compatible connections or tenant models exist: remove them before downgrading';
      END IF;
    END $$;

    DROP INDEX ix_model_offering_connection;
    ALTER TABLE model_offering DROP CONSTRAINT model_offering_owner_check,
      DROP COLUMN connection_id, DROP COLUMN tenant_id, DROP CONSTRAINT model_offering_provider_check;
    ALTER TABLE model_offering ADD CONSTRAINT model_offering_provider_check CHECK (provider IN ('openrouter'));

    DROP INDEX model_version_tenant_slug_key;
    DROP INDEX model_version_global_slug_key;
    ALTER TABLE model_version DROP COLUMN tenant_id;
    ALTER TABLE model_version ADD CONSTRAINT model_version_provider_slug_key UNIQUE (provider_slug);

    ALTER TABLE provider_connection DROP CONSTRAINT provider_connection_base_url_required, DROP COLUMN base_url,
      DROP CONSTRAINT provider_connection_provider_check;
    ALTER TABLE provider_connection
      ADD CONSTRAINT provider_connection_provider_check CHECK (provider IN ('openrouter'));
    """)
