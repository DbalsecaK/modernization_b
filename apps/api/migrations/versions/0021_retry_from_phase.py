"""A failed run may be retried from a phase a person chooses, at or before the one that failed (ADR-0035): the API
writes the choice, the worker resumes the graph there.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-05
"""

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE run ADD COLUMN retry_from text;
    GRANT UPDATE (retry_from) ON run TO platform_app;
    """)


def downgrade() -> None:
    op.execute("""
    REVOKE UPDATE (retry_from) ON run FROM platform_app;
    ALTER TABLE run DROP COLUMN retry_from;
    """)
