"""Enterprise identity of each tenant (spec 15.1, ADR-0022; plan M0b).

- `tenant_identity`: the tenant's sign-in methods (own accounts, SSO; at least one), whether own accounts need a second
  factor, the e-mail domains of the tenant and the id of its Keycloak Organization.
- `tenant_identity_provider`: each identity provider of the tenant (OIDC or SAML), as a Keycloak identity provider
  linked to the tenant's Organization. Its client secret goes to Keycloak only and is never stored here.
- `role_assignment.source`: roles that come from the groups of an identity provider (`idp`) are recalculated at each
  sign-in; the ones a person assigned (`manual`) are never touched.
- `identity_route(domain)`: home-realm discovery before sign-in, when there is no user nor tenant yet. It returns only
  what the login page needs: the provider of the domain, whether the domain is SSO-only and whether the tenant asks
  own accounts for a second factor.
- New tenant permission `identity.manage`, held by the tenant administrator.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-01
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

DOMAIN = r"'^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$'"


def upgrade() -> None:
    op.execute(f"""
    CREATE FUNCTION valid_domains(p_domains text[]) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
      SELECT coalesce(bool_and(d ~ {DOMAIN} AND length(d) <= 253), true) FROM unnest(p_domains) AS d
    $$;

    CREATE TABLE tenant_identity (
      tenant_id uuid PRIMARY KEY REFERENCES tenant (id) ON DELETE CASCADE,
      local_accounts boolean NOT NULL DEFAULT true,
      sso boolean NOT NULL DEFAULT false,
      mfa_required boolean NOT NULL DEFAULT false,
      domains text[] NOT NULL DEFAULT '{{}}' CHECK (valid_domains(domains) AND cardinality(domains) <= 50),
      -- The Keycloak Organization of the tenant (its alias is the tenant's slug); set by the reconciliation.
      organization_id text,
      updated_by uuid REFERENCES app_user (id),
      updated_at timestamptz NOT NULL DEFAULT now(),
      CHECK (local_accounts OR sso)
    );

    CREATE TABLE tenant_identity_provider (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenant (id) ON DELETE CASCADE,
      -- The Keycloak alias, unique in the realm: the tenant's slug and a short name.
      alias text NOT NULL UNIQUE CHECK (alias ~ '^[a-z0-9][a-z0-9-]{{1,62}}$'),
      display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 100),
      protocol text NOT NULL CHECK (protocol IN ('oidc', 'saml')),
      -- Where the provider is (issuer and endpoints, or SAML metadata); never a credential.
      settings jsonb NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(settings) = 'object'),
      domains text[] NOT NULL DEFAULT '{{}}' CHECK (valid_domains(domains) AND cardinality(domains) <= 50),
      sso_only boolean NOT NULL DEFAULT false,
      jit boolean NOT NULL DEFAULT true,
      -- Group of the provider -> key of a tenant role; the role given to a JIT user without a mapped group.
      group_roles jsonb NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(group_roles) = 'object'),
      default_role text,
      status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'failed')),
      last_error text,
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (tenant_id, display_name)
    );
    CREATE INDEX tenant_identity_provider_domains ON tenant_identity_provider USING gin (domains);
    CREATE TRIGGER tenant_identity_provider_updated BEFORE UPDATE ON tenant_identity_provider
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    -- A domain belongs to one provider in the whole platform: home-realm discovery must have one answer.
    CREATE FUNCTION tenant_identity_provider_unique_domains() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF EXISTS (SELECT 1 FROM tenant_identity_provider p WHERE p.id <> NEW.id AND p.domains && NEW.domains) THEN
        RAISE EXCEPTION 'domain_taken' USING ERRCODE = 'unique_violation';
      END IF;
      RETURN NEW;
    END $$;
    ALTER FUNCTION tenant_identity_provider_unique_domains() SECURITY DEFINER SET search_path = public, pg_temp;
    CREATE TRIGGER tenant_identity_provider_domains_unique BEFORE INSERT OR UPDATE OF domains
      ON tenant_identity_provider FOR EACH ROW EXECUTE FUNCTION tenant_identity_provider_unique_domains();

    ALTER TABLE role_assignment ADD COLUMN source text NOT NULL DEFAULT 'manual'
      CHECK (source IN ('manual', 'idp'));
    """)
    for table in ("tenant_identity", "tenant_identity_provider"):
        op.execute(f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {table}_owner ON {table} TO platform_owner USING (true) WITH CHECK (true);
        CREATE POLICY {table}_tenant ON {table} TO platform_app
          USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant());
        GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO platform_app;
        """)
    op.execute("""
    CREATE FUNCTION identity_route(p_domain text)
      RETURNS TABLE (tenant_id uuid, tenant_slug text, alias text, sso_only boolean, mfa_required boolean)
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT t.id, t.slug, p.alias, p.sso_only, coalesce(i.mfa_required, false)
        FROM tenant_identity_provider p
        JOIN tenant t ON t.id = p.tenant_id AND t.status = 'active'
        LEFT JOIN tenant_identity i ON i.tenant_id = p.tenant_id
       WHERE lower(p_domain) = ANY (p.domains) AND p.status = 'active'
      UNION ALL
      SELECT t.id, t.slug, NULL, false, i.mfa_required
        FROM tenant_identity i
        JOIN tenant t ON t.id = i.tenant_id AND t.status = 'active'
       WHERE lower(p_domain) = ANY (i.domains)
         AND NOT EXISTS (SELECT 1 FROM tenant_identity_provider p
                          WHERE lower(p_domain) = ANY (p.domains) AND p.status = 'active')
      LIMIT 1
    $$;
    REVOKE ALL ON FUNCTION identity_route(text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION identity_route(text) TO platform_app;

    INSERT INTO permission (key, description)
      VALUES ('identity.manage', 'Configure how the tenant signs in: SSO providers, own accounts and MFA');
    INSERT INTO permission_scope (permission_key, scope) VALUES ('identity.manage', 'tenant');
    INSERT INTO role_permission (tenant_id, role_id, role_scope, permission_key)
      SELECT tenant_id, id, scope, 'identity.manage' FROM role WHERE key = 'tenantAdmin' AND scope = 'tenant'
      ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
    DELETE FROM role_permission WHERE permission_key = 'identity.manage';
    DELETE FROM permission_scope WHERE permission_key = 'identity.manage';
    DELETE FROM permission WHERE key = 'identity.manage';
    DROP FUNCTION identity_route(text);
    ALTER TABLE role_assignment DROP COLUMN source;
    DROP TABLE tenant_identity_provider;
    DROP FUNCTION tenant_identity_provider_unique_domains();
    DROP TABLE tenant_identity;
    DROP FUNCTION valid_domains(text[]);
    """)
