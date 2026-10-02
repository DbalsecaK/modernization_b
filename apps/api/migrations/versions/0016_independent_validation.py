"""Flow 4, independent validation of a third party's migration (spec 3.3, ADR-0025; plan M10).

A third flow key, `independentValidation`, for projects; a source option now lists the flows that offer it (the legacy
technologies serve Flow 1 and Flow 4), so `source_option.flow` becomes `flows text[]`; and a new input kind,
`target_archive`: the third party's code and its runnable artifact, validated like `source_archive`. The mapping a
person corrects before C2 is versioned in `ivv_mapping_version` (references only; the YAML is in the object store),
append-only for the application.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-01
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

FLOW = "('modernization', 'newFeature', 'independentValidation')"
OLD_FLOW = "('modernization', 'newFeature')"
KIND = "('source_archive', 'target_archive', 'document', 'screenshot', 'figma_link', 'prototype_link')"
OLD_KIND = "('source_archive', 'document', 'screenshot', 'figma_link', 'prototype_link')"


def upgrade() -> None:
    op.execute(f"""
    ALTER TABLE project DROP CONSTRAINT IF EXISTS project_flow_check,
      ADD CONSTRAINT project_flow_check CHECK (flow IN {FLOW});
    ALTER TABLE input_artifact DROP CONSTRAINT IF EXISTS input_artifact_kind_check,
      ADD CONSTRAINT input_artifact_kind_check CHECK (kind IN {KIND});
    """)
    op.execute("""
    -- catalog-sync rewrites the options from the repository files; the existing rows keep their one flow.
    ALTER TABLE source_option ADD COLUMN flows text[];
    UPDATE source_option SET flows = ARRAY[flow];
    ALTER TABLE source_option DROP COLUMN flow,
      ALTER COLUMN flows SET NOT NULL,
      ADD CONSTRAINT source_option_flows_check
        CHECK (cardinality(flows) >= 1 AND flows <@ ARRAY['modernization', 'newFeature', 'independentValidation']);
    """)
    op.execute("""
    CREATE TABLE ivv_mapping_version (
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      version integer NOT NULL CHECK (version >= 1),
      object_key text NOT NULL CHECK (length(object_key) BETWEEN 1 AND 1024),
      sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
      size_bytes bigint NOT NULL CHECK (size_bytes BETWEEN 1 AND 524288),
      problems integer NOT NULL DEFAULT 0 CHECK (problems >= 0),
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (project_id, version),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE
    );
    ALTER TABLE ivv_mapping_version ENABLE ROW LEVEL SECURITY;
    ALTER TABLE ivv_mapping_version FORCE ROW LEVEL SECURITY;
    CREATE POLICY ivv_mapping_version_owner ON ivv_mapping_version TO platform_owner USING (true) WITH CHECK (true);
    CREATE POLICY ivv_mapping_version_tenant ON ivv_mapping_version TO platform_app
      USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant());
    GRANT SELECT, INSERT ON ivv_mapping_version TO platform_app;
    """)


def downgrade() -> None:
    # Fails while a project of Flow 4 or a target archive exists: they have no place in the previous schema.
    op.execute("DROP TABLE IF EXISTS ivv_mapping_version")
    op.execute("""
    ALTER TABLE source_option ADD COLUMN flow text;
    UPDATE source_option SET flow = flows[1];
    ALTER TABLE source_option DROP COLUMN flows, ALTER COLUMN flow SET NOT NULL;
    """)
    op.execute(f"""
    ALTER TABLE source_option ADD CONSTRAINT source_option_flow_check CHECK (flow IN {OLD_FLOW});
    ALTER TABLE input_artifact DROP CONSTRAINT IF EXISTS input_artifact_kind_check,
      ADD CONSTRAINT input_artifact_kind_check CHECK (kind IN {OLD_KIND});
    ALTER TABLE project DROP CONSTRAINT IF EXISTS project_flow_check,
      ADD CONSTRAINT project_flow_check CHECK (flow IN {OLD_FLOW});
    """)
