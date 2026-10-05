"""The versions a source or target option lists (ADR-0037): kept with the option so the catalog the API serves is
the one the sync loaded.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-05
"""

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE source_option ADD COLUMN versions jsonb NOT NULL DEFAULT '[]'::jsonb;
    ALTER TABLE target_option ADD COLUMN versions jsonb NOT NULL DEFAULT '[]'::jsonb;
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE target_option DROP COLUMN versions;
    ALTER TABLE source_option DROP COLUMN versions;
    """)
