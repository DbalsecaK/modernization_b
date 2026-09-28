"""AI configuration and usage (spec 12, 13; plan M1 section 3).

Global catalog (public provider data, like the permission catalog, ADR-0006): model_family, model_version,
model_offering, price_version, effort_mapping. Tenant data with forced RLS: provider_connection, model_profile,
model_assignment, model_policy, usage_ledger (append-only), budget, budget_alert.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-28
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "provider_connection",
    "model_profile",
    "model_assignment",
    "model_policy",
    "usage_ledger",
    "budget",
    "budget_alert",
)
EFFORT = "('low', 'medium', 'high', 'max')"


def upgrade() -> None:
    op.execute(f"""
    -- Catalog: family -> exact version -> offering (version x provider x upstream provider), spec 12.2.
    CREATE TABLE model_family (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      key text NOT NULL UNIQUE,
      name text NOT NULL
    );
    CREATE TABLE model_version (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      family_id uuid NOT NULL REFERENCES model_family (id),
      -- The provider's id and its exact, dated version (never an alias such as "latest", rule 10).
      provider_slug text NOT NULL UNIQUE,
      canonical_slug text NOT NULL UNIQUE,
      name text NOT NULL,
      context_window integer,
      capabilities text[] NOT NULL DEFAULT '{{}}',
      status text NOT NULL DEFAULT 'available' CHECK (status IN ('available', 'deprecated')),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE model_offering (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      version_id uuid NOT NULL REFERENCES model_version (id),
      provider text NOT NULL CHECK (provider IN ('openrouter')),
      -- For an aggregator, the provider the request is pinned to (OpenRouter provider slug).
      upstream_provider text NOT NULL,
      context_window integer,
      max_output_tokens integer,
      capabilities text[] NOT NULL DEFAULT '{{}}',
      zdr boolean NOT NULL DEFAULT false,
      status text NOT NULL DEFAULT 'available' CHECK (status IN ('available', 'unavailable')),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (version_id, provider, upstream_provider)
    );
    -- Prices per offering and token type, in USD per million tokens, with validity (spec 13.3).
    CREATE TABLE price_version (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      offering_id uuid NOT NULL REFERENCES model_offering (id),
      input_per_mtok numeric(18, 6) NOT NULL CHECK (input_per_mtok >= 0),
      output_per_mtok numeric(18, 6) NOT NULL CHECK (output_per_mtok >= 0),
      cache_read_per_mtok numeric(18, 6) CHECK (cache_read_per_mtok >= 0),
      cache_write_per_mtok numeric(18, 6) CHECK (cache_write_per_mtok >= 0),
      request_usd numeric(18, 8) CHECK (request_usd >= 0),
      valid_from timestamptz NOT NULL DEFAULT now(),
      valid_to timestamptz,
      source text NOT NULL CHECK (source IN ('provider_sync', 'manual')),
      created_by uuid REFERENCES app_user (id),
      CHECK (valid_to IS NULL OR valid_to > valid_from)
    );
    CREATE UNIQUE INDEX price_version_current_key ON price_version (offering_id) WHERE valid_to IS NULL;
    -- Normalized effort -> the real parameter of the offering (spec 12.3), editable by the administrator.
    CREATE TABLE effort_mapping (
      offering_id uuid NOT NULL REFERENCES model_offering (id),
      effort text NOT NULL CHECK (effort IN {EFFORT}),
      parameters jsonb NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(parameters) = 'object'),
      updated_by uuid REFERENCES app_user (id),
      updated_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (offering_id, effort)
    );

    -- Tenant data.
    CREATE TABLE provider_connection (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenant (id),
      provider text NOT NULL CHECK (provider IN ('openrouter')),
      name text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
      -- Where the credential lives in the secrets store (ADR-0007); never the credential itself.
      vault_path text,
      status text NOT NULL DEFAULT 'untested' CHECK (status IN ('untested', 'ok', 'failed')),
      last_tested_at timestamptz,
      last_test_detail text,
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (tenant_id, name),
      UNIQUE (id, tenant_id)
    );
    CREATE TABLE model_profile (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenant (id),
      name text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
      connection_id uuid NOT NULL,
      offering_id uuid NOT NULL REFERENCES model_offering (id),
      effort text NOT NULL DEFAULT 'medium' CHECK (effort IN {EFFORT}),
      max_output_tokens integer NOT NULL DEFAULT 4096 CHECK (max_output_tokens BETWEEN 1 AND 1000000),
      temperature numeric(3, 2) CHECK (temperature BETWEEN 0 AND 2),
      timeout_seconds integer NOT NULL DEFAULT 120 CHECK (timeout_seconds BETWEEN 1 AND 3600),
      max_retries integer NOT NULL DEFAULT 2 CHECK (max_retries BETWEEN 0 AND 10),
      fallback_profile_id uuid,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (tenant_id, name),
      UNIQUE (id, tenant_id),
      CHECK (fallback_profile_id IS NULL OR fallback_profile_id <> id),
      FOREIGN KEY (connection_id, tenant_id) REFERENCES provider_connection (id, tenant_id),
      -- Deleting the fallback clears only fallback_profile_id (tenant_id stays).
      FOREIGN KEY (fallback_profile_id, tenant_id) REFERENCES model_profile (id, tenant_id)
        ON DELETE SET NULL (fallback_profile_id)
    );
    -- Cascade Tenant -> Project -> Phase -> Agent role (spec 12.4, 12.5): the most specific row wins.
    CREATE TABLE model_assignment (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      project_id uuid,
      phase text,
      agent_role text,
      profile_id uuid NOT NULL,
      updated_by uuid REFERENCES app_user (id),
      updated_at timestamptz NOT NULL DEFAULT now(),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE,
      FOREIGN KEY (profile_id, tenant_id) REFERENCES model_profile (id, tenant_id) ON DELETE CASCADE,
      UNIQUE NULLS NOT DISTINCT (tenant_id, project_id, phase, agent_role)
    );
    CREATE TABLE model_policy (
      tenant_id uuid PRIMARY KEY REFERENCES tenant (id),
      openrouter_allowed boolean NOT NULL DEFAULT true,
      -- NULL means any upstream provider (unless denied).
      allowed_upstream_providers text[],
      denied_upstream_providers text[] NOT NULL DEFAULT '{{}}',
      require_zdr boolean NOT NULL DEFAULT false,
      deny_data_collection boolean NOT NULL DEFAULT true,
      updated_by uuid REFERENCES app_user (id),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    -- Usage ledger: the source of truth for costs (spec 13.2). Append-only.
    CREATE TABLE usage_ledger (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      tenant_id uuid NOT NULL REFERENCES tenant (id),
      occurred_at timestamptz NOT NULL DEFAULT now(),
      project_id uuid,
      run_id text,
      phase text,
      agent_role text,
      iteration integer,
      profile_id uuid,
      connection_id uuid,
      offering_id uuid REFERENCES model_offering (id),
      price_version_id uuid REFERENCES price_version (id),
      model text,
      upstream_provider text,
      provider_request_id text,
      input_tokens integer NOT NULL DEFAULT 0,
      output_tokens integer NOT NULL DEFAULT 0,
      reasoning_tokens integer NOT NULL DEFAULT 0,
      cache_read_tokens integer NOT NULL DEFAULT 0,
      cache_write_tokens integer NOT NULL DEFAULT 0,
      latency_ms integer NOT NULL DEFAULT 0,
      retries integer NOT NULL DEFAULT 0,
      was_fallback boolean NOT NULL DEFAULT false,
      outcome text NOT NULL CHECK (outcome IN ('success', 'error', 'blocked')),
      error_code text,
      cost_usd numeric(18, 8) NOT NULL DEFAULT 0,
      provider_cost_usd numeric(18, 8)
    );
    CREATE INDEX usage_ledger_tenant_time_idx ON usage_ledger (tenant_id, occurred_at);
    CREATE INDEX usage_ledger_project_time_idx ON usage_ledger (project_id, occurred_at);
    CREATE TRIGGER usage_ledger_no_update_delete BEFORE UPDATE OR DELETE ON usage_ledger
      FOR EACH ROW EXECUTE FUNCTION audit_append_only();
    CREATE TRIGGER usage_ledger_no_truncate BEFORE TRUNCATE ON usage_ledger
      FOR EACH STATEMENT EXECUTE FUNCTION audit_append_only();

    CREATE TABLE budget (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenant (id),
      project_id uuid,
      period text NOT NULL CHECK (period IN ('monthly', 'total')),
      amount_usd numeric(14, 2) NOT NULL CHECK (amount_usd > 0),
      alert_pct integer NOT NULL DEFAULT 80 CHECK (alert_pct BETWEEN 1 AND 99),
      hard_stop boolean NOT NULL DEFAULT true,
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (id, tenant_id),
      UNIQUE NULLS NOT DISTINCT (tenant_id, project_id, period),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE
    );
    -- One alert per budget, level (the alert percentage or 100) and period.
    CREATE TABLE budget_alert (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      budget_id uuid NOT NULL,
      level integer NOT NULL CHECK (level BETWEEN 1 AND 100),
      period_key text NOT NULL,
      spent_usd numeric(18, 8) NOT NULL,
      triggered_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (budget_id, level, period_key),
      FOREIGN KEY (budget_id, tenant_id) REFERENCES budget (id, tenant_id) ON DELETE CASCADE
    );
    """)

    for table in ("model_version", "provider_connection", "model_profile", "budget"):
        op.execute(
            f"CREATE TRIGGER {table}_updated_at BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_owner ON {table} TO platform_owner USING (true) WITH CHECK (true)")
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} TO platform_app "
            "USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())"
        )

    op.execute("""
    GRANT SELECT, INSERT, UPDATE ON model_family, model_version, model_offering, effort_mapping TO platform_app;
    GRANT SELECT, INSERT ON price_version TO platform_app;
    GRANT UPDATE (valid_to) ON price_version TO platform_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON provider_connection, model_profile, model_assignment, budget
      TO platform_app;
    GRANT SELECT, INSERT, UPDATE ON model_policy TO platform_app;
    GRANT SELECT, INSERT ON usage_ledger, budget_alert TO platform_app;
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE budget_alert, budget, usage_ledger, model_policy, model_assignment, model_profile, provider_connection,
      effort_mapping, price_version, model_offering, model_version, model_family;
    """)
