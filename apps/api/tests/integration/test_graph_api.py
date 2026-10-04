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
from .run_support import CICS_FIXTURES, make_project, seed_graph
from .test_acceptance_m4 import object_store, upload_source
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
        # What each unit really is, so the tab counts what the inventory found (not the columns of the drawing).
        assert (order["kind"], nodes["file:ORDENES"]["kind"], nodes["map:PAGOSET.PAGORES"]["kind"]) == (
            "Program", "File", "BmsMap")  # fmt: skip
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


async def test_the_source_target_view_shows_cobol_lines_rule_by_rule(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    """The traceability viewer (plan M6 step 9) on COBOL: a rule cited in two programs shows both legacy excerpts
    from the uploaded archive, each with the cited lines highlighted."""
    project_id = await seeded(owner_engine, app_engine, fga, world)
    sources = {p.relative_to(CICS_FIXTURES).as_posix(): p.read_bytes() for p in sorted(CICS_FIXTURES.rglob("*"))
               if p.suffix in (".cbl", ".cpy", ".csd", ".bms")}  # fmt: skip
    await upload_source(owner_engine, object_store(), world.tenant_a, project_id, sources)
    headers = sign_in(api, world.a_user)
    try:
        listed = api.get(f"/api/v1/projects/{project_id}/traceability", headers=headers)
        assert listed.status_code == 200, listed.text
        rule = next(r for r in listed.json() if r["key"] == "RULE-007")
        assert rule["sources"] == ["cbl/PAGODEB.cbl:18-32", "cbl/PAGOORD.cbl:144-159"]
        detail = api.get(f"/api/v1/projects/{project_id}/traceability/RULE-007", headers=headers).json()
        excerpts = {e["path"]: e for e in detail["legacy"]}
        assert set(excerpts) == {"cbl/PAGODEB.cbl", "cbl/PAGOORD.cbl"}
        debit = excerpts["cbl/PAGODEB.cbl"]
        assert debit["highlighted"] == list(range(18, 33))
        assert any("EXEC CICS READ FILE('CUENTAS')" in line for line in debit["lines"])
        assert detail["verdict"] is None  # nothing verified yet
        assert detail["target"] == []
    finally:
        await forget(world.tenant_a, project_id)


SYBASE_FIXTURE = CICS_FIXTURES.parents[3] / "sybase/tests/fixtures/pago_orden/sp_pago_orden.sp"


async def test_a_stored_procedure_shows_its_blocks_their_phases_and_jumps(
    api: TestClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, fga: OpenFga, world: World
) -> None:
    """Blocks inside a unit (plan M17 step 2): the inventory of the fictitious procedure as the worker stores it."""
    from nexti_adapter_sybase import SybaseAdapter
    from nexti_core.adapters import SourceFile

    project_id = await make_project(owner_engine, world.tenant_a)
    inventory = SybaseAdapter().inventory([SourceFile("sp_pago_orden.sp", SYBASE_FIXTURE.read_text(encoding="utf-8"))])
    graph = GraphStore.connect(SETTINGS.graph_uri, SETTINGS.graph_user, SETTINGS.graph_password.get_secret_value())
    try:
        await graph.setup()
        await graph.replace_code_layer(Scope(world.tenant_a, project_id), inventory)
    finally:
        await graph.close()
    await reconcile(app_engine, fga)
    headers = sign_in(api, world.a_user)
    try:
        response = api.get(f"/api/v1/projects/{project_id}/graph", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        nodes = {n["id"]: n for n in body["nodes"]}
        proc, b = "proc:dbo.sp_pago_orden", "block:dbo.sp_pago_orden#B"
        blocks = [n for n in body["nodes"] if n["kind"] == "Block"]
        assert len(blocks) == 10
        assert all(n["parent"] == proc and n["type"] == "program" for n in blocks)
        phases = [nodes[f"{b}{n}"]["phase"] for n in (1, 6, 9, 10)]
        assert phases == ["pre", "transaction", "post", "error"]
        assert (nodes[proc]["parent"], nodes[proc]["phase"], nodes[proc]["schemaKnown"]) == (None, None, None)
        assert nodes["table:db_pagos..pg_orden"]["schemaKnown"] is False  # no DDL in the inputs
        edges = {(e["from"], e["kind"], e["to"]) for e in body["edges"]}
        assert {(proc, "CONTAINS", f"{b}1"), (f"{b}1", "NEXT", f"{b}2"), (f"{b}5", "GOTO", f"{b}10"),
                (f"{b}8", "ON_ERROR", f"{b}10"), (proc, "WRITES", "table:db_pagos..pg_orden")} <= edges  # fmt: skip
        relations = sum(1 for e in body["edges"] if e["kind"] != "CONTAINS")
        assert body["summary"] == {"modules": 11, "stores": 4, "relations": relations, "entryPoints": 1}
        assert [f["entry"] for f in body["flows"]] == [proc]
        assert not any(n["orphan"] for n in blocks)
        impact = api.get(f"/api/v1/projects/{project_id}/graph/impact",
                         params={"node": "table:db_pagos..pg_orden", "depth": 1}, headers=headers)  # fmt: skip
        assert impact.json()["impacted"] == [proc]  # a block lifts to its procedure
    finally:
        await forget(world.tenant_a, project_id)
