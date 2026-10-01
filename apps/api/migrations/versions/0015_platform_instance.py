"""Instances of the platform (spec 18.4 "Operación de plataforma", ADR-0024; plan M9b).

Every API and worker process registers when it starts and beats every minute: its name, component, version and
deployment profile. Platform operators see them; no tenant data. The processes write through `platform_heartbeat`
(they cannot read the table: that needs platform scope).

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-01
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE platform_instance (
      name text PRIMARY KEY CHECK (length(name) BETWEEN 1 AND 200),
      component text NOT NULL CHECK (component IN ('api', 'worker')),
      version text NOT NULL CHECK (length(version) BETWEEN 1 AND 100),
      profile text NOT NULL CHECK (length(profile) BETWEEN 1 AND 100),
      started_at timestamptz NOT NULL DEFAULT now(),
      last_seen_at timestamptz NOT NULL DEFAULT now()
    );
    ALTER TABLE platform_instance ENABLE ROW LEVEL SECURITY;
    ALTER TABLE platform_instance FORCE ROW LEVEL SECURITY;
    CREATE POLICY platform_instance_owner ON platform_instance TO platform_owner USING (true) WITH CHECK (true);
    CREATE POLICY platform_instance_operators ON platform_instance FOR SELECT TO platform_app
      USING (app_platform_scope());
    GRANT SELECT ON platform_instance TO platform_app;

    CREATE FUNCTION platform_heartbeat(p_name text, p_component text, p_version text, p_profile text, p_started boolean)
      RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
      INSERT INTO platform_instance (name, component, version, profile)
      VALUES (p_name, p_component, p_version, p_profile)
      ON CONFLICT (name) DO UPDATE SET component = EXCLUDED.component, version = EXCLUDED.version,
        profile = EXCLUDED.profile, last_seen_at = now(),
        started_at = CASE WHEN p_started THEN now() ELSE platform_instance.started_at END;
      DELETE FROM platform_instance WHERE last_seen_at < now() - interval '7 days';
    $$;
    REVOKE ALL ON FUNCTION platform_heartbeat(text, text, text, text, boolean) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION platform_heartbeat(text, text, text, text, boolean) TO platform_app;
    """)


def downgrade() -> None:
    op.execute("""
    DROP FUNCTION platform_heartbeat(text, text, text, text, boolean);
    DROP TABLE platform_instance;
    """)
