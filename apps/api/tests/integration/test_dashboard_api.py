"""The dashboard through the API (spec 18.2; plan P2 step 6): per project the newest run, the rules the newest verdict
verified, the verdict and spend against budget; the delivery counters; and the administrator's view, all from data
of the active tenant only."""

import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_core.db.models import Budget, BudgetAlert, UsageLedger

from .conftest import World
from .test_runs_api import sign_in
from .test_validation_api import seeded


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def _spend(owner: AsyncEngine, tenant: uuid.UUID, project: uuid.UUID) -> None:
    async with owner.begin() as conn:
        await conn.execute(insert(UsageLedger).values(
            tenant_id=tenant, project_id=project, phase="generation", model="openai/gpt-4o-mini", outcome="success",
            input_tokens=1000, output_tokens=200, cost_usd=Decimal("0.40"),
        ))  # fmt: skip
        budget_id = (
            await conn.execute(insert(Budget).values(tenant_id=tenant, project_id=project, period="total",
                                                     amount_usd=Decimal("0.50")).returning(Budget.id))
        ).scalar_one()  # fmt: skip
        await conn.execute(insert(BudgetAlert).values(tenant_id=tenant, budget_id=budget_id, level=80,
                                                      period_key="total", spent_usd=Decimal("0.40")))  # fmt: skip
        await conn.execute(
            text("UPDATE run SET status = 'waiting', waiting_reason = 'escalation' WHERE project_id = :p"),
            {"p": project},
        )


async def test_the_dashboard_of_a_tenant_administrator(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id, _ = await seeded(owner_engine, app_engine, fga, world)
    await _spend(owner_engine, world.tenant_a, project_id)
    board = api.get("/api/v1/dashboard", headers=sign_in(api, world.a_user)).json()
    assert board["costVisible"] is True
    project = next(p for p in board["projects"] if p["id"] == str(project_id))
    assert (project["rulesTotal"], project["rulesVerified"], project["verdict"]) == (3, 1, "PARTLY PROVEN")
    assert (project["runStatus"], project["waitingReason"]) == ("waiting", "escalation")
    assert (Decimal(project["spentUsd"]), Decimal(project["budgetUsd"])) == (Decimal("0.40"), Decimal("0.50"))
    assert board["delivery"]["escalations"] >= 1
    assert board["delivery"]["tokensToday"] >= 1200
    assert any(m["usd"] for m in board["monthlySpend"])
    admin = board["admin"]
    assert admin["activeUsers"] >= 1
    assert any(a["projectName"] == project["name"] and a["level"] == 80 for a in admin["budgetAlerts"])


async def test_another_tenant_does_not_see_these_projects(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id, _ = await seeded(owner_engine, app_engine, fga, world)
    board = api.get("/api/v1/dashboard", headers=sign_in(api, world.b_user)).json()
    assert str(project_id) not in {p["id"] for p in board["projects"]}
