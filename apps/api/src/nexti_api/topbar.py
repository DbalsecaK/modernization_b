"""The top bar (spec 18.1): the global search and the notifications of the active tenant.

- Search: projects by name and rules by key or name, only in projects the user may see (OpenFGA ListObjects; RLS
  keeps it to the tenant). Agents and skills come from the catalog the web already loads.
- Notifications: derived from data that already exists, newest first: the user's tasks (questions and gates),
  escalations, runs that finished or failed, new verdicts and, with cost.view, budget alerts. Nothing is stored; the
  web remembers per viewer when the list was last read."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import bindparam, text

from nexti_api.admin.common import transaction
from nexti_api.authz import names
from nexti_api.authz.require import Authorized, require_tenant
from nexti_api.runs.tasks import my_tasks
from nexti_api.schemas import ApiModel

router = APIRouter(prefix="/api/v1", tags=["topbar"])
TenantMember = Annotated[Authorized, Depends(require_tenant("tenant.view"))]
MAX_RESULTS = 8
MAX_NOTIFICATIONS = 30
RECENT = timedelta(days=7)


class SearchHit(ApiModel):
    kind: Literal["project", "rule"]
    id: str
    label: str
    hint: str
    project_id: uuid.UUID


class NotificationOut(ApiModel):
    id: str
    kind: Literal["question", "gate", "escalation", "runFinished", "runFailed", "verdict", "budget"]
    title: str
    project_id: uuid.UUID | None
    project_name: str | None
    tab: str | None
    occurred_at: datetime


async def _visible(request: Request, auth: Authorized) -> list[uuid.UUID]:
    objects = await request.app.state.fga.list_objects(names.user(auth.user_id), "viewer", "project")
    return [uuid.UUID(o.split(":", 1)[1]) for o in objects]


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@router.get("/search", response_model=list[SearchHit])
async def search(
    request: Request, auth: TenantMember, q: Annotated[str, Query(min_length=2, max_length=100)]
) -> list[SearchHit]:
    ids = await _visible(request, auth)
    if not ids:
        return []
    params = {"ids": ids, "q": _like(q.strip()), "n": MAX_RESULTS}
    async with transaction(request, auth) as conn:
        projects = (await conn.execute(
            text("SELECT id, name FROM project WHERE id IN :ids AND name ILIKE :q ESCAPE '\\' ORDER BY name LIMIT :n")
            .bindparams(bindparam("ids", expanding=True)), params)).mappings().all()  # fmt: skip
        rules = (await conn.execute(
            text("SELECT r.key, r.data->>'name' AS name, p.id AS project_id, p.name AS project_name FROM "
                 "(SELECT DISTINCT ON (project_id, key) project_id, key, status, data FROM spec_element "
                 "WHERE project_id IN :ids AND element_type = 'rule' ORDER BY project_id, key, version DESC) r "
                 "JOIN project p ON p.id = r.project_id WHERE r.status <> 'obsolete' "
                 "AND (r.key ILIKE :q ESCAPE '\\' OR r.data->>'name' ILIKE :q ESCAPE '\\') "
                 "ORDER BY p.name, r.key LIMIT :n")
            .bindparams(bindparam("ids", expanding=True)), params)).mappings().all()  # fmt: skip
    return [
        *(SearchHit(kind="project", id=str(p["id"]), label=p["name"], hint="", project_id=p["id"]) for p in projects),
        *(SearchHit(kind="rule", id=r["key"], label=f"{r['key']} · {r['name'] or ''}".rstrip(" ·"),
                    hint=r["project_name"], project_id=r["project_id"]) for r in rules),
    ]  # fmt: skip


async def _rows(conn: Any, sql: str, **params: Any) -> list[dict[str, Any]]:
    query = text(sql).bindparams(bindparam("ids", expanding=True))
    return [dict(r) for r in (await conn.execute(query, params)).mappings()]


@router.get("/notifications", response_model=list[NotificationOut])
async def notifications(request: Request, auth: TenantMember) -> list[NotificationOut]:
    assert auth.tenant_id is not None  # noqa: S101
    tasks = await my_tasks(request, auth)
    ids = await _visible(request, auth) or [uuid.UUID(int=0)]
    show_cost = await request.app.state.fga.check(names.user(auth.user_id), "cost_view", names.tenant(auth.tenant_id))
    since = datetime.now(UTC) - RECENT
    out = [
        NotificationOut(id=f"{t.kind}:{t.question_id or t.run_id}:{t.gate or ''}", kind=t.kind, title=t.title,
                        project_id=t.project_id, project_name=t.project_name,
                        tab="specification" if t.kind == "question" else "runs", occurred_at=t.created_at)
        for t in tasks
    ]  # fmt: skip
    async with transaction(request, auth) as conn:
        runs = await _rows(conn,
            "SELECT r.id, r.status, r.waiting_reason, r.current_phase, coalesce(r.finished_at, r.created_at) AS at, "
            "p.id AS project_id, p.name AS project_name FROM run r JOIN project p ON p.id = r.project_id "
            "WHERE r.project_id IN :ids AND ((r.status IN ('succeeded', 'failed') AND r.finished_at >= :since) "
            "OR (r.status = 'waiting' AND r.waiting_reason = 'escalation'))", ids=ids, since=since)  # fmt: skip
        verdicts = await _rows(conn,
            "SELECT v.id, v.module, v.verdict, v.created_at, p.id AS project_id, p.name AS project_name FROM verdict v "
            "JOIN project p ON p.id = v.project_id WHERE v.project_id IN :ids AND v.created_at >= :since",
            ids=ids, since=since)  # fmt: skip
        alerts = await _rows(conn,
            "SELECT a.id, a.level, a.triggered_at, p.id AS project_id, p.name AS project_name FROM budget_alert a "
            "JOIN budget b ON b.id = a.budget_id LEFT JOIN project p ON p.id = b.project_id "
            "WHERE a.triggered_at >= :since AND (b.project_id IS NULL OR b.project_id IN :ids)",
            ids=ids, since=since) if show_cost else []  # fmt: skip
    for r in runs:
        kind: Literal["escalation", "runFinished", "runFailed"] = (
            "escalation" if r["status"] == "waiting" else "runFinished" if r["status"] == "succeeded" else "runFailed"
        )
        out.append(NotificationOut(id=f"{kind}:{r['id']}", kind=kind, title=r["current_phase"] or "",
                                   project_id=r["project_id"], project_name=r["project_name"], tab="runs",
                                   occurred_at=r["at"]))  # fmt: skip
    out += [
        NotificationOut(id=f"verdict:{v['id']}", kind="verdict", title=f"{v['module']} · {v['verdict']}",
                        project_id=v["project_id"], project_name=v["project_name"], tab="validation",
                        occurred_at=v["created_at"])
        for v in verdicts
    ]  # fmt: skip
    out += [
        NotificationOut(id=f"budget:{a['id']}", kind="budget", title=f"{a['level']}%", project_id=a["project_id"],
                        project_name=a["project_name"], tab="costs" if a["project_id"] else None,
                        occurred_at=a["triggered_at"])
        for a in alerts
    ]  # fmt: skip
    return sorted(out, key=lambda n: n.occurred_at, reverse=True)[:MAX_NOTIFICATIONS]
