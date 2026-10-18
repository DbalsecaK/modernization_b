"""The certainty index of a verdict (ADR-0056, point 6): computed by the verification from the artefacts of the run,
with its components and its frontier, kept with the verdict so the API serves it and the delivery carries it.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-18
"""

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE verdict ADD COLUMN certainty jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE verdict DROP COLUMN certainty")
