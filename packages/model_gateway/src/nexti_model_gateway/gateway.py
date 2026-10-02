"""The model gateway: the only path from the platform to a model (spec 12.7, rule 2).

For every call it resolves the profile through the cascade, checks the tenant policy and the budget, pins the
offering, applies the effort, retries and falls back, and records the call in the usage ledger (spec 13).

The database is read in one transaction, the provider is called outside any transaction, and the result is
recorded in another, so a slow model never holds a database connection.
"""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from nexti_core.audit import AuditEvent, record
from nexti_core.db.models import (
    Budget,
    BudgetAlert,
    BudgetReservation,
    EffortMapping,
    ModelAssignment,
    ModelOffering,
    ModelPolicy,
    ModelProfile,
    ModelVersion,
    PriceVersion,
    ProviderConnection,
    UsageLedger,
)
from nexti_core.db.session import DbScope, scoped_connection
from nexti_model_gateway.openrouter import (
    ChatResult,
    ChatUsage,
    OpenAICompatibleClient,
    OpenRouterClient,
    Pricing,
    ProviderError,
)
from nexti_model_gateway.rules import (
    OPENAI_COMPATIBLE,
    AssignmentRow,
    OfferingFacts,
    Policy,
    cost_usd,
    crossed_levels,
    period_key,
    period_start,
    policy_denial,
    resolve_profile,
    routing,
)
from nexti_model_gateway.secrets import SecretStore

MAX_FALLBACK_DEPTH = 5


class GatewayError(Exception):
    code = "gateway_error"


class NoProfileError(GatewayError):
    code = "no_profile"


class PolicyDeniedError(GatewayError):
    code = "policy_denied"


class BudgetExceededError(GatewayError):
    """The budget is exhausted: the orchestrator pauses the run at its checkpoint (spec 13.5, M3)."""

    code = "budget_exceeded"

    def __init__(self, budget_id: uuid.UUID, spent: Decimal, amount: Decimal) -> None:
        super().__init__(f"budget {budget_id} exhausted: {spent} of {amount} USD")
        self.budget_id = budget_id
        self.spent = spent
        self.amount = amount


class ProviderCallError(GatewayError):
    code = "provider_failed"


@dataclass(frozen=True)
class CallContext:
    """Who is calling and for what: the labels of the usage ledger (spec 13.1)."""

    tenant_id: uuid.UUID
    project_id: uuid.UUID | None = None
    phase: str | None = None
    agent_role: str | None = None
    run_id: str | None = None
    iteration: int | None = None


@dataclass(frozen=True)
class Completion:
    content: str
    usage: ChatUsage
    cost_usd: Decimal
    provider_cost_usd: Decimal | None
    profile_id: uuid.UUID
    offering_id: uuid.UUID
    was_fallback: bool
    request_id: str | None
    model: str = ""  # the model slug that answered


@dataclass(frozen=True)
class _Plan:
    """Everything needed to call one profile, read in one transaction."""

    profile_id: uuid.UUID
    connection_id: uuid.UUID
    vault_path: str | None
    offering_id: uuid.UUID
    model: str
    offering: OfferingFacts
    price_id: uuid.UUID | None
    price: Pricing | None
    effort_parameters: dict[str, Any]
    max_output_tokens: int
    temperature: Decimal | None
    timeout_seconds: int
    max_retries: int
    provider: str = "openrouter"  # the connection's provider
    base_url: str | None = None  # openai-compatible: the server's base URL (ADR-0030)


RESERVATION_TTL = timedelta(minutes=15)  # a reservation left by a crashed process stops counting after this


def max_cost(chain: "list[_Plan]", messages: list[dict[str, Any]]) -> Decimal:
    """The most a call may cost with the profiles of its chain: its input (about three characters per token) and
    the whole output allowance, at the tariff in force."""
    input_tokens = Decimal(sum(len(str(m.get("content", ""))) for m in messages)) / 3
    costs = [
        (input_tokens * p.price.input_per_mtok + Decimal(p.max_output_tokens) * p.price.output_per_mtok) / 1_000_000
        for p in chain
        if p.price is not None
    ]
    return max(costs, default=Decimal(0)).quantize(Decimal("0.00000001"))


