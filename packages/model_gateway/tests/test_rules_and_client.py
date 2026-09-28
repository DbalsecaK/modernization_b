import uuid
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from nexti_model_gateway.openrouter import BASE_URL, ChatUsage, OpenRouterClient, Pricing, ProviderError
from nexti_model_gateway.rules import (
    AssignmentRow,
    OfferingFacts,
    Policy,
    cost_usd,
    crossed_levels,
    period_key,
    policy_denial,
    resolve_profile,
    routing,
)

from . import openrouter_samples as s

GPT4O_MINI = Pricing(Decimal("0.15"), Decimal("0.60"), Decimal("0.075"))


def test_cost_matches_the_cost_openrouter_reported() -> None:
    # The real call of the samples: 13 input + 2 output tokens, OpenRouter reported 3.15e-06 USD.
    assert cost_usd(ChatUsage(input_tokens=13, output_tokens=2), GPT4O_MINI) == Decimal("0.00000315")


def test_cached_input_is_billed_at_the_cache_price() -> None:
    usage = ChatUsage(input_tokens=1_000_000, output_tokens=0, cache_read_tokens=400_000)
    assert cost_usd(usage, GPT4O_MINI) == Decimal("0.12")  # 600k x 0.15 + 400k x 0.075


def test_a_request_fee_is_added() -> None:
    price = Pricing(Decimal(1), Decimal(1), request_usd=Decimal("0.005"))
    assert cost_usd(ChatUsage(input_tokens=0, output_tokens=0), price) == Decimal("0.005")


OPENAI = OfferingFacts("openrouter", "openai", zdr=False)
AZURE_ZDR = OfferingFacts("openrouter", "azure/swedencentral", zdr=True)


@pytest.mark.parametrize(
    ("policy", "offering", "reason"),
    [
        (Policy(), OPENAI, None),
        (Policy(openrouter_allowed=False), OPENAI, "provider_not_allowed"),
        (Policy(denied_upstream_providers=("openai",)), OPENAI, "upstream_provider_denied"),
        (Policy(allowed_upstream_providers=("anthropic",)), OPENAI, "upstream_provider_not_allowed"),
        (Policy(allowed_upstream_providers=("azure",)), AZURE_ZDR, None),
        (Policy(require_zdr=True), OPENAI, "zdr_required"),
        (Policy(require_zdr=True), AZURE_ZDR, None),
    ],
)
def test_policy(policy: Policy, offering: OfferingFacts, reason: str | None) -> None:
    assert policy_denial(policy, offering) == reason


def test_routing_pins_the_provider_and_carries_the_policy() -> None:
    assert routing(Policy(require_zdr=True), AZURE_ZDR) == {
        "order": ["azure/swedencentral"],
        "allow_fallbacks": False,
        "data_collection": "deny",
        "zdr": True,
    }
    assert "zdr" not in routing(Policy(deny_data_collection=False), OPENAI)
    assert "data_collection" not in routing(Policy(deny_data_collection=False), OPENAI)


def test_the_most_specific_assignment_wins() -> None:
    project = uuid.uuid4()
    tenant_default, project_default, phase_default, role_specific = (uuid.uuid4() for _ in range(4))
    rows = [
        AssignmentRow(None, None, None, tenant_default),
        AssignmentRow(project, None, None, project_default),
        AssignmentRow(project, "codegen", None, phase_default),
        AssignmentRow(project, "codegen", "tester", role_specific),
        AssignmentRow(uuid.uuid4(), None, None, uuid.uuid4()),  # another project
    ]
    assert resolve_profile(rows, project, "codegen", "tester") == role_specific
    assert resolve_profile(rows, project, "codegen", "developer") == phase_default
    assert resolve_profile(rows, project, "extraction", None) == project_default
    assert resolve_profile(rows, uuid.uuid4(), "codegen", "tester") == tenant_default
    assert resolve_profile([], project, None, None) is None


def test_budget_levels_and_periods() -> None:
    assert crossed_levels(Decimal("79.99"), Decimal(100), 80) == []
    assert crossed_levels(Decimal(80), Decimal(100), 80) == [80]
    assert crossed_levels(Decimal(100), Decimal(100), 80) == [80, 100]
    now = datetime(2026, 9, 28, tzinfo=UTC)
    assert period_key("monthly", now) == "2026-09"
    assert period_key("total", now) == "total"


@respx.mock
async def test_client_parses_catalog_endpoints_zdr_and_key() -> None:
    respx.get(f"{BASE_URL}/models").respond(json=s.MODELS)
    respx.get(f"{BASE_URL}/models/{s.MODEL}/endpoints").respond(json=s.ENDPOINTS)
    respx.get(f"{BASE_URL}/endpoints/zdr").respond(json=s.ZDR)
    key_route = respx.get(f"{BASE_URL}/key").respond(json=s.KEY)
    async with httpx.AsyncClient() as http:
        client = OpenRouterClient(http)
        models = await client.list_models()
        endpoints = await client.list_endpoints(s.MODEL)
        zdr = await client.zdr_endpoints()
        info = await client.key_info("sk-or-test")
    assert models[1].canonical_slug == "anthropic/claude-sonnet-5.5-20260928"
    assert set(models[0].capabilities) == {"tools", "structured_output", "vision"}
    assert "reasoning" in models[1].capabilities
    assert endpoints[1].upstream_provider == "azure/swedencentral"
    assert endpoints[1].pricing.input_per_mtok == Decimal("0.165")
    assert endpoints[0].pricing.cache_read_per_mtok == Decimal("0.075")
    assert (s.MODEL, "azure/swedencentral") in zdr
    assert info["is_free_tier"] is False
    assert key_route.calls.last.request.headers["authorization"] == "Bearer sk-or-test"


@respx.mock
async def test_client_parses_a_chat_completion() -> None:
    route = respx.post(f"{BASE_URL}/chat/completions").respond(json=s.CHAT)
    async with httpx.AsyncClient() as http:
        result = await OpenRouterClient(http).chat("sk-or-test", {"model": s.MODEL, "messages": []}, 30)
    assert result.content == "Ok."
    assert result.request_id == s.CHAT["id"]
    assert (result.usage.input_tokens, result.usage.output_tokens) == (13, 2)
    assert result.usage.provider_cost_usd == Decimal("0.00000315")
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-or-test"


@respx.mock
@pytest.mark.parametrize(("status", "retryable"), [(429, True), (503, True), (400, False), (401, False)])
async def test_client_classifies_errors(status: int, retryable: bool) -> None:
    respx.post(f"{BASE_URL}/chat/completions").respond(status, json={"error": {"message": "nope", "code": status}})
    async with httpx.AsyncClient() as http:
        with pytest.raises(ProviderError) as info:
            await OpenRouterClient(http).chat("k", {"model": s.MODEL}, 30)
    assert info.value.status == status
    assert info.value.retryable is retryable
