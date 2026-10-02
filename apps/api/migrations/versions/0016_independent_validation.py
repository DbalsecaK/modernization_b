"""Flow 4, independent validation of a third party's migration (spec 3.3, ADR-0025; plan M10).

A third flow key, `independentValidation`, for projects; a source option now lists the flows that offer it (the legacy
technologies serve Flow 1 and Flow 4), so `source_option.flow` becomes `flows text[]`; and a new input kind,
`target_archive`: the third party's code and its runnable artifact, validated like `source_archive`.

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


def downgrade() -> None:
    # Fails while a project of Flow 4 or a target archive exists: they have no place in the previous schema.
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
