"""A rejected upload can be dismissed from the list of inputs (it stays in the audit log, where its rejection was
recorded). Rejected rows have no version, so they cannot become `deleted`; `dismissed_at` hides them instead.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-03
"""

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE input_artifact ADD COLUMN dismissed_at timestamptz,
      ADD CONSTRAINT input_artifact_dismissed_rejected CHECK (dismissed_at IS NULL OR status = 'rejected');
    GRANT UPDATE (dismissed_at) ON input_artifact TO platform_app;
    """)


def downgrade() -> None:
    op.execute("""
    REVOKE UPDATE (dismissed_at) ON input_artifact FROM platform_app;
    ALTER TABLE input_artifact DROP COLUMN dismissed_at;
    """)
