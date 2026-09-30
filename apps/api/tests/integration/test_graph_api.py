"""The knowledge graph through the API (spec 5.2, 5.2.1; plan M6 step 7) with the fictitious CICS application: the
units the Inventario tab draws with their rules, domain and state; the relations; the business flow of a transaction
walked in the order of the code with the rule of each step; impact; and a clear 503 without a graph."""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_api.authz.fga import OpenFga
from nexti_api.authz.reconcile import reconcile
from nexti_api.main import create_app
from nexti_api.settings import Settings
from nexti_graph import GraphStore, Scope

from .conftest import SETTINGS, World
from .run_support import make_project, seed_graph
from .test_runs_api import sign_in

pytestmark = pytest.mark.skipif(not SETTINGS.graph_uri, reason="Neo4j not configured (run init_env.py)")


@pytest.fixture
def api(api_settings: Settings) -> Iterator[TestClient]:
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True}))
    with TestClient(app, base_url="https://testserver") as client:
        yield client


async def seeded(owner: AsyncEngine, app_engine: AsyncEngine, fga: OpenFga, world: World) -> uuid.UUID:
    project_id = await make_project(owner, world.tenant_a)
    await seed_graph(owner, SETTINGS, world.tenant_a, project_id)
    await reconcile(app_engine, fga)
    return project_id


async def forget(tenant: uuid.UUID, project: uuid.UUID) -> None:
    graph = GraphStore.connect(SETTINGS.graph_uri, SETTINGS.graph_user, SETTINGS.graph_password.get_secret_value())
    try:
        await graph.delete_project(Scope(tenant, project))
    finally:
        await graph.close()


async def test_the_graph_has_the_cics_family_with_rules_domains_and_a_walked_flow(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await seeded(owner_engine, app_engine, fga, world)
    headers = sign_in(api, world.a_user)
    try:
        response = api.get(f"/api/v1/projects/{project_id}/graph", headers=headers)
        assert response.status_code == 200, response.text
        graph = response.json()
        nodes = {n["id"]: n for n in graph["nodes"]}
        assert {n["type"] for n in nodes.values()} == {"transaction", "program", "map", "copybook", "file"}
        order = nodes["program:PAGOORD"]
        assert (order["source"], order["loc"], order["state"]) == ("cbl/PAGOORD.cbl:1-192", 192, "inProgress")
        assert {"RULE-001", "RULE-004", "RULE-009"} <= set(order["rules"])
        assert nodes["program:PAGOMOV"]["external"] is True
        assert nodes["file:ORDENES"]["domain"] == "data"
        assert nodes["map:PAGOSET.PAGORES"]["domain"] == nodes["program:PAGOORD"]["domain"]
        assert not any(n["orphan"] for n in nodes.values())
        edges = {(e["from"], e["kind"], e["to"], e["detail"]) for e in graph["edges"]}
        assert ("program:PAGOORD", "CALLS", "program:PAGODEB", "LINK") in edges
        assert ("tx:PGOR", "STARTS", "program:PAGOORD", None) in edges
        assert [r["id"] for r in graph["rules"]][:2] == ["RULE-001", "RULE-002"]

        flow = next(f for f in graph["flows"] if f["entry"] == "tx:PGOR")
        kinds = [(s["kind"], s["nodes"][-1]) for s in flow["steps"]]
        assert kinds[0] == ("start", "program:PAGOORD")
        assert ("call", "program:PAGODEB") in kinds
        assert kinds.index(("read", "file:CUENTAS")) > kinds.index(("call", "program:PAGODEB"))  # walked into
        assert kinds[-1] == ("transfer", "program:PAGOMNU")
        read = next(s for s in flow["steps"] if s["kind"] == "read" and s["nodes"][-1] == "file:ORDENES")
        assert read["rule"] == "RULE-004"
        assert {"RULE-004", "RULE-007", "RULE-009"} <= set(flow["rules"])

        impact = api.get(f"/api/v1/projects/{project_id}/graph/impact",
                         params={"node": "copybook:ORDREG", "depth": 2}, headers=headers)  # fmt: skip
        assert impact.status_code == 200, impact.text
        assert {"program:PAGOORD", "tx:PGOR"} <= set(impact.json()["impacted"])
        missing = api.get(f"/api/v1/projects/{project_id}/graph/impact", params={"node": "program:NADA"},
                          headers=headers)  # fmt: skip
        assert missing.status_code == 404
    finally:
        await forget(world.tenant_a, project_id)


async def test_without_a_graph_the_api_says_so(
    api_settings: Settings, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    project_id = await make_project(owner_engine, world.tenant_a)
    await reconcile(app_engine, fga)
    app = create_app(api_settings.model_copy(update={"dev_auth_enabled": True, "graph_uri": ""}))
    with TestClient(app, base_url="https://testserver") as client:
        headers = sign_in(client, world.a_user)
        response = client.get(f"/api/v1/projects/{project_id}/graph", headers=headers)
    assert (response.status_code, response.json()["code"]) == (503, "graph_unavailable")
