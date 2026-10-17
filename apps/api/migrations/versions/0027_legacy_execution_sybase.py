"""A project's legacy may also run on a Sybase ASE test server of the customer (ADR-0055, `kind = sybase`): the
check on the kind of live system admits it.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-17
"""

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE project_legacy_execution DROP CONSTRAINT project_legacy_execution_kind_check;
    ALTER TABLE project_legacy_execution
      ADD CONSTRAINT project_legacy_execution_kind_check CHECK (kind IN ('ibmi', 'sybase'));
    """)


def downgrade() -> None:
    op.execute("""
    UPDATE project_legacy_execution SET mode = 'auto', kind = NULL, config = '{}'::jsonb WHERE kind = 'sybase';
    ALTER TABLE project_legacy_execution DROP CONSTRAINT project_legacy_execution_kind_check;
    ALTER TABLE project_legacy_execution ADD CONSTRAINT project_legacy_execution_kind_check CHECK (kind IN ('ibmi'));
    """)
