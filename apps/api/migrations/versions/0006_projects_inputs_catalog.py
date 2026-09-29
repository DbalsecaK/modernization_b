"""Projects, inputs and the agent / skill catalog (spec 7.1, 8, 9, 18.3, 19.4; plan M2 section 3).

Global catalog (platform data, loaded by `catalog-sync` from the repository files, ADR-0006): agent_definition and
skill_definition (versioned: projects pin a version), source_adapter, source_option, target_option,
compatibility_rule and pipeline_template. Tenant data with forced RLS: project_config (versioned, insert-only),
project_agent, project_skill, input_artifact and project_repository; `project` gains its flow and metadata.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-28
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TENANT_TABLES = ("project_config", "project_agent", "project_skill", "input_artifact", "project_repository")
LEVEL = "('certified', 'assisted', 'experimental')"
FLOW = "('modernization', 'newFeature')"
AXIS = "('architecture', 'backend', 'frontend', 'database', 'cloud')"
AUTONOMY = "('guided', 'balanced', 'autonomous')"


def upgrade() -> None:
    op.execute(f"""
    -- Catalog. `current` marks the version the repository files define now; older versions stay for the projects
    -- that pinned them (9.7).
    CREATE TABLE agent_definition (
      key text NOT NULL,
      version text NOT NULL,
      current boolean NOT NULL DEFAULT true,
      position integer NOT NULL,
      name text NOT NULL,
      name_es text NOT NULL,
      agent_group text NOT NULL CHECK (agent_group IN ('analysis', 'design', 'build', 'quality', 'control')),
      description text NOT NULL,
      description_es text NOT NULL,
      phases text[] NOT NULL,
      capabilities text[] NOT NULL DEFAULT '{{}}',
      tools text[] NOT NULL DEFAULT '{{}}',
      mandatory boolean NOT NULL DEFAULT false,
      level text NOT NULL CHECK (level IN {LEVEL}),
      default_profile text NOT NULL DEFAULT '',
      relative_cost integer NOT NULL CHECK (relative_cost BETWEEN 1 AND 3),
      recommend jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(recommend) = 'array'),
      synced_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (key, version)
    );
    CREATE UNIQUE INDEX agent_definition_current_key ON agent_definition (key) WHERE current;
    CREATE TABLE skill_definition (
      key text NOT NULL,
      version text NOT NULL,
      current boolean NOT NULL DEFAULT true,
      title text NOT NULL,
      description text NOT NULL,
      skill_type text NOT NULL CHECK (skill_type IN ('source', 'target', 'conversion', 'crossCutting', 'customer')),
      agents text[] NOT NULL,
      technologies text[] NOT NULL DEFAULT '{{}}',
      conflicts text[] NOT NULL DEFAULT '{{}}',
      requires text[] NOT NULL DEFAULT '{{}}',
      status text NOT NULL CHECK (status IN ('draft', 'evaluating', 'published', 'obsolete')),
      eval_score numeric(4, 3) CHECK (eval_score BETWEEN 0 AND 1),
      content text NOT NULL,
      content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{{64}}$'),
      synced_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (key, version)
    );
    CREATE UNIQUE INDEX skill_definition_current_key ON skill_definition (key) WHERE current;
    CREATE TABLE source_adapter (
      key text PRIMARY KEY,
      name text NOT NULL,
      level text NOT NULL CHECK (level IN {LEVEL}),
      version text NOT NULL,
      validation text NOT NULL
    );
    CREATE TABLE source_option (
      key text PRIMARY KEY,
      position integer NOT NULL,
      name text NOT NULL,
      flow text NOT NULL CHECK (flow IN {FLOW}),
      adapter_key text REFERENCES source_adapter (key),
      required_skills text[] NOT NULL DEFAULT '{{}}'
    );
    CREATE TABLE target_option (
      axis text NOT NULL CHECK (axis IN {AXIS}),
      key text NOT NULL,
      position integer NOT NULL,
      name text NOT NULL,
      level text CHECK (level IN {LEVEL}),
      wave integer CHECK (wave BETWEEN 1 AND 3),
      PRIMARY KEY (axis, key)
    );
    CREATE TABLE compatibility_rule (
      key text PRIMARY KEY,
      position integer NOT NULL,
      condition jsonb NOT NULL CHECK (jsonb_typeof(condition) = 'object'),
      message text NOT NULL
    );
    CREATE TABLE pipeline_template (
      key text PRIMARY KEY,
      position integer NOT NULL,
      name text NOT NULL,
      description text NOT NULL,
      required_gates text[] NOT NULL,
      default_autonomy text NOT NULL CHECK (default_autonomy IN {AUTONOMY})
    );

    -- Projects (18.3). The status stays active / archived; the pipeline state arrives with the runs (M3).
    ALTER TABLE project
      ADD COLUMN flow text NOT NULL DEFAULT 'modernization' CHECK (flow IN {FLOW}),
      ADD COLUMN artifact_language text NOT NULL DEFAULT 'en' CHECK (artifact_language IN ('en', 'es')),
      ADD COLUMN description text NOT NULL DEFAULT '' CHECK (length(description) <= 2000),
      ADD COLUMN created_by uuid REFERENCES app_user (id),
      ADD CONSTRAINT project_tenant_name_key UNIQUE (tenant_id, name);

    -- The configuration of a project, one row per version (never updated: a change is a new version).
    CREATE TABLE project_config (
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      version integer NOT NULL CHECK (version >= 1),
      sources text[] NOT NULL CHECK (cardinality(sources) >= 1),
      target jsonb NOT NULL CHECK (jsonb_typeof(target) = 'object'),
      pipeline_template text NOT NULL REFERENCES pipeline_template (key),
      autonomy text NOT NULL CHECK (autonomy IN {AUTONOMY}),
      max_iterations integer NOT NULL CHECK (max_iterations BETWEEN 1 AND 10),
      sampling_pct integer NOT NULL CHECK (sampling_pct BETWEEN 0 AND 100),
      warnings text[] NOT NULL DEFAULT '{{}}',
      change_note text CHECK (length(change_note) <= 500),
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (project_id, version),
      UNIQUE (project_id, version, tenant_id),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE
    );
    -- The team of agents and the skills of one configuration version, with the catalog version pinned.
    CREATE TABLE project_agent (
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      config_version integer NOT NULL,
      agent_key text NOT NULL,
      agent_version text NOT NULL,
      -- Why it was recommended (a stable key), or NULL when the user added it.
      reason text,
      PRIMARY KEY (project_id, config_version, agent_key),
      FOREIGN KEY (project_id, config_version, tenant_id)
        REFERENCES project_config (project_id, version, tenant_id) ON DELETE CASCADE,
      FOREIGN KEY (agent_key, agent_version) REFERENCES agent_definition (key, version)
    );
    CREATE TABLE project_skill (
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      config_version integer NOT NULL,
      skill_key text NOT NULL,
      skill_version text NOT NULL,
      recommended boolean NOT NULL,
      PRIMARY KEY (project_id, config_version, skill_key),
      FOREIGN KEY (project_id, config_version, tenant_id)
        REFERENCES project_config (project_id, version, tenant_id) ON DELETE CASCADE,
      FOREIGN KEY (skill_key, skill_version) REFERENCES skill_definition (key, version)
    );

    -- Inputs (7.1, 15.4): files validated before they are stored, and links. A rejected upload keeps its record
    -- (why) but has no object and no version.
    CREATE TABLE input_artifact (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      kind text NOT NULL CHECK (kind IN ('source_archive', 'document', 'screenshot', 'figma_link', 'prototype_link')),
      name text NOT NULL CHECK (length(name) BETWEEN 1 AND 255),
      version integer CHECK (version >= 1),
      status text NOT NULL CHECK (status IN ('accepted', 'rejected', 'deleted')),
      object_key text,
      size_bytes bigint CHECK (size_bytes >= 0),
      sha256 text CHECK (sha256 ~ '^[0-9a-f]{{64}}$'),
      content_type text,
      url text CHECK (length(url) <= 2000),
      notes text NOT NULL DEFAULT '' CHECK (length(notes) <= 2000),
      findings jsonb NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(findings) = 'object'),
      rejection_code text,
      rejection_detail text,
      uploaded_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      deleted_at timestamptz,
      UNIQUE (project_id, kind, name, version),
      CHECK ((status = 'rejected') = (version IS NULL)),
      CHECK ((status = 'rejected') = (rejection_code IS NOT NULL)),
      CHECK ((kind IN ('figma_link', 'prototype_link')) = (url IS NOT NULL)),
      CHECK (status <> 'accepted' OR kind IN ('figma_link', 'prototype_link') OR
             (object_key IS NOT NULL AND sha256 IS NOT NULL AND size_bytes IS NOT NULL)),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE
    );
    CREATE INDEX input_artifact_project_idx ON input_artifact (project_id, kind, name);

    -- The Git repository of the project (7.1). The token lives in the secrets store (ADR-0007): only its path here.
    CREATE TABLE project_repository (
      tenant_id uuid NOT NULL,
      project_id uuid PRIMARY KEY,
      url text NOT NULL CHECK (url ~ '^https://' AND length(url) <= 500),
      branch text NOT NULL DEFAULT 'main' CHECK (length(branch) BETWEEN 1 AND 255),
      vault_path text,
      status text NOT NULL DEFAULT 'untested' CHECK (status IN ('untested', 'ok', 'failed')),
      last_checked_at timestamptz,
      last_check_detail text,
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE
    );
    CREATE TRIGGER project_repository_updated_at BEFORE UPDATE ON project_repository
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
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
    -- The catalog is written by catalog-sync (platform_owner); the API only reads it.
    GRANT SELECT ON agent_definition, skill_definition, source_adapter, source_option, target_option,
      compatibility_rule, pipeline_template TO platform_app;
    -- A configuration is never changed in place: a change is a new version.
    GRANT SELECT, INSERT ON project_config, project_agent, project_skill TO platform_app;
    GRANT SELECT, INSERT ON input_artifact TO platform_app;
    GRANT UPDATE (status, deleted_at, object_key) ON input_artifact TO platform_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON project_repository TO platform_app;
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE project_repository, input_artifact, project_skill, project_agent, project_config;
    ALTER TABLE project DROP CONSTRAINT project_tenant_name_key, DROP COLUMN created_by, DROP COLUMN description,
      DROP COLUMN artifact_language, DROP COLUMN flow;
    DROP TABLE pipeline_template, compatibility_rule, target_option, source_option, source_adapter,
      skill_definition, agent_definition;
    """)
