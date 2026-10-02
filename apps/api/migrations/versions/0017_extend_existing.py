"""Flow 3, add functionality to an existing application (spec 3.1, ADR-0026; plan M11).

A fourth flow key, `extendExisting`, for projects and for the flows a source option lists: the existing Spring Boot
application is a new source option, and the documentary inputs of Flow 2 serve Flow 3 too. Its inputs reuse the
existing kinds (`source_archive` for the application's code, `document` for the request), so the input kinds do not
change.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-02
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

FLOW = "('modernization', 'newFeature', 'independentValidation', 'extendExisting')"
OLD_FLOW = "('modernization', 'newFeature', 'independentValidation')"
FLOWS = "ARRAY['modernization', 'newFeature', 'independentValidation', 'extendExisting']"
OLD_FLOWS = "ARRAY['modernization', 'newFeature', 'independentValidation']"


def upgrade() -> None:
    op.execute(f"""
    ALTER TABLE project DROP CONSTRAINT IF EXISTS project_flow_check,
      ADD CONSTRAINT project_flow_check CHECK (flow IN {FLOW});
    ALTER TABLE source_option DROP CONSTRAINT IF EXISTS source_option_flows_check,
      ADD CONSTRAINT source_option_flows_check CHECK (cardinality(flows) >= 1 AND flows <@ {FLOWS});
    """)


def downgrade() -> None:
    # Fails while a project of Flow 3 exists: it has no place in the previous schema. The source options of Flow 3 are
    # catalog rows: they lose the flow (or go, when it was their only one) and catalog-sync rewrites them.
    op.execute("""
    ALTER TABLE source_option DROP CONSTRAINT IF EXISTS source_option_flows_check;
    UPDATE source_option SET flows = array_remove(flows, 'extendExisting') WHERE 'extendExisting' = ANY (flows);
    DELETE FROM source_option WHERE cardinality(flows) = 0;
    """)
    op.execute(f"""
    ALTER TABLE source_option
      ADD CONSTRAINT source_option_flows_check CHECK (cardinality(flows) >= 1 AND flows <@ {OLD_FLOWS});
    ALTER TABLE project DROP CONSTRAINT IF EXISTS project_flow_check,
      ADD CONSTRAINT project_flow_check CHECK (flow IN {OLD_FLOW});
    """)
