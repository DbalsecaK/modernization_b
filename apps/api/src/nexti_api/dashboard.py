"""The dashboard (spec 18.2) of the active tenant, by profile, from data that already exists:

- executive: progress per project, most recently active first (phases of its newest run), rules verified by the
  newest verdict, verdicts and spend against budget;
- delivery: runs in progress, gates waiting, escalations and today's consumption;
- administrator: active users, pending invitations, AI connections and budget alerts.

Only projects the user may see count (OpenFGA ListObjects; RLS keeps it to the tenant). Money needs cost.view and
the administrator section users.manage on the tenant; without them those parts come empty."""

import uuid
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import transaction
from nexti_api.authz import names
from nexti_api.authz.require import Authorized, require_tenant
from nexti_api.schemas import ApiModel
from nexti_api.spec.validation import _evidence

router = APIRouter(prefix="/api/v1", tags=["dashboard"])
TenantMember = Annotated[Authorized, Depends(require_tenant("tenant.view"))]
DONE_PHASES = ("succeeded", "skipped")
MONTHS = 6


class DashboardProject(ApiModel):
    id: uuid.UUID
    name: str
    run_status: str | None
    current_phase: str | None
    waiting_reason: str | None
    phases_done: int
    phases_total: int
    rules_total: int
    rules_verified: int
    verdict: str | None
    spent_usd: Decimal | None
    budget_usd: Decimal | None


class MonthSpend(ApiModel):
    month: str
    usd: Decimal


class Delivery(ApiModel):
    running: int
    gates_waiting: int
    escalations: int
    tokens_today: int
    cost_today_usd: Decimal | None


class ConnectionHealth(ApiModel):
    name: str
    provider: str
    status: str


class BudgetAlertOut(ApiModel):
    project_name: str | None
    level: int
    amount_usd: Decimal


class AdminSummary(ApiModel):
    active_users: int
    pending_invitations: int
    connections: list[ConnectionHealth]
    budget_alerts: list[BudgetAlertOut]


class DashboardOut(ApiModel):
    cost_visible: bool
    projects: list[DashboardProject]
    monthly_spend: list[MonthSpend]
    delivery: Delivery
    admin: AdminSummary | None


async def _can(request: Request, auth: Authorized, permission: str) -> bool:
    assert auth.tenant_id is not None  # noqa: S101
    user, tenant = names.user(auth.user_id), names.tenant(auth.tenant_id)
    return bool(await request.app.state.fga.check(user, names.relation(permission), tenant))


async def _rows(conn: AsyncConnection, sql: str, ids: list[uuid.UUID], **params: Any) -> list[dict[str, Any]]:
    query = text(sql).bindparams(bindparam("ids", expanding=True))
    return [dict(r) for r in (await conn.execute(query, {"ids": ids, **params})).mappings()]


async def _projects(
    request: Request, conn: AsyncConnection, ids: list[uuid.UUID], show_cost: bool
) -> list[DashboardProject]:
    projects = await _rows(conn, "SELECT id, name FROM project WHERE id IN :ids ORDER BY name", ids)
    runs = {r["project_id"]: r for r in await _rows(conn,
        "SELECT DISTINCT ON (project_id) id, project_id, status, current_phase, waiting_reason, created_at FROM run "
        "WHERE project_id IN :ids ORDER BY project_id, created_at DESC", ids)}  # fmt: skip
    phases = {r["run_id"]: r for r in await _rows(conn,
        "SELECT run_id, count(*) AS total, count(*) FILTER (WHERE status IN ('succeeded', 'skipped')) AS done "
        "FROM phase_run WHERE run_id IN (SELECT DISTINCT ON (project_id) id FROM run WHERE project_id IN :ids "
        "ORDER BY project_id, created_at DESC) GROUP BY run_id", ids)}  # fmt: skip
    rules = {r["project_id"]: r["total"] for r in await _rows(conn,
        "SELECT project_id, count(*) AS total FROM (SELECT DISTINCT ON (project_id, key) project_id, status "
        "FROM spec_element WHERE project_id IN :ids AND element_type = 'rule' ORDER BY project_id, key, version DESC) "
        "latest WHERE status <> 'obsolete' GROUP BY project_id", ids)}  # fmt: skip
    verdicts = {r["project_id"]: r["verdict"] for r in await _rows(conn,
        "SELECT DISTINCT ON (project_id) project_id, verdict FROM verdict WHERE project_id IN :ids "
        "AND module NOT LIKE 'frontend-%' ORDER BY project_id, created_at DESC", ids)}  # fmt: skip
    spent = {r["project_id"]: r["usd"] for r in await _rows(conn,
        "SELECT project_id, sum(cost_usd) AS usd FROM usage_ledger WHERE project_id IN :ids GROUP BY project_id",
        ids)}  # fmt: skip
    budgets = {r["project_id"]: r["usd"] for r in await _rows(conn,
        "SELECT project_id, sum(amount_usd) AS usd FROM budget WHERE project_id IN :ids GROUP BY project_id",
        ids)}  # fmt: skip
    # Most recently active first; projects that never ran go last, by name.
    epoch = datetime.min.replace(tzinfo=UTC)
    projects.sort(key=lambda p: runs[p["id"]]["created_at"] if p["id"] in runs else epoch, reverse=True)
    out = []
    for p in projects:
        run = runs.get(p["id"])
        counted = phases.get(run["id"]) if run else None
        trace = (await _evidence(request, conn, p["id"])).get("trace", {}) if p["id"] in verdicts else {}
        out.append(DashboardProject(
            id=p["id"], name=p["name"],
            run_status=run["status"] if run else None, current_phase=run["current_phase"] if run else None,
            waiting_reason=run["waiting_reason"] if run else None,
            phases_done=counted["done"] if counted else 0, phases_total=counted["total"] if counted else 0,
            rules_total=rules.get(p["id"], 0), rules_verified=sum(1 for t in trace.values() if t.get("verified")),
            verdict=verdicts.get(p["id"]),
            spent_usd=spent.get(p["id"], Decimal(0)) if show_cost else None,
            budget_usd=budgets.get(p["id"]) if show_cost else None,
        ))  # fmt: skip
    return out


