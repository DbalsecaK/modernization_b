"""The spec, user stories and the plan by waves; generated artifacts, verdicts and evaluations (spec 4, 7.7, 11.3,
21.4; plan M4).

Tenant data with forced RLS. Nothing here is edited in place: every change of a spec element, a story or the plan is a
new version row (the current one is the highest version), so the history and the audit trail stay complete.
New project permissions `story.edit` and `plan.edit`.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-29
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "spec_element", "user_story", "user_story_version", "story_dependency", "migration_plan", "generated_artifact",
    "verdict", "evaluation",
)  # fmt: skip
PERMISSIONS = {
    "story.edit": ("Edit the user stories of a project", ("projectOwner", "analyst", "businessReviewer")),
    "plan.edit": ("Change the migration plan by waves", ("projectOwner", "architect")),
}


def upgrade() -> None:
    op.execute("""
    -- Elements of the spec (4.1): rules, capabilities, contracts, test cases. One row per version; the element's key
    -- (RULE-001...) is stable in the project. `data` is the element as the spec model defines it.
    CREATE TABLE spec_element (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      element_type text NOT NULL CHECK (element_type IN ('rule', 'capability', 'contract', 'test_case')),
      key text NOT NULL CHECK (key ~ '^[A-Z]+-[0-9]{3,}$'),
      version integer NOT NULL CHECK (version >= 1),
      status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'review', 'approved', 'reopened', 'obsolete')),
      data jsonb NOT NULL CHECK (jsonb_typeof(data) = 'object'),
      run_id uuid,
      origin text NOT NULL DEFAULT 'extracted' CHECK (origin IN ('extracted', 'person', 'imported')),
      change_note text CHECK (length(change_note) <= 2000),
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (project_id, element_type, key, version),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE
    );
    CREATE INDEX spec_element_current_idx ON spec_element (project_id, element_type, key, version DESC);

    -- User stories (7.7): identity here, content in versions.
    CREATE TABLE user_story (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      key text NOT NULL CHECK (key ~ '^US-[0-9]{3,}$'),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (project_id, key),
      UNIQUE (id, tenant_id),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE
    );

    CREATE TABLE user_story_version (
      tenant_id uuid NOT NULL,
      story_id uuid NOT NULL,
      version integer NOT NULL CHECK (version >= 1),
      feature text NOT NULL DEFAULT '' CHECK (length(feature) <= 200),
      title text NOT NULL CHECK (length(title) BETWEEN 3 AND 200),
      narrative text NOT NULL DEFAULT '' CHECK (length(narrative) <= 2000),
      criteria jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(criteria) = 'array'),
      links jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(links) = 'array'),
      priority text NOT NULL DEFAULT 'P1' CHECK (priority IN ('P0', 'P1', 'P2')),
      estimate integer NOT NULL DEFAULT 1 CHECK (estimate BETWEEN 1 AND 100),
      status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'review', 'question', 'approved', 'discarded', 'merged')),
      origin text NOT NULL DEFAULT 'extracted' CHECK (origin IN ('extracted', 'document', 'jira', 'person')),
      out_of_scope boolean NOT NULL DEFAULT false,
      merged_into uuid,
      reason text CHECK (length(reason) <= 2000),
      action text NOT NULL DEFAULT 'create'
        CHECK (action IN ('create', 'edit', 'split', 'merge', 'discard', 'restore', 'suggestion', 'status')),
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (story_id, version),
      CHECK (status <> 'discarded' OR reason IS NOT NULL),
      FOREIGN KEY (story_id, tenant_id) REFERENCES user_story (id, tenant_id) ON DELETE CASCADE
    );

    -- Dependencies between stories: from the graph (tables, calls) or added by people.
    CREATE TABLE story_dependency (
      tenant_id uuid NOT NULL,
      story_id uuid NOT NULL,
      depends_on uuid NOT NULL,
      strength text NOT NULL CHECK (strength IN ('hard', 'soft')),
      reason text NOT NULL DEFAULT '' CHECK (length(reason) <= 500),
      origin text NOT NULL DEFAULT 'graph' CHECK (origin IN ('graph', 'person')),
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (story_id, depends_on),
      CHECK (story_id <> depends_on),
      FOREIGN KEY (story_id, tenant_id) REFERENCES user_story (id, tenant_id) ON DELETE CASCADE,
      FOREIGN KEY (depends_on, tenant_id) REFERENCES user_story (id, tenant_id) ON DELETE CASCADE
    );

    -- The plan by waves (7.7): each change is a version; `suggested` keeps what the platform proposed.
    CREATE TABLE migration_plan (
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      version integer NOT NULL CHECK (version >= 1),
      waves jsonb NOT NULL CHECK (jsonb_typeof(waves) = 'array'),
      suggested jsonb NOT NULL CHECK (jsonb_typeof(suggested) = 'array'),
      warnings jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(warnings) = 'array'),
      change_note text CHECK (length(change_note) <= 2000),
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (project_id, version),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE
    );

    -- Files the generation produced (the content is in the object store; only references here).
    CREATE TABLE generated_artifact (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      run_id uuid NOT NULL,
      layer text NOT NULL CHECK (layer IN ('contracts', 'domain', 'adapters', 'orchestration', 'tests', 'docs')),
      path text NOT NULL CHECK (length(path) BETWEEN 1 AND 500),
      object_key text NOT NULL,
      sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
      size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
      rules jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(rules) = 'array'),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (run_id, path),
      FOREIGN KEY (run_id, tenant_id) REFERENCES run (id, tenant_id) ON DELETE CASCADE
    );

    -- The verdict of a module (11.3), computed by code: the six checks and what the verdict does not prove.
    CREATE TABLE verdict (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      run_id uuid NOT NULL,
      module text NOT NULL CHECK (length(module) BETWEEN 1 AND 200),
      verdict text NOT NULL CHECK (verdict IN ('PROVEN', 'PARTLY PROVEN', 'NOT PROVEN')),
      checks jsonb NOT NULL CHECK (jsonb_typeof(checks) = 'array'),
      not_proven jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(not_proven) = 'array'),
      proof_pack_key text,
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (run_id, module),
      FOREIGN KEY (run_id, tenant_id) REFERENCES run (id, tenant_id) ON DELETE CASCADE
    );

    -- Evaluations against a reference spec (21.4): name and hash of the reference, never its content (ADR-0011).
    CREATE TABLE evaluation (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      run_id uuid,
      reference text NOT NULL CHECK (length(reference) BETWEEN 1 AND 200),
      reference_sha256 text NOT NULL CHECK (reference_sha256 ~ '^[0-9a-f]{64}$'),
      metrics jsonb NOT NULL CHECK (jsonb_typeof(metrics) = 'object'),
      created_at timestamptz NOT NULL DEFAULT now(),
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

    # Versioned tables are append-only for the application; story dependencies can be removed by people.
    op.execute("""
    GRANT SELECT, INSERT ON spec_element, user_story, user_story_version, migration_plan, generated_artifact, verdict,
      evaluation TO platform_app;
    GRANT SELECT, INSERT, DELETE ON story_dependency TO platform_app;
    """)

    for key, (description, roles) in PERMISSIONS.items():
        op.execute(f"INSERT INTO permission (key, description) VALUES ('{key}', '{description}')")  # noqa: S608
        op.execute(f"INSERT INTO permission_scope (permission_key, scope) VALUES ('{key}', 'project')")  # noqa: S608
        role_list = ", ".join(f"'{r}'" for r in roles)
        op.execute(f"""  -- constant keys of this module
        INSERT INTO role_permission (tenant_id, role_id, role_scope, permission_key)
        SELECT tenant_id, id, scope, '{key}' FROM role WHERE key IN ({role_list}) AND scope = 'project'
        ON CONFLICT DO NOTHING
        """)  # noqa: S608


def downgrade() -> None:
    keys = ", ".join(f"'{k}'" for k in PERMISSIONS)
    op.execute(f"""
    DELETE FROM role_permission WHERE permission_key IN ({keys});
    DELETE FROM permission_scope WHERE permission_key IN ({keys});
    DELETE FROM permission WHERE key IN ({keys});
    """)  # noqa: S608
    op.execute(
        "DROP TABLE evaluation, verdict, generated_artifact, migration_plan, story_dependency, user_story_version, "
        "user_story, spec_element"
    )
