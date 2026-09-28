"""Usage and costs (spec 13.5): summaries from the usage ledger and budgets with their alerts.

Tokens need usage.view; money needs cost.view as well (spec 13.5: separate permissions).
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy import Text, cast, delete, func, insert, literal, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz import names
from nexti_api.authz.require import Authorized, require_tenant
from nexti_api.errors import ProblemError
from nexti_api.schemas import ApiModel
from nexti_core.db.models import Budget, BudgetAlert, Project, UsageLedger
from nexti_model_gateway.rules import period_key, period_start

router = APIRouter(prefix="/api/v1", tags=["usage"])
UsageView = Annotated[Authorized, Depends(require_tenant("usage.view"))]
CostView = Annotated[Authorized, Depends(require_tenant("cost.view"))]
ConfigureModels = Annotated[Authorized, Depends(require_tenant("models.configure"))]
GroupBy = Literal["project", "model", "phase", "agentRole", "provider", "month", "day"]


class UsageRow(ApiModel):
    key: str | None
    label: str
    calls: int
    failed_calls: int
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cache_read_tokens: int
    # Only with cost.view; null otherwise.
    cost_usd: Decimal | None
    provider_cost_usd: Decimal | None


class UsageSummary(ApiModel):
    since: date
    until: date
    group_by: GroupBy
    cost_visible: bool
    total: UsageRow
    rows: list[UsageRow]


class BudgetOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    project_name: str | None
    period: Literal["monthly", "total"]
    amount_usd: Decimal
    alert_pct: int
    hard_stop: bool
    spent_usd: Decimal
    period_key: str
    alerts: list[int]


class BudgetIn(ApiModel):
    project_id: uuid.UUID | None = None
    period: Literal["monthly", "total"] = "monthly"
    amount_usd: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    alert_pct: int = Field(default=80, ge=1, le=99)
    hard_stop: bool = True


async def _cost_visible(request: Request, auth: Authorized) -> bool:
    assert auth.tenant_id is not None  # noqa: S101
    return bool(await request.app.state.fga.check(names.user(auth.user_id), "cost_view", names.tenant(auth.tenant_id)))


@router.get("/usage/summary", response_model=UsageSummary)
async def summary(
    request: Request,
    auth: UsageView,
    group_by: Annotated[GroupBy, Query(alias="groupBy")] = "model",
    since: date | None = None,
    until: date | None = None,
) -> UsageSummary:
    today = datetime.now(UTC).date()
    until = until or today
    since = since or until.replace(day=1)
    start = datetime.combine(since, time.min, tzinfo=UTC)
    end = datetime.combine(until + timedelta(days=1), time.min, tzinfo=UTC)
    show_cost = await _cost_visible(request, auth)

    key_columns = {
        "project": (cast(UsageLedger.project_id, Text), func.coalesce(Project.name, "—")),
        "model": (UsageLedger.model, func.coalesce(UsageLedger.model, "—")),
        "phase": (UsageLedger.phase, func.coalesce(UsageLedger.phase, "—")),
        "agentRole": (UsageLedger.agent_role, func.coalesce(UsageLedger.agent_role, "—")),
        "provider": (UsageLedger.upstream_provider, func.coalesce(UsageLedger.upstream_provider, "—")),
        "month": (func.to_char(UsageLedger.occurred_at, "YYYY-MM"), func.to_char(UsageLedger.occurred_at, "YYYY-MM")),
        "day": (
            func.to_char(UsageLedger.occurred_at, "YYYY-MM-DD"),
            func.to_char(UsageLedger.occurred_at, "YYYY-MM-DD"),
        ),
    }
    key, label = key_columns[group_by]
    measures = (
        func.count().filter(UsageLedger.outcome == "success").label("calls"),
        func.count().filter(UsageLedger.outcome != "success").label("failed_calls"),
        func.coalesce(func.sum(UsageLedger.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(UsageLedger.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(UsageLedger.reasoning_tokens), 0).label("reasoning_tokens"),
        func.coalesce(func.sum(UsageLedger.cache_read_tokens), 0).label("cache_read_tokens"),
        func.coalesce(func.sum(UsageLedger.cost_usd), 0).label("cost_usd"),
        func.sum(UsageLedger.provider_cost_usd).label("provider_cost_usd"),
    )
    window = (UsageLedger.occurred_at >= start, UsageLedger.occurred_at < end)
    async with transaction(request, auth) as conn:
        grouped = (
            select(key.label("key"), label.label("label"), *measures)
            .outerjoin(Project, Project.id == UsageLedger.project_id)
            .where(*window)
            .group_by(key, label)
            .order_by(func.sum(UsageLedger.cost_usd).desc(), label)
        )
        rows = (await conn.execute(grouped)).all()
        total = (
            await conn.execute(
                select(literal(None).label("key"), literal("total").label("label"), *measures).where(*window)
            )
        ).one()

    def out(r: Any) -> UsageRow:
        return UsageRow(
            key=r.key,
            label=r.label,
            calls=r.calls,
            failed_calls=r.failed_calls,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            reasoning_tokens=r.reasoning_tokens,
            cache_read_tokens=r.cache_read_tokens,
            cost_usd=r.cost_usd if show_cost else None,
            provider_cost_usd=r.provider_cost_usd if show_cost else None,
        )

    return UsageSummary(
        since=since,
        until=until,
        group_by=group_by,
        cost_visible=show_cost,
        total=out(total),
        rows=[out(r) for r in rows],
    )


async def _budgets(conn: AsyncConnection, budget_id: uuid.UUID | None = None) -> list[BudgetOut]:
    now = datetime.now(UTC)
    query = select(Budget, Project.name.label("project_name")).outerjoin(Project, Project.id == Budget.project_id)
    if budget_id is not None:
        query = query.where(Budget.id == budget_id)
    out = []
    for row in (await conn.execute(query.order_by(Budget.created_at))).all():
        b = row
        spent_query = select(func.coalesce(func.sum(UsageLedger.cost_usd), 0))
        if b.project_id is not None:
            spent_query = spent_query.where(UsageLedger.project_id == b.project_id)
        start = period_start(b.period, now)
        if start is not None:
            spent_query = spent_query.where(UsageLedger.occurred_at >= start)
        key = period_key(b.period, now)
        alerts = (
            (
                await conn.execute(
                    select(BudgetAlert.level).where(BudgetAlert.budget_id == b.id, BudgetAlert.period_key == key)
                )
            )
            .scalars()
            .all()
        )
        out.append(
            BudgetOut(
                id=b.id,
                project_id=b.project_id,
                project_name=row.project_name,
                period=b.period,
                amount_usd=b.amount_usd,
                alert_pct=b.alert_pct,
                hard_stop=b.hard_stop,
                spent_usd=Decimal((await conn.execute(spent_query)).scalar_one()),
                period_key=key,
                alerts=sorted(alerts),
            )
        )
    return out


@router.get("/budgets", response_model=list[BudgetOut])
async def list_budgets(request: Request, auth: CostView) -> list[BudgetOut]:
    async with transaction(request, auth) as conn:
        return await _budgets(conn)


@router.post("/budgets", response_model=BudgetOut, status_code=201)
async def create_budget(request: Request, body: BudgetIn, auth: ConfigureModels) -> BudgetOut:
    try:
        async with transaction(request, auth) as conn:
            if (
                body.project_id
                and (await conn.execute(select(Project.id).where(Project.id == body.project_id))).first() is None
            ):
                raise not_found("project")
            budget_id = (
                await conn.execute(
                    insert(Budget)
                    .values(tenant_id=auth.tenant_id, created_by=auth.user_id, **body.model_dump(by_alias=False))
                    .returning(Budget.id)
                )
            ).scalar_one()
            await audit(conn, auth, "budget.create", f"budget:{budget_id}", body.model_dump(mode="json"))
            return (await _budgets(conn, budget_id))[0]
    except IntegrityError as exc:
        raise ProblemError(409, "budget_exists", "A budget for that scope and period already exists.") from exc


@router.put("/budgets/{budget_id}", response_model=BudgetOut)
async def update_budget(request: Request, budget_id: uuid.UUID, body: BudgetIn, auth: ConfigureModels) -> BudgetOut:
    async with transaction(request, auth) as conn:
        values = body.model_dump(by_alias=False, exclude={"project_id"})
        result = await conn.execute(update(Budget).where(Budget.id == budget_id).values(**values))
        if result.rowcount == 0:
            raise not_found("budget")
        await audit(conn, auth, "budget.update", f"budget:{budget_id}", body.model_dump(mode="json"))
        return (await _budgets(conn, budget_id))[0]


@router.delete("/budgets/{budget_id}", status_code=204)
async def delete_budget(request: Request, budget_id: uuid.UUID, auth: ConfigureModels) -> None:
    async with transaction(request, auth) as conn:
        result = await conn.execute(delete(Budget).where(Budget.id == budget_id))
        if result.rowcount == 0:
            raise not_found("budget")
        await audit(conn, auth, "budget.delete", f"budget:{budget_id}")
