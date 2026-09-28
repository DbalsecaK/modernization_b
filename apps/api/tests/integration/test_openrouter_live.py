"""M1 acceptance with the real OpenRouter API: one minimal call through the gateway is recorded in the usage ledger
with its tokens, and the cost the platform computes from its versioned price matches the cost OpenRouter reports.

Needs OPENROUTER_API_KEY_FOR_TESTS (environment or infra/docker-compose/.env); skipped without it. One call to
openai/gpt-4o-mini with a handful of tokens costs a few millionths of a dollar.
"""

import os
import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.tenancy import create_tenant
from nexti_core.db.models import (
    ModelAssignment,
    ModelFamily,
    ModelOffering,
    ModelProfile,
    ModelVersion,
    ProviderConnection,
    UsageLedger,
)
from nexti_model_gateway.gateway import CallContext
from nexti_model_gateway.service import GatewayService, SecretsConfig

from .conftest import SETTINGS, compose_env

MODEL = "openai/gpt-4o-mini"
UPSTREAM = "openai"


def _api_key() -> str:
    if key := os.environ.get("OPENROUTER_API_KEY_FOR_TESTS"):
        return key
    try:
        return compose_env("OPENROUTER_API_KEY_FOR_TESTS")
    except (RuntimeError, OSError):
        return ""


API_KEY = _api_key()
pytestmark = pytest.mark.skipif(not API_KEY, reason="OPENROUTER_API_KEY_FOR_TESTS is not set")


async def _version(engine: AsyncEngine) -> uuid.UUID:
    """The catalog row of the model (other tests may have created it with a simulated catalog)."""
    async with engine.begin() as conn:
        found = (await conn.execute(select(ModelVersion.id).where(ModelVersion.provider_slug == MODEL))).scalar()
        if found is not None:
            return found
        family = (
            await conn.execute(
                insert(ModelFamily).values(key=f"openai-live-{uuid.uuid4().hex[:6]}", name="OpenAI")
                .returning(ModelFamily.id)
            )
        ).scalar_one()  # fmt: skip
        version: uuid.UUID = (
            await conn.execute(
                insert(ModelVersion)
                .values(family_id=family, provider_slug=MODEL, canonical_slug=MODEL, name="GPT-4o-mini")
                .returning(ModelVersion.id)
            )
        ).scalar_one()
    return version


async def test_a_real_call_is_recorded_with_the_cost_openrouter_reports(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with httpx.AsyncClient(timeout=60) as http:
        # The gateway runs as the application role, under RLS, as in production.
        service = GatewayService(
            app_engine, http, SecretsConfig(SETTINGS.secrets_url, SETTINGS.secrets_token.get_secret_value())
        )
        version = await _version(owner_engine)
        # Real providers and prices of the model, from OpenRouter.
        async with owner_engine.begin() as conn:
            assert await service.load_offerings(conn, version) > 0
            offering = (
                await conn.execute(
                    select(ModelOffering.id).where(
                        ModelOffering.version_id == version, ModelOffering.upstream_provider == UPSTREAM
                    )
                )
            ).scalar_one()

        async with owner_engine.begin() as conn:
            tenant_id = await create_tenant(conn, slug=f"live-{uuid.uuid4().hex[:8]}", name="OpenRouter live test")
        connection_id = uuid.uuid4()
        path = await service.store_credential(tenant_id, connection_id, API_KEY)
        try:
            assert (await service.check_connection(path)).ok
            async with owner_engine.begin() as conn:
                await conn.execute(
                    insert(ProviderConnection).values(
                        id=connection_id, tenant_id=tenant_id, provider="openrouter", name="Live", vault_path=path
                    )
                )
                profile = (
                    await conn.execute(
                        insert(ModelProfile)
                        .values(
                            tenant_id=tenant_id, name="Live", connection_id=connection_id, offering_id=offering,
                            max_output_tokens=16, max_retries=1,
                        )
                        .returning(ModelProfile.id)
                    )
                ).scalar_one()  # fmt: skip
                await conn.execute(insert(ModelAssignment).values(tenant_id=tenant_id, profile_id=profile))

            result = await service.complete(
                CallContext(tenant_id=tenant_id, phase="connection-test"),
                [{"role": "user", "content": "Reply with the single word: ok"}],
                max_tokens=5,
            )
        finally:
            await service.delete_credential(path)

    assert result.content
    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0
    async with owner_engine.connect() as conn:
        row = (await conn.execute(select(UsageLedger).where(UsageLedger.tenant_id == tenant_id))).one()
    assert row.outcome == "success"
    assert row.upstream_provider == UPSTREAM
    assert row.price_version_id is not None
    assert (row.input_tokens, row.output_tokens) == (result.usage.input_tokens, result.usage.output_tokens)
    assert row.provider_cost_usd is not None
    # Computed from the versioned price = reported by OpenRouter (to the micro-dollar precision of the ledger).
    assert abs(row.cost_usd - row.provider_cost_usd) <= Decimal("0.00000001"), (row.cost_usd, row.provider_cost_usd)
