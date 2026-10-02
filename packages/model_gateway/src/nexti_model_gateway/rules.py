"""Pure rules of the gateway (no I/O): cost, tenant policy, cascade of assignments, budget periods."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from nexti_model_gateway.openrouter import ChatUsage, Pricing

MTOK = Decimal(1_000_000)
# A server with the OpenAI chat API at the connection's own base URL (vLLM, Ollama; ADR-0030).
OPENAI_COMPATIBLE = "openai-compatible"
PROVIDERS = ("openrouter", OPENAI_COMPATIBLE)
USD = Decimal("0.00000001")


def cost_usd(usage: ChatUsage, price: Pricing) -> Decimal:
    """Cost of a call with the tariff in force (spec 13.3). Cached input is billed at the cache price; the prompt
    count from OpenRouter includes the cached tokens. Reasoning tokens are part of the output count."""
    cached = usage.cache_read_tokens
    written = usage.cache_write_tokens
    plain_input = max(usage.input_tokens - cached - written, 0)
    read_price = price.cache_read_per_mtok if price.cache_read_per_mtok is not None else price.input_per_mtok
    write_price = price.cache_write_per_mtok if price.cache_write_per_mtok is not None else price.input_per_mtok
    total = (
        Decimal(plain_input) * price.input_per_mtok
        + Decimal(cached) * read_price
        + Decimal(written) * write_price
        + Decimal(usage.output_tokens) * price.output_per_mtok
    ) / MTOK
    if price.request_usd:
        total += price.request_usd
    return total.quantize(USD, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Policy:
    """Tenant policy for model use (spec 12.6). Defaults apply when the tenant has not configured one."""

    openrouter_allowed: bool = True
    allowed_upstream_providers: tuple[str, ...] | None = None
    denied_upstream_providers: tuple[str, ...] = ()
    require_zdr: bool = False
    deny_data_collection: bool = True


@dataclass(frozen=True)
class OfferingFacts:
    provider: str
    upstream_provider: str
    zdr: bool


def _provider_family(tag: str) -> str:
    """OpenRouter tags can carry a region ("azure/swedencentral"); policies name the provider ("azure")."""
    return tag.split("/", 1)[0]


def policy_denial(policy: Policy, offering: OfferingFacts) -> str | None:
    """None if the offering may be used; otherwise a stable reason code."""
    if offering.provider == "openrouter" and not policy.openrouter_allowed:
        return "provider_not_allowed"
    if offering.provider == OPENAI_COMPATIBLE:
        # The tenant's own server (ADR-0030): the upstream lists name OpenRouter's providers and do not apply.
        return "zdr_required" if policy.require_zdr and not offering.zdr else None
    upstream = _provider_family(offering.upstream_provider)
    if upstream in policy.denied_upstream_providers or offering.upstream_provider in policy.denied_upstream_providers:
        return "upstream_provider_denied"
    allowed = policy.allowed_upstream_providers
    if allowed is not None and upstream not in allowed and offering.upstream_provider not in allowed:
        return "upstream_provider_not_allowed"
    if policy.require_zdr and not offering.zdr:
        return "zdr_required"
    return None


def routing(policy: Policy, offering: OfferingFacts) -> dict[str, Any]:
    """OpenRouter `provider` preferences: pinned upstream, no silent fallback, data collection and ZDR."""
    prefs: dict[str, Any] = {"order": [offering.upstream_provider], "allow_fallbacks": False}
    if policy.deny_data_collection:
        prefs["data_collection"] = "deny"
    if policy.require_zdr:
        prefs["zdr"] = True
    return prefs


@dataclass(frozen=True)
class AssignmentRow:
    project_id: uuid.UUID | None
    phase: str | None
    agent_role: str | None
    profile_id: uuid.UUID


def resolve_profile(
    rows: Iterable[AssignmentRow], project_id: uuid.UUID | None, phase: str | None, agent_role: str | None
) -> uuid.UUID | None:
    """Cascade Tenant -> Project -> Phase -> Agent role (spec 12.4): among the rows that apply, the most specific
    wins (project weighs more than phase, phase more than role)."""
    best: tuple[int, uuid.UUID] | None = None
    for r in rows:
        if r.project_id is not None and r.project_id != project_id:
            continue
        if r.phase is not None and r.phase != phase:
            continue
        if r.agent_role is not None and r.agent_role != agent_role:
            continue
        score = (4 if r.project_id else 0) + (2 if r.phase else 0) + (1 if r.agent_role else 0)
        if best is None or score > best[0]:
            best = (score, r.profile_id)
    return best[1] if best else None


def period_key(period: str, now: datetime) -> str:
    return now.strftime("%Y-%m") if period == "monthly" else "total"


def period_start(period: str, now: datetime) -> datetime | None:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) if period == "monthly" else None


def crossed_levels(spent: Decimal, amount: Decimal, alert_pct: int) -> list[int]:
    """Alert levels reached by the spend: the warning percentage and 100 (spec 13.5)."""
    reached = []
    if spent >= amount * Decimal(alert_pct) / Decimal(100):
        reached.append(alert_pct)
    if spent >= amount:
        reached.append(100)
    return reached
