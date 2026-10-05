"""Artifacts and verdicts of a retried run (ADR-0035): a redone phase replaces its generated files instead of keeping
the rows of the earlier attempt (`phase` says which phase wrote each file; the app role may update and delete them),
and every verification attempt keeps its own verdict (`attempt`), never rewriting the earlier evidence.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-05
"""

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE generated_artifact ADD COLUMN phase text;
    GRANT UPDATE, DELETE ON generated_artifact TO platform_app;
    ALTER TABLE verdict ADD COLUMN attempt integer NOT NULL DEFAULT 1 CHECK (attempt >= 1);
    ALTER TABLE verdict DROP CONSTRAINT verdict_run_id_module_key;
    ALTER TABLE verdict ADD CONSTRAINT verdict_run_id_module_attempt_key UNIQUE (run_id, module, attempt);
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE verdict DROP CONSTRAINT verdict_run_id_module_attempt_key;
    ALTER TABLE verdict ADD CONSTRAINT verdict_run_id_module_key UNIQUE (run_id, module);
    ALTER TABLE verdict DROP COLUMN attempt;
    REVOKE UPDATE, DELETE ON generated_artifact FROM platform_app;
    ALTER TABLE generated_artifact DROP COLUMN phase;
    """)
