"""The usage of one project through the API (spec 13.5 "Por proyecto"; plan P2 step 5): by phase, agent and model,
the self-correction calls and the project budget, all from the usage ledger and nothing from other projects."""

import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_core.db.models import Budget, UsageLedger

from .conftest import World
from .run_support import make_project
from .test_runs_api import sign_in

MODEL = "openai/gpt-4o-mini"


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def _call(
    tenant: uuid.UUID, project: uuid.UUID, phase: str, agent: str, iteration: int, cost: str
) -> dict[str, object]:
    return {"tenant_id": tenant, "project_id": project, "phase": phase, "agent_role": agent, "iteration": iteration,
            "model": MODEL, "outcome": "success", "input_tokens": 1000, "output_tokens": 100,
            "cost_usd": Decimal(cost)}  # fmt: skip


async def test_the_usage_of_a_project_by_phase_agent_and_model(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await make_project(owner_engine, world.tenant_a)
    other = await make_project(owner_engine, world.tenant_a)
    a = world.tenant_a
    async with owner_engine.begin() as conn:
        await conn.execute(insert(UsageLedger), [
            _call(a, project_id, "design", "architect", 1, "0.10"),
            _call(a, project_id, "design", "architect", 2, "0.05"),
            _call(a, project_id, "generation", "developer", 1, "0.30"),
            _call(a, other, "generation", "developer", 1, "9.00"),
        ])  # fmt: skip
        await conn.execute(insert(Budget).values(tenant_id=a, project_id=project_id, period="total",
                                                 amount_usd=Decimal("5.00")))  # fmt: skip
    await reconcile(app_engine, fga)
    headers = sign_in(api, world.a_user)
    usage = api.get(f"/api/v1/projects/{project_id}/usage", headers=headers).json()
    assert usage["costVisible"] is True
    assert Decimal(usage["budgetUsd"]) == Decimal("5.00")
    assert (usage["total"]["calls"], Decimal(usage["total"]["costUsd"])) == (3, Decimal("0.45"))
    assert (usage["selfCorrection"]["calls"], Decimal(usage["selfCorrection"]["costUsd"])) == (1, Decimal("0.05"))
    assert [(r["key"], Decimal(r["costUsd"])) for r in usage["byPhase"]] == [("generation", Decimal("0.30")),
                                                                            ("design", Decimal("0.15"))]  # fmt: skip
    assert [r["key"] for r in usage["byAgent"]] == ["developer", "architect"]
    assert [(r["key"], r["inputTokens"]) for r in usage["byModel"]] == [(MODEL, 3000)]


async def test_a_new_project_has_used_nothing_and_another_tenant_sees_nothing(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await make_project(owner_engine, world.tenant_a)
    await reconcile(app_engine, fga)
    usage = api.get(f"/api/v1/projects/{project_id}/usage", headers=sign_in(api, world.a_user)).json()
    assert (usage["total"]["calls"], usage["byPhase"], usage["budgetUsd"]) == (0, [], None)
    api.cookies.clear()
    outsider = api.get(f"/api/v1/projects/{project_id}/usage", headers=sign_in(api, world.b_user))
    assert outsider.status_code in (403, 404)
