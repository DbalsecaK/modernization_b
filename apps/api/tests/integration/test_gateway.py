"""Model gateway against the real database and OpenBao, with OpenRouter simulated from recorded responses
(M1 acceptance: ledger with tokens and cost, policy respected, budget stops the calls)."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.tenancy import create_tenant
from nexti_core.db.models import (
    Budget,
    BudgetAlert,
    BudgetReservation,
    EffortMapping,
    ModelAssignment,
    ModelFamily,
    ModelOffering,
    ModelPolicy,
    ModelProfile,
    ModelVersion,
    PriceVersion,
    ProviderConnection,
    UsageLedger,
)
from nexti_core.db.session import DbScope, scoped_connection
from nexti_model_gateway.catalog import LocalModel, add_local_model, load_offerings, sync_catalog
from nexti_model_gateway.gateway import (
    BudgetExceededError,
    CallContext,
    ModelGateway,
    NoProfileError,
    PolicyDeniedError,
    ProviderCallError,
)
from nexti_model_gateway.openrouter import BASE_URL, OpenRouterClient, Pricing
from nexti_model_gateway.secrets import SecretsConfig, SecretStore, connection_path

from .conftest import SETTINGS

MODEL = "openai/gpt-4o-mini"
CHAT: dict[str, Any] = {
    "id": "gen-test",
    "model": MODEL,
    "provider": "OpenAI",
    "choices": [{"message": {"role": "assistant", "content": "Ok."}}],
    "usage": {
        "prompt_tokens": 13,
        "completion_tokens": 2,
        "cost": 3.15e-06,
        "prompt_tokens_details": {"cached_tokens": 0},
        "completion_tokens_details": {"reasoning_tokens": 0},
    },
}
MESSAGES = [{"role": "user", "content": "Reply with the word ok."}]


@dataclass(frozen=True)
class Catalog:
    openai: uuid.UUID
    azure_zdr: uuid.UUID


@pytest.fixture(scope="module")
async def catalog(owner_engine: AsyncEngine) -> Catalog:
    """gpt-4o-mini offered by OpenAI (no ZDR) and by Azure (ZDR), with their real prices."""
    async with owner_engine.begin() as conn:
        family = (
            await conn.execute(
                insert(ModelFamily)
                .values(key=f"openai-{uuid.uuid4().hex[:6]}", name="OpenAI")
                .returning(ModelFamily.id)
            )
        ).scalar_one()
        slug = f"{MODEL}-{uuid.uuid4().hex[:6]}"
        version = (
            await conn.execute(
                insert(ModelVersion)
                .values(family_id=family, provider_slug=slug, canonical_slug=slug, name="GPT-4o-mini")
                .returning(ModelVersion.id)
            )
        ).scalar_one()
        ids = {}
        for upstream, zdr, input_price, output_price in (
            ("openai", False, "0.15", "0.60"),
            ("azure/swedencentral", True, "0.165", "0.66"),
        ):
            offering = (
                await conn.execute(
                    insert(ModelOffering)
                    .values(version_id=version, provider="openrouter", upstream_provider=upstream, zdr=zdr)
                    .returning(ModelOffering.id)
                )
            ).scalar_one()
            await conn.execute(
                insert(PriceVersion).values(
                    offering_id=offering,
                    input_per_mtok=Decimal(input_price),
                    output_per_mtok=Decimal(output_price),
                    source="provider_sync",
                )
            )
            await conn.execute(
                insert(EffortMapping).values(
                    offering_id=offering, effort="medium", parameters={"reasoning": {"effort": "medium"}}
                )
            )
            ids[upstream] = offering
    return Catalog(openai=ids["openai"], azure_zdr=ids["azure/swedencentral"])


@dataclass(frozen=True)
class Tenant:
    id: uuid.UUID
    primary: uuid.UUID
    fallback: uuid.UUID


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(timeout=10) as client:
        yield client


def secrets_store(http: httpx.AsyncClient) -> SecretStore:
    return SecretStore(SecretsConfig(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value()), http)


@pytest.fixture
async def tenant(owner_engine: AsyncEngine, catalog: Catalog, http: httpx.AsyncClient) -> Tenant:
    """A fresh tenant (the ledger is append-only, so budgets need their own) with an OpenRouter connection whose
    key is in OpenBao, a primary profile on OpenAI and its fallback on Azure (ZDR), assigned by default."""
    async with owner_engine.begin() as conn:
        tenant_id = await create_tenant(conn, slug=f"gw-{uuid.uuid4().hex[:8]}", name="Gateway test")
        connection = (
            await conn.execute(
                insert(ProviderConnection)
                .values(tenant_id=tenant_id, provider="openrouter", name="OpenRouter")
                .returning(ProviderConnection.id)
            )
        ).scalar_one()
        path = connection_path(tenant_id, connection)
        await conn.execute(
            update(ProviderConnection).where(ProviderConnection.id == connection).values(vault_path=path)
        )
        fallback = (
            await conn.execute(
                insert(ModelProfile)
                .values(
                    tenant_id=tenant_id,
                    name="Fallback",
                    connection_id=connection,
                    offering_id=catalog.azure_zdr,
                    max_retries=0,
                )
                .returning(ModelProfile.id)
            )
        ).scalar_one()
        primary = (
            await conn.execute(
                insert(ModelProfile)
                .values(
                    tenant_id=tenant_id,
                    name="Primary",
                    connection_id=connection,
                    offering_id=catalog.openai,
                    max_output_tokens=5,
                    max_retries=2,
                    fallback_profile_id=fallback,
                )
                .returning(ModelProfile.id)
            )
        ).scalar_one()
        await conn.execute(insert(ModelAssignment).values(tenant_id=tenant_id, profile_id=primary))
    await secrets_store(http).put(path, "sk-or-test-tenant-key")
    return Tenant(tenant_id, primary, fallback)


def gateway(app_engine: AsyncEngine, http: httpx.AsyncClient, *, allow_private_hosts: bool = False) -> ModelGateway:
    async def no_sleep(_: float) -> None:
        return None

    return ModelGateway(app_engine, secrets_store(http), OpenRouterClient(http), sleep=no_sleep,
                        allow_private_hosts=allow_private_hosts)  # fmt: skip


def mock_openrouter() -> respx.MockRouter:
    router = respx.mock(assert_all_called=False)
    router.route(host="127.0.0.1").pass_through()  # OpenBao is real
    return router


async def ledger(owner_engine: AsyncEngine, tenant_id: uuid.UUID) -> list[Any]:
    async with owner_engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    select(UsageLedger).where(UsageLedger.tenant_id == tenant_id).order_by(UsageLedger.id)
                )
            ).all()
        )


async def set_policy(owner_engine: AsyncEngine, tenant_id: uuid.UUID, **values: Any) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(insert(ModelPolicy).values(tenant_id=tenant_id, **values))


async def test_a_call_is_recorded_with_tokens_and_the_cost_openrouter_reports(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, http: httpx.AsyncClient, tenant: Tenant
) -> None:
    with mock_openrouter() as router:
        route = router.post(f"{BASE_URL}/chat/completions").respond(json=CHAT)
        result = await gateway(app_engine, http).complete(CallContext(tenant.id, phase="extraction"), MESSAGES)
    assert result.content == "Ok."
    assert result.cost_usd == Decimal("0.00000315")
    assert result.cost_usd == result.provider_cost_usd
    assert result.was_fallback is False

    request = route.calls.last.request
    body = json.loads(request.content)
    assert request.headers["authorization"] == "Bearer sk-or-test-tenant-key"
    assert body["provider"] == {"order": ["openai"], "allow_fallbacks": False, "data_collection": "deny"}
    assert body["usage"] == {"include": True}
    assert body["max_tokens"] == 5
    assert body["reasoning"] == {"effort": "medium"}

    [row] = await ledger(owner_engine, tenant.id)
    assert (row.outcome, row.input_tokens, row.output_tokens) == ("success", 13, 2)
    assert row.cost_usd == Decimal("0.00000315")
    assert row.provider_cost_usd == Decimal("0.00000315")
    assert row.phase == "extraction"
    assert row.price_version_id is not None
    assert row.provider_request_id == "gen-test"


async def test_zdr_policy_skips_the_primary_and_uses_the_zdr_fallback(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, http: httpx.AsyncClient, tenant: Tenant
) -> None:
    await set_policy(owner_engine, tenant.id, require_zdr=True)
    with mock_openrouter() as router:
        route = router.post(f"{BASE_URL}/chat/completions").respond(json=CHAT)
        result = await gateway(app_engine, http).complete(CallContext(tenant.id), MESSAGES)
    assert result.was_fallback is True
    assert result.profile_id == tenant.fallback
    body = json.loads(route.calls.last.request.content)
    assert body["provider"]["order"] == ["azure/swedencentral"]
    assert body["provider"]["zdr"] is True
    rows = await ledger(owner_engine, tenant.id)
    assert [(r.outcome, r.error_code, r.was_fallback) for r in rows] == [
        ("blocked", "policy:zdr_required", False),
        ("success", None, True),
    ]
    # 13 x 0.165 + 2 x 0.66 per million: the Azure price, not the OpenAI one.
    assert rows[1].cost_usd == Decimal("0.00000347")


async def test_a_tenant_that_forbids_openrouter_makes_no_call(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, http: httpx.AsyncClient, tenant: Tenant
) -> None:
    await set_policy(owner_engine, tenant.id, openrouter_allowed=False)
    with mock_openrouter() as router:
        route = router.post(f"{BASE_URL}/chat/completions").respond(json=CHAT)
        with pytest.raises(PolicyDeniedError, match="provider_not_allowed"):
            await gateway(app_engine, http).complete(CallContext(tenant.id), MESSAGES)
    assert not route.called
    rows = await ledger(owner_engine, tenant.id)
    assert {r.outcome for r in rows} == {"blocked"}
    async with owner_engine.connect() as conn:
        audited: int = (
            await conn.execute(
                text("SELECT count(*) FROM audit_log WHERE tenant_id = :t AND action = 'ai.call_blocked'"),
                {"t": tenant.id},
            )
        ).scalar_one()
    assert audited == 2


async def test_retryable_errors_are_retried_then_the_fallback_answers(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, http: httpx.AsyncClient, tenant: Tenant
) -> None:
    with mock_openrouter() as router:
        router.post(f"{BASE_URL}/chat/completions").mock(
            side_effect=[httpx.Response(503, json={"error": {"message": "overloaded", "code": 503}})] * 3
            + [httpx.Response(200, json=CHAT)]
        )
        result = await gateway(app_engine, http).complete(CallContext(tenant.id), MESSAGES)
    assert result.was_fallback is True
    rows = await ledger(owner_engine, tenant.id)
    assert [(r.outcome, r.error_code, r.retries) for r in rows] == [("error", "provider:503", 2), ("success", None, 0)]


async def test_the_budget_alerts_at_80_and_100_percent_and_then_stops_the_calls(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, http: httpx.AsyncClient, tenant: Tenant
) -> None:
    async with owner_engine.begin() as conn:
        # Rounded to cents, so use a budget reached after a couple of expensive calls.
        budget = (
            await conn.execute(
                insert(Budget)
                .values(tenant_id=tenant.id, period="monthly", amount_usd=Decimal("0.01"), alert_pct=80)
                .returning(Budget.id)
            )
        ).scalar_one()
    expensive = {**CHAT, "usage": {**CHAT["usage"], "prompt_tokens": 30_000, "completion_tokens": 0}}  # 0.0045 USD
    gw = gateway(app_engine, http)
    with mock_openrouter() as router:
        route = router.post(f"{BASE_URL}/chat/completions").respond(json=expensive)
        await gw.complete(CallContext(tenant.id), MESSAGES)  # 0.0045: 45 %
        await gw.complete(CallContext(tenant.id), MESSAGES)  # 0.0090: 90 % -> alert 80
        await gw.complete(CallContext(tenant.id), MESSAGES)  # 0.0135: 135 % -> alert 100
        calls = route.call_count
        with pytest.raises(BudgetExceededError) as info:
            await gw.complete(CallContext(tenant.id), MESSAGES)
        assert route.call_count == calls  # stopped before calling the provider
    assert info.value.budget_id == budget
    async with owner_engine.connect() as conn:
        levels = (await conn.execute(select(BudgetAlert.level).where(BudgetAlert.budget_id == budget))).scalars().all()
    assert sorted(levels) == [80, 100]
    rows = await ledger(owner_engine, tenant.id)
    assert rows[-1].outcome == "blocked"
    assert rows[-1].error_code == "budget_exceeded"


async def test_calls_in_flight_count_against_the_budget_until_they_end(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, http: httpx.AsyncClient, tenant: Tenant
) -> None:
    """Parallel calls (a fan-out of rule extraction) cannot all pass the budget before any is recorded: each call
    reserves what it may cost while it is in flight, and budgets count spend plus reservations (spec 13.5)."""
    async with owner_engine.begin() as conn:
        await conn.execute(insert(Budget).values(tenant_id=tenant.id, period="monthly", amount_usd=Decimal("0.01")))
        # Another call in flight may still spend the whole budget.
        await conn.execute(insert(BudgetReservation).values(tenant_id=tenant.id, amount_usd=Decimal("0.01")))
    gw = gateway(app_engine, http)
    with mock_openrouter() as router:
        route = router.post(f"{BASE_URL}/chat/completions").respond(json=CHAT)
        with pytest.raises(BudgetExceededError):
            await gw.complete(CallContext(tenant.id), MESSAGES)
        assert route.call_count == 0  # stopped before calling the provider
        async with owner_engine.begin() as conn:
            # A reservation left by a crashed process stops counting after 15 minutes.
            await conn.execute(
                text("UPDATE budget_reservation SET created_at = now() - interval '20 minutes' WHERE tenant_id = :t"),
                {"t": tenant.id},
            )
        await gw.complete(CallContext(tenant.id), MESSAGES)
        await asyncio.gather(*(gw.complete(CallContext(tenant.id), MESSAGES) for _ in range(3)))
    assert route.call_count == 4
    async with owner_engine.connect() as conn:
        fresh: int = (
            await conn.execute(
                text("SELECT count(*) FROM budget_reservation WHERE tenant_id = :t AND created_at > now() - "
                     "interval '15 minutes'"),
                {"t": tenant.id},
            )
        ).scalar_one()  # fmt: skip
    assert fresh == 0  # every call released its reservation when it ended


async def test_assignments_follow_the_cascade_and_tenants_stay_apart(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, http: httpx.AsyncClient, tenant: Tenant, catalog: Catalog
) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            insert(ModelAssignment).values(tenant_id=tenant.id, phase="verification", profile_id=tenant.fallback)
        )
    other = await create_empty_tenant(owner_engine)
    with mock_openrouter() as router:
        router.post(f"{BASE_URL}/chat/completions").respond(json=CHAT)
        verification = await gateway(app_engine, http).complete(CallContext(tenant.id, phase="verification"), MESSAGES)
        extraction = await gateway(app_engine, http).complete(CallContext(tenant.id, phase="extraction"), MESSAGES)
        with pytest.raises(NoProfileError):
            await gateway(app_engine, http).complete(CallContext(other), MESSAGES)
    assert verification.profile_id == tenant.fallback
    assert extraction.profile_id == tenant.primary


async def create_empty_tenant(owner_engine: AsyncEngine) -> uuid.UUID:
    async with owner_engine.begin() as conn:
        return await create_tenant(conn, slug=f"gw-empty-{uuid.uuid4().hex[:8]}", name="No AI config")


async def test_the_usage_ledger_is_append_only(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, tenant: Tenant
) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(insert(UsageLedger).values(tenant_id=tenant.id, outcome="success"))
    with pytest.raises(DBAPIError, match="append-only"):
        async with owner_engine.begin() as conn:
            await conn.execute(text("UPDATE usage_ledger SET cost_usd = 0 WHERE tenant_id = :t"), {"t": tenant.id})
    with pytest.raises(DBAPIError, match="permission denied"):
        async with scoped_connection(app_engine, DbScope(tenant_id=tenant.id)) as conn:
            await conn.execute(text("DELETE FROM usage_ledger"))


async def test_catalog_sync_and_offerings_with_versioned_prices(
    owner_engine: AsyncEngine, http: httpx.AsyncClient
) -> None:
    slug = f"acme/model-{uuid.uuid4().hex[:6]}"
    models = {
        "data": [
            {
                "id": slug,
                "canonical_slug": f"{slug}-20260928",
                "name": "Acme",
                "context_length": 8000,
                "architecture": {"input_modalities": ["text"]},
                "supported_parameters": ["reasoning"],
            },
            # A variant of the same model: OpenRouter lists both under one canonical slug.
            {"id": f"{slug}:thinking", "canonical_slug": f"{slug}-20260928", "name": "Acme (thinking)"},
        ]
    }
    endpoints = {
        "data": {
            "architecture": {},
            "endpoints": [
                {
                    "tag": "acme",
                    "provider_name": "Acme",
                    "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                    "status": 0,
                    "supported_parameters": ["reasoning"],
                }
            ],
        }
    }
    cheaper = json.loads(json.dumps(endpoints))
    cheaper["data"]["endpoints"][0]["pricing"]["prompt"] = "0.0000005"
    with mock_openrouter() as router:
        router.get(f"{BASE_URL}/models").respond(json=models)
        router.get(f"{BASE_URL}/endpoints/zdr").respond(json={"data": [{"model_id": slug, "tag": "acme"}]})
        ep = router.get(f"{BASE_URL}/models/{slug}/endpoints")
        client = OpenRouterClient(http)
        async with owner_engine.begin() as conn:
            await sync_catalog(conn, client)
            same_canonical = (
                await conn.execute(select(func.count()).where(ModelVersion.canonical_slug == f"{slug}-20260928"))
            ).scalar_one()
            assert same_canonical == 2
            version = (
                await conn.execute(select(ModelVersion.id).where(ModelVersion.provider_slug == slug))
            ).scalar_one()
            ep.respond(json=endpoints)
            await load_offerings(conn, client, version)
            ep.respond(json=cheaper)
            await load_offerings(conn, client, version)
            offering = (await conn.execute(select(ModelOffering).where(ModelOffering.version_id == version))).one()
            prices = (
                await conn.execute(
                    select(PriceVersion.input_per_mtok, PriceVersion.valid_to)
                    .where(PriceVersion.offering_id == offering.id)
                    .order_by(PriceVersion.valid_from)
                )
            ).all()
            effort: dict[str, object] = (
                await conn.execute(
                    select(EffortMapping.parameters).where(
                        EffortMapping.offering_id == offering.id, EffortMapping.effort == "high"
                    )
                )
            ).scalar_one()
    assert offering.zdr is True
    assert [p.input_per_mtok for p in prices] == [Decimal("1.000000"), Decimal("0.500000")]
    assert prices[0].valid_to is not None
    assert prices[1].valid_to is None
    assert effort == {"reasoning": {"effort": "high"}}


LOCAL_BASE = "http://vllm.internal:8000/v1"
LOCAL_CHAT: dict[str, Any] = {
    "id": "chatcmpl-local",
    "model": "llama-3.1-8b-instruct",
    "choices": [{"message": {"role": "assistant", "content": "Ok."}}],
    "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
}


async def local_tenant(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, price: Decimal
) -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant with an openai-compatible connection (no API key) and one model entered by hand with a declared
    price, as the API does it (catalog.add_local_model under the tenant's RLS scope)."""
    async with owner_engine.begin() as conn:
        tenant_id = await create_tenant(conn, slug=f"gwl-{uuid.uuid4().hex[:8]}", name="Local models")
        connection = (
            await conn.execute(
                insert(ProviderConnection)
                .values(tenant_id=tenant_id, provider="openai-compatible", name="vLLM", base_url=LOCAL_BASE)
                .returning(ProviderConnection.id)
            )
        ).scalar_one()
    async with scoped_connection(app_engine, DbScope(tenant_id=tenant_id)) as conn:
        offering = await add_local_model(
            conn, tenant_id, connection, LocalModel("llama-3.1-8b-instruct", "Llama", price=Pricing(price, price))
        )
        profile = (
            await conn.execute(
                insert(ModelProfile)
                .values(
                    tenant_id=tenant_id, name="Local", connection_id=connection, offering_id=offering, max_retries=0
                )
                .returning(ModelProfile.id)
            )
        ).scalar_one()
        await conn.execute(insert(ModelAssignment).values(tenant_id=tenant_id, profile_id=profile))
    return tenant_id, offering


