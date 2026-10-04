"""The model-written insights of the graph through the API (ADR-0032): descriptions, observations and scenarios as
the deep inventory stored them, the newest run winning; everything empty before (or without) a deep inventory;
another tenant reaches nothing."""

import hashlib
import io
import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings

from .conftest import World
from .run_support import execute, make_config, make_project, make_run
from .test_runs_api import configured_project, sign_in
from .test_validation_api import store

SCENARIO = {
    "id": "scenario:1", "name": "A company pays an order", "persona": "Company treasurer",
    "summary": "The order is paid from the company account.", "rules": ["RULE-001"],
    "steps": [{"title": "Check the order", "nodes": ["proc:dbo.sp_pago_orden"], "rule": "RULE-001"},
              {"title": "Mark it paid", "nodes": ["table:db_pagos..pg_orden"], "rule": None}],
}  # fmt: skip


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def seed_insights(
    owner: AsyncEngine, tenant_id: uuid.UUID, project_id: uuid.UUID, documents: dict[str, Any]
) -> None:
    """What a run with `deep_inventory` stores: one generated artifact per insight (path -> document)."""
    version = await make_config(owner, tenant_id, project_id)
    run_id = await make_run(owner, tenant_id, project_id, version, kind="pipeline")
    for path, document in documents.items():
        data = json.dumps(document).encode("utf-8")
        key = f"tenants/{tenant_id}/projects/{project_id}/runs/{run_id}/files/{path}"
        await store().put(key, io.BytesIO(data), len(data), "application/json")
        await execute(
            owner,
            "INSERT INTO generated_artifact (tenant_id, project_id, run_id, layer, path, object_key, sha256, "
            "size_bytes) VALUES (:t, :p, :r, 'docs', :path, :k, :h, :s)",
            t=tenant_id, p=project_id, r=run_id, path=path, k=key, h=hashlib.sha256(data).hexdigest(), s=len(data),
        )  # fmt: skip


def _documents(description: str) -> dict[str, Any]:
    return {
        "inventory/descriptions.json": {"origin": "model", "agent": "legacy-analyst",
                                        "descriptions": {"proc:dbo.sp_pago_orden": description}},
        "inventory/observations.json": {"origin": "model", "agent": "legacy-analyst",
                                        "observations": ["The procedure writes one table.", "Two external calls."]},
        "inventory/scenarios.json": {"origin": "model", "agent": "functional-analyst", "scenarios": [SCENARIO]},
    }  # fmt: skip


async def test_the_insights_of_the_newest_deep_inventory_come_in_camel_case(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await make_project(owner_engine, world.tenant_a)
    await seed_insights(owner_engine, world.tenant_a, project_id, _documents("An older description."))
    await seed_insights(owner_engine, world.tenant_a, project_id, _documents("Pays a company order."))
    await reconcile(app_engine, fga)
    found = api.get(f"/api/v1/projects/{project_id}/graph/insights", headers=sign_in(api, world.a_user))
    assert found.status_code == 200, found.text
    insights = found.json()
    assert insights["descriptions"] == {"proc:dbo.sp_pago_orden": "Pays a company order."}
    assert insights["observations"] == ["The procedure writes one table.", "Two external calls."]
    assert insights["scenarios"] == [SCENARIO]


async def test_another_tenant_reaches_no_insights(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await make_project(owner_engine, world.tenant_a)
    await seed_insights(owner_engine, world.tenant_a, project_id, _documents("Pays a company order."))
    await reconcile(app_engine, fga)
    other = api.get(f"/api/v1/projects/{project_id}/graph/insights", headers=sign_in(api, world.b_user))
    assert other.status_code in (403, 404)
    assert "Pays a company order" not in other.text


async def test_without_a_deep_inventory_everything_is_empty(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await make_project(owner_engine, world.tenant_a)
    await reconcile(app_engine, fga)
    found = api.get(f"/api/v1/projects/{project_id}/graph/insights", headers=sign_in(api, world.a_user))
    assert found.json() == {"descriptions": {}, "observations": [], "scenarios": []}


async def test_a_pipeline_a_person_starts_reads_the_inventory_in_depth_unless_they_opt_out(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    headers = sign_in(api, world.a_user)
    deep = await configured_project(owner_engine, world)
    shallow = await configured_project(owner_engine, world)
    await reconcile(app_engine, fga)
    started = api.post(f"/api/v1/projects/{deep}/runs", json={"kind": "pipeline"}, headers=headers)
    assert started.status_code == 201, started.text
    assert started.json()["options"] == {"deep_inventory": True}
    opted_out = api.post(f"/api/v1/projects/{shallow}/runs", json={"kind": "pipeline", "deepInventory": False},
                         headers=headers)  # fmt: skip
    assert opted_out.json()["options"] == {"deep_inventory": False}
