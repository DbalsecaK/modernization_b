"""The delta of Flow 3 through the API (ADR-0026): the AS-IS inventory, the baseline, the design, the new and changed
files and DELTA.md as the worker stored them; nothing before the inventory, and another tenant reaches nothing."""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings

from .conftest import World
from .run_support import make_project, seed_delta
from .test_runs_api import sign_in
from .test_validation_api import store


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def _project(owner: AsyncEngine, app_engine: AsyncEngine, fga: OpenFga, world: World) -> uuid.UUID:
    project_id = await make_project(owner, world.tenant_a)
    await seed_delta(owner, store(), world.tenant_a, project_id)
    await reconcile(app_engine, fga)
    return project_id


async def test_the_delta_and_its_baseline_are_shown(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await _project(owner_engine, app_engine, fga, world)
    found = api.get(f"/api/v1/projects/{project_id}/delta", headers=sign_in(api, world.a_user)).json()
    assert found["inventory"]["endpoints"][0]["path"] == "/api/v1/payments"
    assert found["baseline"]["passed"] == ["PaymentServiceTest.a_prepaid_account_cannot_pay()"]
    assert found["design"]["changes"][0]["name"] == "PaymentStatusQuery"
    assert found["added"] == ["src/main/java/com/contoso/billpay/domain/PaymentStatusService.java"]
    assert found["changed"] == []
    assert "**PROVEN**" in found["report"]


async def test_before_the_inventory_there_is_no_delta(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await make_project(owner_engine, world.tenant_a)
    await reconcile(app_engine, fga)
    found = api.get(f"/api/v1/projects/{project_id}/delta", headers=sign_in(api, world.a_user)).json()
    assert found == {"inventory": None, "baseline": None, "design": None, "added": [], "changed": [], "report": None}


async def test_the_delta_of_another_tenant_is_unreachable(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await _project(owner_engine, app_engine, fga, world)
    response = api.get(f"/api/v1/projects/{project_id}/delta", headers=sign_in(api, world.b_user))
    assert response.status_code in (403, 404)