async def test_an_openai_compatible_server_is_called_and_its_usage_recorded(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, http: httpx.AsyncClient
) -> None:
    tenant_id, offering = await local_tenant(owner_engine, app_engine, Decimal("2"))
    with mock_openrouter() as router:
        route = router.post(f"{LOCAL_BASE}/chat/completions").respond(json=LOCAL_CHAT)
        # the air-gapped deployment allows model servers on private hosts (vllm.internal)
        local = gateway(app_engine, http, allow_private_hosts=True)
        result = await local.complete(CallContext(tenant_id, phase="extraction"), MESSAGES)
    request = route.calls.last.request
    body = json.loads(request.content)
    assert "authorization" not in request.headers
    assert not {"provider", "usage"} & set(body)  # nothing OpenRouter-only
    assert body["model"] == "llama-3.1-8b-instruct"
    # 1500 tokens at the declared 2 USD per million.
    assert result.cost_usd == Decimal("0.00300000")
    [row] = await ledger(owner_engine, tenant_id)
    assert (row.outcome, row.offering_id, row.input_tokens, row.output_tokens) == ("success", offering, 1000, 500)
    assert row.cost_usd == Decimal("0.00300000")
    assert row.provider_cost_usd is None


async def test_a_local_model_costs_zero_by_default_and_works_with_openrouter_off(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, http: httpx.AsyncClient, tenant: Tenant
) -> None:
    tenant_id, _ = await local_tenant(owner_engine, app_engine, Decimal(0))

    async def no_sleep(_: float) -> None:
        return None

    airgapped = ModelGateway(
        app_engine,
        secrets_store(http),
        OpenRouterClient(http),
        sleep=no_sleep,
        openrouter_enabled=False,
        allow_private_hosts=True,
    )
    with mock_openrouter() as router:
        router.post(f"{LOCAL_BASE}/chat/completions").respond(json=LOCAL_CHAT)
        openrouter = router.post(f"{BASE_URL}/chat/completions").respond(json=CHAT)
        result = await airgapped.complete(CallContext(tenant_id), MESSAGES)
        with pytest.raises(PolicyDeniedError):
            await airgapped.complete(CallContext(tenant.id), MESSAGES)
    assert result.cost_usd == Decimal(0)
    assert not openrouter.called
    assert {r.error_code for r in await ledger(owner_engine, tenant.id)} == {"policy:openrouter_disabled"}


