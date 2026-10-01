"""The architecture and the contracts of the target through the API (spec 18.3; plan P2 step 3): the design approved
at C3 as the worker stored it, and the HTTP contract, from the frontend's OpenAPI document when there is one and
otherwise from the design's use cases, with the same paths."""

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
from .run_support import make_project, seed_architecture
from .test_runs_api import sign_in
from .test_validation_api import store

ALL_RULES = [f"RULE-00{n}" for n in range(1, 10)]


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def _project(owner: AsyncEngine, app_engine: AsyncEngine, fga: OpenFga, world: World, **kw: bool) -> uuid.UUID:
    project_id = await make_project(owner, world.tenant_a)
    await seed_architecture(owner, store(), world.tenant_a, project_id, **kw)
    await reconcile(app_engine, fga)
    return project_id


async def test_the_design_and_the_openapi_contract(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await _project(owner_engine, app_engine, fga, world)
    headers = sign_in(api, world.a_user)
    design = api.get(f"/api/v1/projects/{project_id}/design", headers=headers).json()
    assert (design["context"], design["basePackage"]) == ("payments", "com.bancoficticio.payments")
    assert design["entities"][0]["name"] == "PaymentOrder"
    assert design["entities"][0]["legacyTable"] == "db_pagos..pg_orden"
    (use_case,) = design["useCases"]
    assert (use_case["name"], use_case["httpMethod"], use_case["path"]) == ("PayOrder", "POST", "/orders/pay")
    assert use_case["rules"] == ALL_RULES
    assert len(design["ports"]) == 4
    assert len(design["decisions"]) == 1
    contracts = api.get(f"/api/v1/projects/{project_id}/contracts", headers=headers).json()
    assert contracts["source"] == "openapi"
    assert contracts["openapi"]["openapi"] == "3.1.0"
    expected = {"method": "POST", "path": "/api/payments/orders/pay", "name": "payOrder",
                "summary": use_case["description"] or "PayOrder", "rules": ALL_RULES}  # fmt: skip
    assert contracts["operations"] == [expected]


async def test_without_a_frontend_the_contract_comes_from_the_design(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await _project(owner_engine, app_engine, fga, world, openapi=False)
    headers = sign_in(api, world.a_user)
    contracts = api.get(f"/api/v1/projects/{project_id}/contracts", headers=headers).json()
    assert (contracts["source"], contracts["openapi"]) == ("design", None)
    (operation,) = contracts["operations"]
    assert (operation["method"], operation["name"]) == ("POST", "PayOrder")
    assert operation["path"] == "/api/payments/orders/pay"


async def test_before_the_design_phase_there_is_nothing(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await make_project(owner_engine, world.tenant_a)
    await reconcile(app_engine, fga)
    headers = sign_in(api, world.a_user)
    assert api.get(f"/api/v1/projects/{project_id}/design", headers=headers).json() is None
    assert api.get(f"/api/v1/projects/{project_id}/contracts", headers=headers).json() is None


async def test_the_architecture_of_another_tenant_is_unreachable(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await _project(owner_engine, app_engine, fga, world)
    headers = sign_in(api, world.b_user)
    for suffix in ("/design", "/contracts"):
        assert api.get(f"/api/v1/projects/{project_id}{suffix}", headers=headers).status_code in (403, 404)
