"""SCIM 2.0 per tenant (spec 13 and 15.1, ADR-0031; plan M16 step 2).

- `scim_access`: the bearer the customer's identity provider presents to /scim/v2. Only the SHA-256 digest of the
  high-entropy value is kept (it is shown once, when created) and a short hint to recognise it; at most one is active
  per tenant. Revoked rows stay as history.
- `scim_user`: a person the identity provider manages in the tenant, tied to the platform account (`app_user`) through
  its membership, and to the Keycloak account it created or linked. Deactivating keeps the row (history).
- `scim_group` and `scim_group_member`: the groups of the identity provider and who is in them. A group gives tenant
  roles through the same group -> role mapping as the identity providers (`role_assignment.source = 'scim'`).
- `scim_access_tenant(digest)`: the tenant of an active bearer, before any tenant is known (SECURITY DEFINER, it
  returns the row only to the API role).
- `scim_user_shared(user)`: whether a member of the active tenant is also an active member of another tenant (then
  deactivating them here must not disable their Keycloak account). It answers only for members of the active tenant.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-02
"""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

TABLES = ("scim_access", "scim_user", "scim_group", "scim_group_member")


def upgrade() -> None:
    op.execute("""
    CREATE TABLE scim_access (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenant (id) ON DELETE CASCADE,
      -- SHA-256 of the bearer value; the value itself is never stored.
      access_digest bytea NOT NULL UNIQUE CHECK (length(access_digest) = 32),
      -- The last characters of the value, so an administrator can tell which one the provider holds.
      hint text NOT NULL CHECK (length(hint) BETWEEN 1 AND 8),
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      last_used_at timestamptz,
      revoked_at timestamptz,
      revoked_by uuid REFERENCES app_user (id)
    );
    CREATE UNIQUE INDEX scim_access_active ON scim_access (tenant_id) WHERE revoked_at IS NULL;

    CREATE TABLE scim_user (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      user_id uuid NOT NULL,
      -- The Keycloak account created or linked for this person.
      keycloak_id text,
      user_name text NOT NULL CHECK (length(user_name) BETWEEN 1 AND 320),
      external_id text CHECK (length(external_id) <= 320),
      given_name text CHECK (length(given_name) <= 200),
      family_name text CHECK (length(family_name) <= 200),
      display_name text CHECK (length(display_name) <= 200),
      email text NOT NULL CHECK (length(email) BETWEEN 3 AND 320),
      active boolean NOT NULL DEFAULT true,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (id, tenant_id),
      UNIQUE (tenant_id, user_id),
      FOREIGN KEY (tenant_id, user_id) REFERENCES membership (tenant_id, user_id) ON DELETE CASCADE
    );
    CREATE UNIQUE INDEX scim_user_name_key ON scim_user (tenant_id, lower(user_name));
    CREATE INDEX scim_user_external_id ON scim_user (tenant_id, external_id);
    CREATE TRIGGER scim_user_updated BEFORE UPDATE ON scim_user FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    CREATE TABLE scim_group (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenant (id) ON DELETE CASCADE,
      display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 256),
      external_id text CHECK (length(external_id) <= 320),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (id, tenant_id)
    );
    CREATE UNIQUE INDEX scim_group_name_key ON scim_group (tenant_id, lower(display_name));
    CREATE TRIGGER scim_group_updated BEFORE UPDATE ON scim_group FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    CREATE TABLE scim_group_member (
      tenant_id uuid NOT NULL,
      group_id uuid NOT NULL,
      member_id uuid NOT NULL,
      PRIMARY KEY (group_id, member_id),
      FOREIGN KEY (group_id, tenant_id) REFERENCES scim_group (id, tenant_id) ON DELETE CASCADE,
      FOREIGN KEY (member_id, tenant_id) REFERENCES scim_user (id, tenant_id) ON DELETE CASCADE
    );
    CREATE INDEX scim_group_member_member ON scim_group_member (member_id);

    ALTER TABLE role_assignment DROP CONSTRAINT role_assignment_source_check,
      ADD CONSTRAINT role_assignment_source_check CHECK (source IN ('manual', 'idp', 'scim'));
    """)
    for table in TABLES:
        op.execute(f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {table}_owner ON {table} TO platform_owner USING (true) WITH CHECK (true);
        CREATE POLICY {table}_tenant ON {table} TO platform_app
          USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant());
        """)
    op.execute("""
    GRANT SELECT, INSERT, UPDATE ON scim_access TO platform_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON scim_user, scim_group, scim_group_member TO platform_app;

    CREATE FUNCTION scim_access_tenant(p_digest bytea)
      RETURNS TABLE (access_id uuid, tenant_id uuid, access_digest bytea)
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT a.id, a.tenant_id, a.access_digest FROM scim_access a
        JOIN tenant t ON t.id = a.tenant_id AND t.status = 'active'
       WHERE a.access_digest = p_digest AND a.revoked_at IS NULL
    $$;
    REVOKE ALL ON FUNCTION scim_access_tenant(bytea) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION scim_access_tenant(bytea) TO platform_app;

    CREATE FUNCTION scim_user_shared(p_user uuid) RETURNS boolean
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT app_current_tenant() IS NOT NULL
         AND EXISTS (SELECT 1 FROM membership m WHERE m.user_id = p_user AND m.tenant_id = app_current_tenant())
         AND EXISTS (SELECT 1 FROM membership m
                      WHERE m.user_id = p_user AND m.tenant_id <> app_current_tenant() AND m.status = 'active')
    $$;
    REVOKE ALL ON FUNCTION scim_user_shared(uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION scim_user_shared(uuid) TO platform_app;

    -- Whether another tenant also declares a domain (as its own or for one of its providers): such a domain is not
    -- the active tenant's to provision from, since accounts are global (D-20). It answers yes or no, nothing else.
    CREATE FUNCTION scim_domain_claimed_elsewhere(p_domain text) RETURNS boolean
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT app_current_tenant() IS NOT NULL AND (
        EXISTS (SELECT 1 FROM tenant_identity i
                 WHERE i.tenant_id <> app_current_tenant() AND lower(p_domain) = ANY (i.domains))
        OR EXISTS (SELECT 1 FROM tenant_identity_provider p
                    WHERE p.tenant_id <> app_current_tenant() AND lower(p_domain) = ANY (p.domains)))
    $$;
    REVOKE ALL ON FUNCTION scim_domain_claimed_elsewhere(text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION scim_domain_claimed_elsewhere(text) TO platform_app;
    """)


def downgrade() -> None:
    op.execute("""
    DROP FUNCTION IF EXISTS scim_domain_claimed_elsewhere(text);
    DROP FUNCTION scim_user_shared(uuid);
    DROP FUNCTION scim_access_tenant(bytea);
    DELETE FROM role_assignment WHERE source = 'scim';
    ALTER TABLE role_assignment DROP CONSTRAINT role_assignment_source_check,
      ADD CONSTRAINT role_assignment_source_check CHECK (source IN ('manual', 'idp'));
    DROP TABLE scim_group_member, scim_group, scim_user, scim_access;
    """)
