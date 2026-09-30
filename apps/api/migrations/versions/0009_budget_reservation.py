"""Budget reservations (spec 13.5): the cost a call may reach, held while the call is in flight. The gateway decides
budgets under a per-tenant lock counting what was spent plus what is reserved, so calls made in parallel (a fan-out
of rule extraction) cannot all pass the check before any of them is recorded. A reservation is deleted when its call
ends; one left by a crashed process stops counting after 15 minutes.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-30
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE budget_reservation (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenant (id) ON DELETE CASCADE,
      project_id uuid,
      amount_usd numeric(18, 8) NOT NULL CHECK (amount_usd >= 0),
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX budget_reservation_tenant ON budget_reservation (tenant_id, created_at);
    ALTER TABLE budget_reservation ENABLE ROW LEVEL SECURITY;
    ALTER TABLE budget_reservation FORCE ROW LEVEL SECURITY;
    CREATE POLICY budget_reservation_owner ON budget_reservation TO platform_owner USING (true) WITH CHECK (true);
    CREATE POLICY budget_reservation_tenant ON budget_reservation TO platform_app
      USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant());
    GRANT SELECT, INSERT, DELETE ON budget_reservation TO platform_app;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE budget_reservation")
