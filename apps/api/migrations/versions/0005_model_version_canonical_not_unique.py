"""model_version.canonical_slug is not unique: OpenRouter lists aliases and variants of a model (":thinking",
":free", an undated id) under the canonical slug of the version they point to. provider_slug stays unique.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-28
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE model_version DROP CONSTRAINT model_version_canonical_slug_key;
    CREATE INDEX ix_model_version_canonical_slug ON model_version (canonical_slug);
    """)


def downgrade() -> None:
    op.execute("""
    DROP INDEX ix_model_version_canonical_slug;
    ALTER TABLE model_version ADD CONSTRAINT model_version_canonical_slug_key UNIQUE (canonical_slug);
    """)
