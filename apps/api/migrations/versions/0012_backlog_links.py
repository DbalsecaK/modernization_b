"""The project's backlog in Jira or Azure DevOps (spec 7.6, ADR-0019; plan M7b).

- `tenant_integration.config`: where the tool is (Jira site and account e-mail, Azure DevOps organization URL). Never a
  credential: that stays in the secrets store.
- `project_backlog`: the link of a project to one integration and its external project, the type and state mapping
  and the automation rules.
- `work_item_link`: one external item per element of the platform and linked project (idempotent writes).
- `bug_fix`: each correction the developer agent proposed for a bug, kept as a draft for a person to review.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-01
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

TENANT_TABLES = ("project_backlog", "work_item_link", "bug_fix")


def upgrade() -> None:
    op.execute("""
    ALTER TABLE tenant_integration ADD COLUMN config jsonb NOT NULL DEFAULT '{}'::jsonb
      CHECK (jsonb_typeof(config) = 'object');
    ALTER TABLE tenant_integration ADD CONSTRAINT tenant_integration_id_tenant UNIQUE (id, tenant_id);

    CREATE TABLE project_backlog (
      tenant_id uuid NOT NULL,
      project_id uuid PRIMARY KEY,
      integration_id uuid NOT NULL,
      external_project text NOT NULL CHECK (length(external_project) BETWEEN 1 AND 200),
      types jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(types) = 'object'),
      states jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(states) = 'object'),
      rules jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(rules) = 'object'),
      last_synced_at timestamptz,
      last_sync_detail text,
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE,
      FOREIGN KEY (integration_id, tenant_id) REFERENCES tenant_integration (id, tenant_id) ON DELETE RESTRICT
    );

    CREATE TABLE work_item_link (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      integration_id uuid NOT NULL,
      element text NOT NULL CHECK (length(element) BETWEEN 1 AND 300),
      kind text NOT NULL CHECK (kind IN ('feature', 'story', 'task', 'bug')),
      title text NOT NULL DEFAULT '',
      external_id text NOT NULL,
      external_key text NOT NULL,
      url text NOT NULL DEFAULT '',
      digest text NOT NULL,
      state text NOT NULL CHECK (state IN ('open', 'review', 'done', 'discarded')),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (project_id, integration_id, element),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE,
      FOREIGN KEY (integration_id, tenant_id) REFERENCES tenant_integration (id, tenant_id) ON DELETE CASCADE
    );

    CREATE TABLE bug_fix (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      element text NOT NULL,
      iteration integer NOT NULL CHECK (iteration >= 1),
      status text NOT NULL CHECK (status IN ('proposed', 'failed', 'escalated')),
      detail text NOT NULL DEFAULT '',
      -- The proposed files, in the object store (references only, 10.2): a draft a person reviews.
      files_key text,
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (project_id, element, iteration),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE
    );
    """)
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_owner ON {table} TO platform_owner USING (true) WITH CHECK (true)")
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} TO platform_app "
            "USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())"
        )
    op.execute("""
    GRANT SELECT, INSERT, UPDATE, DELETE ON project_backlog TO platform_app;
    GRANT SELECT, INSERT, UPDATE ON work_item_link TO platform_app;
    GRANT SELECT, INSERT ON bug_fix TO platform_app;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE bug_fix, work_item_link, project_backlog")
    op.execute("ALTER TABLE tenant_integration DROP CONSTRAINT tenant_integration_id_tenant")
    op.execute("ALTER TABLE tenant_integration DROP COLUMN config")
