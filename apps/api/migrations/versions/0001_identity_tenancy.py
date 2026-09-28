"""Identity and tenancy: tenants, users, memberships, roles, permissions, assignments, projects, invitations,
OpenFGA outbox. Row-Level Security on every table (spec 14.2, 16, 19.4; plan M0 section 4).

Session variables read by the policies (set with SET LOCAL by the API, never from a client parameter):
  app.tenant_id       active tenant of the session
  app.user_id         platform user of the session
  app.platform_scope  'on' only after OpenFGA confirmed a platform role
  app.auth_sub        Keycloak `sub` during sign-in, before the user id is known
  app.auth_email      verified e-mail during sign-in, to find pending invitations

Revision ID: 0001
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TENANT_TABLES = ("role", "role_permission", "project", "role_assignment", "invitation")
RLS_TABLES = ("tenant", "app_user", "membership", *TENANT_TABLES, "authz_outbox")

PERMISSIONS = [
    ("project.create", ["tenant"], "Create projects in the tenant"),
    ("project.configure", ["project"], "Change the configuration of a project"),
    ("input.upload", ["project"], "Upload inputs to a project"),
    ("pipeline.run", ["project"], "Run the pipeline of a project"),
    ("gate.c1.approve", ["project"], "Approve gate C1"),
    ("gate.c2.approve", ["project"], "Approve gate C2"),
    ("gate.c3.approve", ["project"], "Approve gate C3"),
    ("signoff.sign", ["project"], "Sign the sign-off of a project"),
    ("code.view", ["tenant", "project"], "View generated and source code"),
    ("code.download", ["project"], "Download code"),
    ("code.push", ["project"], "Push code to the customer repository"),
    ("models.configure", ["tenant"], "Configure AI connections, catalog and profiles"),
    ("usage.view", ["tenant", "project"], "View token usage"),
    ("cost.view", ["tenant"], "View costs in money"),
    ("agents.select", ["project"], "Select the agents of a project"),
    ("skills.select", ["project"], "Select the skills of a project"),
    ("skills.publish", ["tenant"], "Publish customer skills"),
    ("users.manage", ["tenant"], "Manage users, invitations, roles and permissions"),
    ("audit.view", ["tenant"], "View the audit log"),
]


def upgrade() -> None:
    op.execute("""
    CREATE FUNCTION app_current_tenant() RETURNS uuid LANGUAGE sql STABLE
      AS $$ SELECT nullif(current_setting('app.tenant_id', true), '')::uuid $$;
    CREATE FUNCTION app_current_user() RETURNS uuid LANGUAGE sql STABLE
      AS $$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$;
    CREATE FUNCTION app_platform_scope() RETURNS boolean LANGUAGE sql STABLE
      AS $$ SELECT coalesce(current_setting('app.platform_scope', true), '') = 'on' $$;
    CREATE FUNCTION app_auth_sub() RETURNS text LANGUAGE sql STABLE
      AS $$ SELECT nullif(current_setting('app.auth_sub', true), '') $$;
    CREATE FUNCTION app_auth_email() RETURNS text LANGUAGE sql STABLE
      AS $$ SELECT lower(nullif(current_setting('app.auth_email', true), '')) $$;

    CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN NEW.updated_at = now(); RETURN NEW; END $$;
    """)

    op.execute("""
    CREATE TABLE tenant (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
      name text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
      status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
      deployment_model text NOT NULL DEFAULT 'sharedSaas'
        CHECK (deployment_model IN ('sharedSaas', 'dedicatedSaas', 'customerCloud', 'onPrem')),
      default_language text NOT NULL DEFAULT 'en' CHECK (default_language IN ('en', 'es')),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );

    -- Global identity: one person can belong to several tenants. No credential columns: they live in Keycloak.
    CREATE TABLE app_user (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      keycloak_sub text UNIQUE,
      email text NOT NULL CHECK (position('@' IN email) > 1),
      display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
      locale text NOT NULL DEFAULT 'en' CHECK (locale IN ('en', 'es')),
      status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
      last_login_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX app_user_email_key ON app_user (lower(email));

    CREATE TABLE membership (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenant (id),
      user_id uuid NOT NULL REFERENCES app_user (id),
      status text NOT NULL DEFAULT 'active' CHECK (status IN ('invited', 'active', 'suspended')),
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (tenant_id, user_id)
    );
    CREATE INDEX membership_user_idx ON membership (user_id);

    -- Catalog (16.2), read-only for the API. A permission can be granted at tenant level, project level or both.
    CREATE TABLE permission (
      key text PRIMARY KEY CHECK (key ~ '^[a-z0-9]+(\\.[a-z0-9]+)+$'),
      description text NOT NULL
    );
    CREATE TABLE permission_scope (
      permission_key text NOT NULL REFERENCES permission (key),
      scope text NOT NULL CHECK (scope IN ('tenant', 'project')),
      PRIMARY KEY (permission_key, scope)
    );

    -- Roles are per tenant (a copy of the base roles is made when the tenant is created).
    CREATE TABLE role (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenant (id),
      key text NOT NULL CHECK (key ~ '^[a-zA-Z][a-zA-Z0-9]{1,62}$'),
      scope text NOT NULL CHECK (scope IN ('tenant', 'project')),
      name text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
      is_system boolean NOT NULL DEFAULT false,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (tenant_id, key),
      UNIQUE (id, tenant_id, scope)
    );

    -- The composite keys keep the role, its tenant and the permission scope consistent.
    CREATE TABLE role_permission (
      tenant_id uuid NOT NULL,
      role_id uuid NOT NULL,
      role_scope text NOT NULL,
      permission_key text NOT NULL,
      PRIMARY KEY (role_id, permission_key),
      FOREIGN KEY (role_id, tenant_id, role_scope) REFERENCES role (id, tenant_id, scope) ON DELETE CASCADE,
      FOREIGN KEY (permission_key, role_scope) REFERENCES permission_scope (permission_key, scope)
    );

    -- Minimal project for the per-project role; full CRUD and wizard are M2.
    CREATE TABLE project (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenant (id),
      name text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
      status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (id, tenant_id)
    );

    -- A tenant role (project_id NULL) or a project role in one project. Requires a membership in the tenant.
    CREATE TABLE role_assignment (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      user_id uuid NOT NULL,
      role_id uuid NOT NULL,
      scope text NOT NULL,
      project_id uuid,
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      CHECK ((scope = 'tenant' AND project_id IS NULL) OR (scope = 'project' AND project_id IS NOT NULL)),
      FOREIGN KEY (tenant_id, user_id) REFERENCES membership (tenant_id, user_id) ON DELETE CASCADE,
      FOREIGN KEY (role_id, tenant_id, scope) REFERENCES role (id, tenant_id, scope),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id),
      UNIQUE NULLS NOT DISTINCT (user_id, role_id, project_id)
    );
    CREATE INDEX role_assignment_tenant_user_idx ON role_assignment (tenant_id, user_id);

    -- The invitation e-mail is sent by Keycloak; the platform stores no token.
    CREATE TABLE invitation (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenant (id),
      email text NOT NULL CHECK (position('@' IN email) > 1),
      role_id uuid NOT NULL,
      role_scope text NOT NULL,
      project_id uuid,
      status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'revoked', 'expired')),
      keycloak_user_id text,
      invited_by uuid NOT NULL REFERENCES app_user (id),
      expires_at timestamptz NOT NULL,
      accepted_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      CHECK ((role_scope = 'tenant' AND project_id IS NULL) OR (role_scope = 'project' AND project_id IS NOT NULL)),
      FOREIGN KEY (role_id, tenant_id, role_scope) REFERENCES role (id, tenant_id, scope),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id)
    );
    CREATE INDEX invitation_email_idx ON invitation (lower(email)) WHERE status = 'pending';

    -- Platform roles are not tenant data: assigned by operators, read by the API for the OpenFGA sync.
    CREATE TABLE platform_role_assignment (
      user_id uuid NOT NULL REFERENCES app_user (id),
      role text NOT NULL CHECK (role IN ('superAdmin', 'supportOperator')),
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (user_id, role)
    );

    -- Written in the same transaction as the business row; published to OpenFGA by the relay (ADR-0001).
    CREATE TABLE authz_outbox (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      tenant_id uuid REFERENCES tenant (id),
      operation text NOT NULL CHECK (operation IN ('write', 'delete')),
      tuples jsonb NOT NULL CHECK (jsonb_typeof(tuples) = 'array' AND jsonb_array_length(tuples) > 0),
      status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'failed')),
      attempts integer NOT NULL DEFAULT 0,
      last_error text,
      created_at timestamptz NOT NULL DEFAULT now(),
      processed_at timestamptz
    );
    CREATE INDEX authz_outbox_pending_idx ON authz_outbox (id) WHERE status = 'pending';
    """)

    for table in ("tenant", "app_user", "membership", "role", "project", "invitation"):
        op.execute(
            f"CREATE TRIGGER {table}_updated_at BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )

    # Seed the permission catalog (kept equal to nexti_core.authz_catalog by a test).
    permission = sa.table("permission", sa.column("key", sa.Text), sa.column("description", sa.Text))
    permission_scope = sa.table("permission_scope", sa.column("permission_key", sa.Text), sa.column("scope", sa.Text))
    op.bulk_insert(permission, [{"key": key, "description": description} for key, _, description in PERMISSIONS])
    op.bulk_insert(
        permission_scope,
        [{"permission_key": key, "scope": scope} for key, scopes, _ in PERMISSIONS for scope in scopes],
    )

    # Row-Level Security. FORCE makes it apply to the table owner too; the migration role gets an explicit
    # policy so it can seed and repair data. The runtime roles never have BYPASSRLS.
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_owner ON {table} TO platform_owner USING (true) WITH CHECK (true)")
        op.execute(
            f"CREATE POLICY {table}_platform ON {table} TO platform_app "
            "USING (app_platform_scope()) WITH CHECK (app_platform_scope())"
        )

    op.execute("""
    -- Tenant: the active one, plus the ones the user belongs to (tenant switcher).
    CREATE POLICY tenant_active ON tenant TO platform_app
      USING (id = app_current_tenant()) WITH CHECK (id = app_current_tenant());
    CREATE POLICY tenant_member ON tenant FOR SELECT TO platform_app
      USING (EXISTS (SELECT 1 FROM membership m
                     WHERE m.tenant_id = tenant.id AND m.user_id = app_current_user() AND m.status = 'active'));

    -- Users: oneself, the users of the active tenant, and the signing-in user found by sub or e-mail.
    CREATE POLICY app_user_visible ON app_user FOR SELECT TO platform_app
      USING (id = app_current_user()
             OR keycloak_sub = app_auth_sub()
             OR lower(email) = app_auth_email()
             OR EXISTS (SELECT 1 FROM membership m
                        WHERE m.user_id = app_user.id AND m.tenant_id = app_current_tenant()));
    CREATE POLICY app_user_sign_in ON app_user FOR INSERT TO platform_app
      WITH CHECK (keycloak_sub = app_auth_sub());
    CREATE POLICY app_user_update_self ON app_user FOR UPDATE TO platform_app
      USING (id = app_current_user() OR keycloak_sub = app_auth_sub() OR lower(email) = app_auth_email())
      WITH CHECK (id = app_current_user() OR keycloak_sub = app_auth_sub() OR lower(email) = app_auth_email());

    -- Memberships: the active tenant's, plus one's own in any tenant.
    CREATE POLICY membership_tenant ON membership TO platform_app
      USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant());
    CREATE POLICY membership_own ON membership FOR SELECT TO platform_app
      USING (user_id = app_current_user());

    -- Invitations: the active tenant's, plus the pending ones of the signing-in e-mail (accepted at login).
    CREATE POLICY invitation_for_email ON invitation FOR SELECT TO platform_app
      USING (status = 'pending' AND lower(email) = app_auth_email());

    -- Outbox: the API writes for the active tenant (platform tuples need platform scope); the relay reads all.
    CREATE POLICY authz_outbox_tenant ON authz_outbox TO platform_app
      USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant());
    CREATE POLICY authz_outbox_relay ON authz_outbox FOR SELECT TO authz_relay USING (true);
    CREATE POLICY authz_outbox_relay_update ON authz_outbox FOR UPDATE TO authz_relay
      USING (true) WITH CHECK (true);
    """)
    for table in TENANT_TABLES:
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} TO platform_app "
            "USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())"
        )

    # Inviting a person who may already exist in another tenant: the admin cannot see that user (RLS), so this
    # function (owned by the migration role) returns the id without exposing the row.
    op.execute("""
    CREATE FUNCTION ensure_user_for_invitation(p_email text, p_display_name text) RETURNS uuid
      LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DECLARE
      v_id uuid;
    BEGIN
      IF app_current_tenant() IS NULL THEN
        RAISE EXCEPTION 'ensure_user_for_invitation requires an active tenant';
      END IF;
      SELECT id INTO v_id FROM app_user WHERE lower(email) = lower(p_email);
      IF v_id IS NULL THEN
        INSERT INTO app_user (email, display_name) VALUES (lower(p_email), p_display_name) RETURNING id INTO v_id;
      END IF;
      RETURN v_id;
    END $$;
    REVOKE ALL ON FUNCTION ensure_user_for_invitation(text, text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION ensure_user_for_invitation(text, text) TO platform_app;
    """)

    op.execute("""
    GRANT USAGE ON SCHEMA public TO platform_app, authz_relay;
    GRANT SELECT, INSERT, UPDATE ON tenant, app_user TO platform_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON membership, role, role_permission, project, role_assignment,
      invitation TO platform_app;
    GRANT SELECT ON permission, permission_scope, platform_role_assignment TO platform_app;
    GRANT SELECT, INSERT ON authz_outbox TO platform_app;
    GRANT SELECT, UPDATE (status, attempts, last_error, processed_at) ON authz_outbox TO authz_relay;
    """)


def downgrade() -> None:
    op.execute("""
    DROP FUNCTION ensure_user_for_invitation(text, text);
    DROP TABLE authz_outbox, platform_role_assignment, invitation, role_assignment, project, role_permission,
      role, permission_scope, permission, membership, app_user, tenant;
    DROP FUNCTION set_updated_at(), app_current_tenant(), app_current_user(), app_platform_scope(),
      app_auth_sub(), app_auth_email();
    """)
