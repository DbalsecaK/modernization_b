"""Cursor of the Keycloak events already copied to the audit log (user events and admin events).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    -- Platform data (no tenant): the position of the poller in each Keycloak event stream.
    CREATE TABLE keycloak_event_cursor (
      kind text PRIMARY KEY CHECK (kind IN ('user', 'admin')),
      last_time bigint NOT NULL,
      -- Ids of the events at exactly last_time, so events sharing a millisecond are not copied twice.
      last_ids text[] NOT NULL DEFAULT '{}',
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    GRANT SELECT, INSERT, UPDATE ON keycloak_event_cursor TO platform_app;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE keycloak_event_cursor")