@dataclass(frozen=True)
class _BudgetState:
    budget_id: uuid.UUID
    amount: Decimal
    alert_pct: int
    hard_stop: bool
    period: str
    spent: Decimal
    reserved: Decimal = Decimal(0)  # what calls in flight may still spend


@dataclass
class _Attempt:
    plan: _Plan
    outcome: str
    error_code: str | None = None
    result: ChatResult | None = None
    retries: int = 0
    latency_ms: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


Sleep = Callable[[float], Awaitable[None]]


class ModelGateway:
    def __init__(
        self,
        engine: AsyncEngine,
        secrets: SecretStore,
        client: OpenRouterClient,
        *,
        sleep: Sleep = asyncio.sleep,
        backoff_seconds: float = 0.5,
        openrouter_enabled: bool = True,
    ) -> None:
        """`openrouter_enabled` False (air-gapped profile, ADR-0030): OpenRouter offerings are blocked."""
        self.engine = engine
        self.secrets = secrets
        self.client = client
        self.sleep = sleep
        self.backoff_seconds = backoff_seconds
        self.openrouter_enabled = openrouter_enabled

    # --- configuration -------------------------------------------------------------------------------------

    async def _policy(self, conn: AsyncConnection) -> Policy:
        row = (await conn.execute(select(ModelPolicy))).first()
        if row is None:
            return Policy()
        return Policy(
            openrouter_allowed=row.openrouter_allowed,
            allowed_upstream_providers=tuple(row.allowed_upstream_providers)
            if row.allowed_upstream_providers is not None
            else None,
            denied_upstream_providers=tuple(row.denied_upstream_providers),
            require_zdr=row.require_zdr,
            deny_data_collection=row.deny_data_collection,
        )

    async def _plan(self, conn: AsyncConnection, profile_id: uuid.UUID) -> tuple[_Plan, uuid.UUID | None]:
        row = (
            await conn.execute(
                select(
                    ModelProfile.id,
                    ModelProfile.effort,
                    ModelProfile.max_output_tokens,
                    ModelProfile.temperature,
                    ModelProfile.timeout_seconds,
                    ModelProfile.max_retries,
                    ModelProfile.fallback_profile_id,
                    ProviderConnection.id.label("connection_id"),
                    ProviderConnection.vault_path,
                    ProviderConnection.provider.label("connection_provider"),
                    ProviderConnection.base_url,
                    ModelOffering.id.label("offering_id"),
                    ModelOffering.provider,
                    ModelOffering.upstream_provider,
                    ModelOffering.zdr,
                    ModelVersion.provider_slug,
                )
                .join(ProviderConnection, ProviderConnection.id == ModelProfile.connection_id)
                .join(ModelOffering, ModelOffering.id == ModelProfile.offering_id)
                .join(ModelVersion, ModelVersion.id == ModelOffering.version_id)
                .where(ModelProfile.id == profile_id)
            )
        ).one_or_none()
        if row is None:
            raise NoProfileError("the model profile does not exist in this tenant")
        price = (
            await conn.execute(
                select(PriceVersion).where(PriceVersion.offering_id == row.offering_id, PriceVersion.valid_to.is_(None))
            )
        ).first()
        effort = (
            await conn.execute(
                select(EffortMapping.parameters).where(
                    EffortMapping.offering_id == row.offering_id, EffortMapping.effort == row.effort
                )
            )
        ).scalar_one_or_none()
        plan = _Plan(
            profile_id=row.id,
            connection_id=row.connection_id,
            vault_path=row.vault_path,
            offering_id=row.offering_id,
            model=row.provider_slug,
            offering=OfferingFacts(row.provider, row.upstream_provider, row.zdr),
            price_id=price.id if price else None,
            price=Pricing(
                price.input_per_mtok,
                price.output_per_mtok,
                price.cache_read_per_mtok,
                price.cache_write_per_mtok,
                price.request_usd,
            )
            if price
            else None,
            effort_parameters=dict(effort or {}),
            max_output_tokens=row.max_output_tokens,
            temperature=row.temperature,
            timeout_seconds=row.timeout_seconds,
            max_retries=row.max_retries,
            provider=row.connection_provider,
            base_url=row.base_url,
        )
        return plan, row.fallback_profile_id

    async def _budgets(self, conn: AsyncConnection, ctx: CallContext, now: datetime) -> list[_BudgetState]:
        query = select(Budget)
        query = (
            query.where((Budget.project_id.is_(None)) | (Budget.project_id == ctx.project_id))
            if ctx.project_id
            else query.where(Budget.project_id.is_(None))
        )
        states = []
        for b in (await conn.execute(query)).all():
            spent_query = select(func.coalesce(func.sum(UsageLedger.cost_usd), 0))
            if b.project_id is not None:
                spent_query = spent_query.where(UsageLedger.project_id == b.project_id)
            start = period_start(b.period, now)
            if start is not None:
                spent_query = spent_query.where(UsageLedger.occurred_at >= start)
            spent = Decimal((await conn.execute(spent_query)).scalar_one())
            reserved_query = select(func.coalesce(func.sum(BudgetReservation.amount_usd), 0)).where(
                BudgetReservation.created_at >= now - RESERVATION_TTL
            )
            if b.project_id is not None:
                reserved_query = reserved_query.where(BudgetReservation.project_id == b.project_id)
            reserved = Decimal((await conn.execute(reserved_query)).scalar_one())
            states.append(_BudgetState(b.id, b.amount_usd, b.alert_pct, b.hard_stop, b.period, spent, reserved))
        return states

    # --- ledger ---------------------------------------------------------------------------------------------

    async def _record(self, ctx: CallContext, attempts: list[_Attempt], *, blocked_budget: bool = False) -> None:
        now = datetime.now(UTC)
        async with scoped_connection(self.engine, DbScope(tenant_id=ctx.tenant_id)) as conn:
            for index, a in enumerate(attempts):
                usage = a.result.usage if a.result else ChatUsage()
                cost = cost_usd(usage, a.plan.price) if a.result and a.plan.price else Decimal(0)
                await conn.execute(
                    insert(UsageLedger).values(
                        tenant_id=ctx.tenant_id,
                        project_id=ctx.project_id,
                        run_id=ctx.run_id,
                        phase=ctx.phase,
                        agent_role=ctx.agent_role,
                        iteration=ctx.iteration,
                        profile_id=a.plan.profile_id,
                        connection_id=a.plan.connection_id,
                        offering_id=a.plan.offering_id,
                        price_version_id=a.plan.price_id,
                        model=a.plan.model,
                        upstream_provider=a.plan.offering.upstream_provider,
                        provider_request_id=a.result.request_id if a.result else None,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        reasoning_tokens=usage.reasoning_tokens,
                        cache_read_tokens=usage.cache_read_tokens,
                        cache_write_tokens=usage.cache_write_tokens,
                        latency_ms=a.latency_ms,
                        retries=a.retries,
                        was_fallback=index > 0,
                        outcome=a.outcome,
                        error_code=a.error_code,
                        cost_usd=cost,
                        provider_cost_usd=usage.provider_cost_usd,
                    )
                )
                if a.outcome == "blocked" and a.error_code and a.error_code.startswith("policy:"):
                    await record(
                        conn,
                        AuditEvent(
                            action="ai.call_blocked",
                            outcome="denied",
                            actor_kind="system",
                            actor_label="model-gateway",
                            tenant_id=ctx.tenant_id,
                            target=f"profile:{a.plan.profile_id}",
                            details={"reason": a.error_code, "upstream_provider": a.plan.offering.upstream_provider},
                        ),
                    )
            if not blocked_budget:
                await self._alerts(conn, ctx, now)

    async def _alerts(self, conn: AsyncConnection, ctx: CallContext, now: datetime) -> None:
        """Record each alert level once per budget and period, and audit it (spec 13.5)."""
        for b in await self._budgets(conn, ctx, now):
            for level in crossed_levels(b.spent, b.amount, b.alert_pct):
                key = period_key(b.period, now)
                inserted = (
                    await conn.execute(
                        pg_insert(BudgetAlert)
                        .values(
                            tenant_id=ctx.tenant_id,
                            budget_id=b.budget_id,
                            level=level,
                            period_key=key,
                            spent_usd=b.spent,
                        )
                        .on_conflict_do_nothing()
                        .returning(BudgetAlert.id)
                    )
                ).first()
                if inserted:
                    await record(
                        conn,
                        AuditEvent(
                            action="budget.alert",
                            outcome="success",
                            actor_kind="system",
                            actor_label="model-gateway",
                            tenant_id=ctx.tenant_id,
                            target=f"budget:{b.budget_id}",
                            details={
                                "level": level,
                                "spent_usd": str(b.spent),
                                "amount_usd": str(b.amount),
                                "period": key,
                            },
                        ),
                    )

    # --- the call -------------------------------------------------------------------------------------------

    def _body(
        self, plan: _Plan, policy: Policy, messages: list[dict[str, Any]], extra: dict[str, Any]
    ) -> dict[str, Any]:
        # OpenRouter-only fields (usage accounting, provider routing) are not sent to an openai-compatible server.
        openrouter: dict[str, Any] = (
            {"usage": {"include": True}, "provider": routing(policy, plan.offering)}
            if plan.provider != OPENAI_COMPATIBLE
            else {}
        )
        body: dict[str, Any] = {
            "model": plan.model,
            "messages": messages,
            "max_tokens": plan.max_output_tokens,
            **openrouter,
            **plan.effort_parameters,
            **extra,
        }
        if plan.temperature is not None:
            body["temperature"] = float(plan.temperature)
        return body

    async def _call(
        self, plan: _Plan, policy: Policy, messages: list[dict[str, Any]], extra: dict[str, Any]
    ) -> _Attempt:
        api_key = await self.secrets.get(plan.vault_path) if plan.vault_path else None
        local = plan.provider == OPENAI_COMPATIBLE
        if local and not plan.base_url:
            return _Attempt(plan, "error", "missing_base_url")
        # The API key of an openai-compatible server is optional (a local vLLM or Ollama often has none).
        if not api_key and not local:
            return _Attempt(plan, "error", "missing_credential")
        client = OpenAICompatibleClient(self.client.http, plan.base_url or "") if local else self.client
        body = self._body(plan, policy, messages, extra)
        attempt = _Attempt(plan, "error")
        for retry in range(plan.max_retries + 1):
            started = time.perf_counter()
            try:
                result = await client.chat(api_key, body, plan.timeout_seconds)
            except ProviderError as exc:
                attempt.latency_ms += int((time.perf_counter() - started) * 1000)
                attempt.error_code = f"provider:{exc.status}"
                attempt.retries = retry
                if not exc.retryable or retry == plan.max_retries:
                    return attempt
                await self.sleep(min(self.backoff_seconds * (2**retry), 8.0))
                continue
            attempt.latency_ms += int((time.perf_counter() - started) * 1000)
            attempt.retries = retry
            attempt.outcome = "success"
            attempt.error_code = None
            attempt.result = result
            return attempt
        return attempt

    async def complete(
        self,
        ctx: CallContext,
        messages: list[dict[str, Any]],
        *,
        profile_id: uuid.UUID | None = None,
        **extra: Any,
    ) -> Completion:
        """Call the model assigned to the context. Raises BudgetExceededError, PolicyDeniedError, NoProfileError
        or ProviderCallError; every attempt (including blocked ones) is in the usage ledger."""
        now = datetime.now(UTC)
        async with scoped_connection(self.engine, DbScope(tenant_id=ctx.tenant_id)) as conn:
            rows = (
                await conn.execute(
                    select(
                        ModelAssignment.project_id,
                        ModelAssignment.phase,
                        ModelAssignment.agent_role,
                        ModelAssignment.profile_id,
                    )
                )
            ).all()
            # An explicit profile (e.g. "test profile") skips the cascade; RLS still limits it to the tenant.
            profile_id = profile_id or resolve_profile(
                [AssignmentRow(r.project_id, r.phase, r.agent_role, r.profile_id) for r in rows],
                ctx.project_id,
                ctx.phase,
                ctx.agent_role,
            )
            if profile_id is None:
                raise NoProfileError("no model profile is assigned for this context")
            chain: list[_Plan] = []
            next_id: uuid.UUID | None = profile_id
            while (
                next_id is not None and len(chain) < MAX_FALLBACK_DEPTH and next_id not in {p.profile_id for p in chain}
            ):
                plan, next_id = await self._plan(conn, next_id)
                chain.append(plan)
            policy = await self._policy(conn)
            # Budgets are decided one call at a time per tenant (also across worker processes), counting what the
            # calls in flight may still spend: parallel calls cannot all pass before any of them is recorded.
            await conn.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(str(ctx.tenant_id), 0))))
            budgets = await self._budgets(conn, ctx, now)
            exhausted = next((b for b in budgets if b.hard_stop and b.spent + b.reserved >= b.amount), None)
            reservation: uuid.UUID | None = None
            if exhausted is None and budgets:
                reservation = (
                    await conn.execute(
                        insert(BudgetReservation)
                        .values(
                            tenant_id=ctx.tenant_id, project_id=ctx.project_id, amount_usd=max_cost(chain, messages)
                        )
                        .returning(BudgetReservation.id)
                    )
                ).scalar_one()

        if exhausted is not None:
            await self._record(ctx, [_Attempt(chain[0], "blocked", "budget_exceeded")], blocked_budget=True)
            raise BudgetExceededError(exhausted.budget_id, exhausted.spent + exhausted.reserved, exhausted.amount)
        try:
            return await self._attempts(ctx, chain, policy, messages, extra)
        finally:
            if reservation is not None:
                async with scoped_connection(self.engine, DbScope(tenant_id=ctx.tenant_id)) as conn:
                    await conn.execute(delete(BudgetReservation).where(BudgetReservation.id == reservation))

    async def _attempts(
        self, ctx: CallContext, chain: list[_Plan], policy: Policy, messages: list[dict[str, Any]],
        extra: dict[str, Any],
    ) -> Completion:  # fmt: skip

        attempts: list[_Attempt] = []
        for plan in chain:
            denial = policy_denial(policy, plan.offering)
            if denial is None and plan.offering.provider == "openrouter" and not self.openrouter_enabled:
                denial = "openrouter_disabled"
            if denial is not None:
                attempts.append(_Attempt(plan, "blocked", f"policy:{denial}"))
                continue
            attempt = await self._call(plan, policy, messages, extra)
            attempts.append(attempt)
            if attempt.outcome == "success" and attempt.result is not None:
                await self._record(ctx, attempts)
                usage = attempt.result.usage
                return Completion(
                    content=attempt.result.content,
                    usage=usage,
                    cost_usd=cost_usd(usage, plan.price) if plan.price else Decimal(0),
                    provider_cost_usd=usage.provider_cost_usd,
                    profile_id=plan.profile_id,
                    offering_id=plan.offering_id,
                    was_fallback=len(attempts) > 1,
                    request_id=attempt.result.request_id,
                    model=plan.model,
                )
        await self._record(ctx, attempts)
        if all(a.outcome == "blocked" for a in attempts):
            raise PolicyDeniedError(", ".join(sorted({a.error_code or "" for a in attempts})))
        raise ProviderCallError(", ".join(a.error_code or "unknown" for a in attempts))
