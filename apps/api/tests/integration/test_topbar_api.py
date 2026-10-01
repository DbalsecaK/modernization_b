"""The top bar through the API (spec 18.1; plan P2 step 7): the global search over projects and rules the user may
see, and the notifications derived from runs, verdicts and budget alerts, all within the active tenant."""

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
from nexti_core.db.models import Budget, BudgetAlert

from .conftest import World
from .test_runs_api import sign_in
from .test_validation_api import seeded


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def _name(owner: AsyncEngine, project_id: uuid.UUID) -> str:
    async with owner.connect() as conn:
        name: str = (await conn.execute(text("SELECT name FROM project WHERE id = :p"), {"p": project_id})).scalar_one()
    return name


async def test_the_search_finds_projects_and_rules_the_user_may_see(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id, _ = await seeded(owner_engine, app_engine, fga, world)
    name = await _name(owner_engine, project_id)
    headers = sign_in(api, world.a_user)
    by_name = api.get("/api/v1/search", params={"q": name[-8:]}, headers=headers).json()
    assert [(h["kind"], h["id"]) for h in by_name] == [("project", str(project_id))]
    rules = [h for h in api.get("/api/v1/search", params={"q": "RULE-00"}, headers=headers).json()
             if h["projectId"] == str(project_id)]  # fmt: skip
    assert [(h["id"], h["label"], h["hint"]) for h in rules] == [
        ("RULE-001", "RULE-001 · Rule 1", name), ("RULE-002", "RULE-002 · Rule 2", name),
        ("RULE-003", "RULE-003 · Rule 3", name),
    ]  # fmt: skip
    # Wildcards are literal text, and the query needs two characters.
    assert api.get("/api/v1/search", params={"q": "%_"}, headers=headers).json() == []
    assert api.get("/api/v1/search", params={"q": "R"}, headers=headers).status_code == 422
    api.cookies.clear()
    other = api.get("/api/v1/search", params={"q": name[-8:]}, headers=sign_in(api, world.b_user)).json()
    assert other == []


async def test_notifications_come_from_runs_verdicts_and_budget_alerts(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id, _ = await seeded(owner_engine, app_engine, fga, world)
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE run SET status = 'waiting', waiting_reason = 'escalation', "
                                "current_phase = 'generation' WHERE project_id = :p"), {"p": project_id})  # fmt: skip
        budget = (
            await conn.execute(insert(Budget).values(tenant_id=world.tenant_a, project_id=project_id, period="total",
                                                     amount_usd=Decimal("1")).returning(Budget.id))
        ).scalar_one()  # fmt: skip
        await conn.execute(insert(BudgetAlert).values(tenant_id=world.tenant_a, budget_id=budget, level=80,
                                                      period_key="total", spent_usd=Decimal("0.8")))  # fmt: skip
    mine = [n for n in api.get("/api/v1/notifications", headers=sign_in(api, world.a_user)).json()
            if n["projectId"] == str(project_id)]  # fmt: skip
    kinds = {n["kind"]: n for n in mine}
    assert set(kinds) == {"escalation", "verdict", "budget"}
    assert (kinds["escalation"]["title"], kinds["escalation"]["tab"]) == ("generation", "runs")
    assert kinds["verdict"]["title"] == "PayOrder · PARTLY PROVEN"
    assert (kinds["budget"]["title"], kinds["budget"]["tab"]) == ("80%", "costs")
    assert mine == sorted(mine, key=lambda n: n["occurredAt"], reverse=True)
    api.cookies.clear()
    others = api.get("/api/v1/notifications", headers=sign_in(api, world.b_user)).json()
    assert all(n["projectId"] != str(project_id) for n in others)