async def _delivery(conn: AsyncConnection, ids: list[uuid.UUID], show_cost: bool) -> Delivery:
    (counts,) = await _rows(conn,
        "SELECT count(*) FILTER (WHERE status = 'running') AS running, "
        "count(*) FILTER (WHERE status = 'waiting' AND waiting_reason = 'escalation') AS escalations "
        "FROM run WHERE project_id IN :ids", ids)  # fmt: skip
    (gates,) = await _rows(conn,
        "SELECT count(*) AS waiting FROM gate JOIN run ON run.id = gate.run_id "
        "WHERE run.project_id IN :ids AND gate.status = 'pending' AND run.status = 'waiting'", ids)  # fmt: skip
    today = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    (used,) = await _rows(conn,
        "SELECT coalesce(sum(input_tokens + output_tokens), 0) AS tokens, coalesce(sum(cost_usd), 0) AS usd "
        "FROM usage_ledger WHERE project_id IN :ids AND occurred_at >= :today", ids, today=today)  # fmt: skip
    return Delivery(running=counts["running"], gates_waiting=gates["waiting"], escalations=counts["escalations"],
                    tokens_today=used["tokens"], cost_today_usd=used["usd"] if show_cost else None)  # fmt: skip


async def _monthly(conn: AsyncConnection) -> list[MonthSpend]:
    rows = await conn.execute(text(
        "SELECT to_char(occurred_at, 'YYYY-MM') AS month, sum(cost_usd) AS usd FROM usage_ledger "
        "WHERE occurred_at >= date_trunc('month', now()) - make_interval(months => :back) "
        "GROUP BY 1 ORDER BY 1"), {"back": MONTHS - 1})  # fmt: skip
    return [MonthSpend(month=r.month, usd=r.usd) for r in rows]


async def _admin(conn: AsyncConnection) -> AdminSummary:
    users: int = (await conn.execute(text("SELECT count(*) FROM membership WHERE status = 'active'"))).scalar_one()
    invited: int = (await conn.execute(text("SELECT count(*) FROM invitation WHERE status = 'pending'"))).scalar_one()
    connections = [ConnectionHealth(name=r.name, provider=r.provider, status=r.status) for r in await conn.execute(
        text("SELECT name, provider, status FROM provider_connection ORDER BY name"))]  # fmt: skip
    alerts = [BudgetAlertOut(project_name=r.project_name, level=r.level, amount_usd=r.amount_usd) for r in
              await conn.execute(text(
                  "SELECT DISTINCT ON (b.id) p.name AS project_name, a.level, b.amount_usd FROM budget_alert a "
                  "JOIN budget b ON b.id = a.budget_id LEFT JOIN project p ON p.id = b.project_id "
                  "ORDER BY b.id, a.level DESC"))]  # fmt: skip
    return AdminSummary(active_users=users, pending_invitations=invited, connections=connections, budget_alerts=alerts)


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(request: Request, auth: TenantMember) -> DashboardOut:
    visible = await request.app.state.fga.list_objects(names.user(auth.user_id), "viewer", "project")
    ids = [uuid.UUID(obj.split(":", 1)[1]) for obj in visible] or [uuid.UUID(int=0)]
    show_cost = await _can(request, auth, "cost.view")
    manage_users = await _can(request, auth, "users.manage")
    async with transaction(request, auth) as conn:
        projects = await _projects(request, conn, ids, show_cost)
        delivery = await _delivery(conn, ids, show_cost)
        monthly = await _monthly(conn) if show_cost else []
        admin = await _admin(conn) if manage_users else None
    return DashboardOut(cost_visible=show_cost, projects=projects, monthly_spend=monthly, delivery=delivery,
                        admin=admin)  # fmt: skip
