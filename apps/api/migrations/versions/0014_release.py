"""Releases of a project (spec 6.1 phase 13, 7.2, ADR-0023; plan M9a).

Every delivery leaves a row: the release pushed to a new branch of the customer's repository (branch, commit, base),
the one that could not be pushed (and why) or the one left to download as a ZIP. Who asked for it, from which run.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-01
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE release (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      run_id uuid,
      kind text NOT NULL CHECK (kind IN ('push', 'zip')),
      status text NOT NULL CHECK (status IN ('pushed', 'failed', 'ready')),
      repository_url text,
      branch text,
      commit_sha text CHECK (commit_sha IS NULL OR commit_sha ~ '^[0-9a-f]{40}$'),
      base_sha text CHECK (base_sha IS NULL OR base_sha ~ '^[0-9a-f]{40}$'),
      files integer NOT NULL DEFAULT 0 CHECK (files >= 0),
      findings jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(findings) = 'object'),
      error text,
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE
    );
    CREATE INDEX release_project ON release (project_id, created_at DESC);
    ALTER TABLE release ENABLE ROW LEVEL SECURITY;
    ALTER TABLE release FORCE ROW LEVEL SECURITY;
    CREATE POLICY release_owner ON release TO platform_owner USING (true) WITH CHECK (true);
    CREATE POLICY release_tenant ON release TO platform_app
      USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant());
    GRANT SELECT, INSERT ON release TO platform_app;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE release")