async def test_a_server_whose_host_is_internal_at_call_time_is_refused(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, http: httpx.AsyncClient
) -> None:
    """The base URL was checked when configured, but DNS can change (rebinding): without private hosts allowed, a
    host that does not resolve to a public address is refused before any request leaves."""
    tenant_id, _ = await local_tenant(owner_engine, app_engine, Decimal(0))
    with mock_openrouter() as router:
        route = router.post(f"{LOCAL_BASE}/chat/completions").respond(json=LOCAL_CHAT)
        with pytest.raises(ProviderCallError):
            await gateway(app_engine, http).complete(CallContext(tenant_id), MESSAGES)
    assert not route.called
    assert {r.error_code for r in await ledger(owner_engine, tenant_id)} == {"host_not_allowed"}


async def test_a_tenants_local_models_are_invisible_to_other_tenants(
    app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    tenant_a, offering = await local_tenant(owner_engine, app_engine, Decimal(0))
    tenant_b, _ = await local_tenant(owner_engine, app_engine, Decimal(0))  # same slug: unique per tenant
    async with scoped_connection(app_engine, DbScope(tenant_id=tenant_b)) as conn:
        assert (await conn.execute(select(ModelOffering).where(ModelOffering.id == offering))).first() is None
        assert (await conn.execute(select(PriceVersion).where(PriceVersion.offering_id == offering))).first() is None
        assert (await conn.execute(select(EffortMapping).where(EffortMapping.offering_id == offering))).first() is None
        versions = (
            (
                await conn.execute(
                    select(ModelVersion.tenant_id).where(ModelVersion.provider_slug == "llama-3.1-8b-instruct")
                )
            )
            .scalars()
            .all()
        )
        assert set(versions) == {tenant_b}
        # Nor can it attach a model to another tenant's rows.
        with pytest.raises(DBAPIError):
            await conn.execute(
                insert(ModelOffering).values(
                    version_id=select(ModelVersion.id).where(ModelVersion.tenant_id == tenant_b).scalar_subquery(),
                    provider="openai-compatible",
                    upstream_provider="connection:forged",
                    tenant_id=tenant_a,
                )
            )
