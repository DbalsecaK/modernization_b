"""The knowledge graph against the local Neo4j (spec 5): the inventory of the fictitious application becomes the
code layer; impact, orphans and shared tables are answered inside one project; two tenants never see each other.
Skipped when the local services are not configured (infra/docker-compose/init_env.py)."""

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nexti_adapter_sybase import SybaseAdapter
from nexti_core.adapters import Edge, Node, SourceFile
from nexti_graph import GraphError, GraphStore, Scope

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "packages/adapters/source/sybase/tests/fixtures/pago_orden/sp_pago_orden.sp"


def _settings() -> dict[str, str]:
    values = {k: v for k, v in os.environ.items() if k.startswith("GRAPH_")}
    env = ROOT / "apps" / "worker" / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.startswith("GRAPH_"):
                values.setdefault(name, value)
    return values


SETTINGS = _settings()
pytestmark = pytest.mark.skipif(not SETTINGS.get("GRAPH_URI"), reason="Neo4j not configured (run init_env.py)")


@pytest.fixture
async def graph() -> AsyncIterator[GraphStore]:
    store = GraphStore.connect(SETTINGS["GRAPH_URI"], SETTINGS["GRAPH_USER"], SETTINGS["GRAPH_PASSWORD"])
    await store.setup()
    yield store
    await store.close()


@pytest.fixture
async def scopes(graph: GraphStore) -> AsyncIterator[tuple[Scope, Scope]]:
    a = Scope(uuid.uuid4(), uuid.uuid4())
    b = Scope(uuid.uuid4(), uuid.uuid4())
    yield a, b
    for scope in (a, b):
        await graph.delete_project(scope)


async def test_the_inventory_becomes_the_code_layer_of_the_project(
    graph: GraphStore, scopes: tuple[Scope, Scope]
) -> None:
    scope, _ = scopes
    inventory = SybaseAdapter().inventory([SourceFile("sp_pago_orden.sp", FIXTURE.read_text(encoding="utf-8"))])
    await graph.replace_code_layer(scope, inventory)
    procedures = await graph.nodes(scope, "StoredProcedure")
    assert {p.key for p in procedures} == {
        "proc:dbo.sp_pago_orden", "proc:db_cuentas..sp_debito", "proc:cobis..sp_cerror",
    }  # fmt: skip
    main = next(p for p in procedures if p.key == "proc:dbo.sp_pago_orden")
    assert (main.properties["file"], main.properties["line_start"]) == ("sp_pago_orden.sp", 6)
    edges = set(await graph.edges(scope))
    assert ("proc:dbo.sp_pago_orden", "WRITES", "table:db_pagos..pg_orden") in edges
    assert ("proc:dbo.sp_pago_orden", "CALLS", "proc:db_cuentas..sp_debito") in edges
    # Rebuilding the code layer replaces it: no duplicates.
    await graph.replace_code_layer(scope, inventory)
    assert len(await graph.nodes(scope, "StoredProcedure")) == 3


async def test_impact_orphans_and_shared_tables(graph: GraphStore, scopes: tuple[Scope, Scope]) -> None:
    scope, _ = scopes
    await graph.upsert_nodes(scope, [
        Node("proc:alta", "StoredProcedure", "alta"), Node("proc:pago", "StoredProcedure", "pago"),
        Node("proc:reporte", "StoredProcedure", "reporte"), Node("proc:muerto", "StoredProcedure", "muerto"),
        Node("table:orden", "Table", "orden"), Node("table:suelta", "Table", "suelta"),
    ])  # fmt: skip
    await graph.upsert_edges(scope, [
        Edge("proc:alta", "WRITES", "table:orden"), Edge("proc:pago", "READS", "table:orden"),
        Edge("proc:pago", "WRITES", "table:orden"), Edge("proc:reporte", "CALLS", "proc:pago"),
    ])  # fmt: skip
    assert await graph.impact(scope, "table:orden", depth=2) == ["proc:alta", "proc:pago", "proc:reporte"]
    assert await graph.orphans(scope) == ["proc:muerto", "table:suelta"]
    shared = await graph.shared_tables(scope, ["proc:alta", "proc:pago"])
    assert ("proc:alta", "proc:pago", "table:orden") in shared
    with pytest.raises(GraphError):
        await graph.impact(scope, "table:orden", depth=9)


async def test_two_tenants_never_see_each_other(graph: GraphStore, scopes: tuple[Scope, Scope]) -> None:
    a, b = scopes
    await graph.upsert_nodes(a, [Node("table:orden", "Table", "orden de A")])
    await graph.upsert_nodes(b, [Node("table:orden", "Table", "orden de B")])
    assert [n.name for n in await graph.nodes(a)] == ["orden de A"]
    assert [n.name for n in await graph.nodes(b)] == ["orden de B"]
    # An edge can only join nodes of the same project.
    await graph.upsert_nodes(a, [Node("proc:x", "StoredProcedure", "x")])
    await graph.upsert_edges(b, [Edge("proc:x", "READS", "table:orden")])
    assert await graph.edges(b) == []


async def test_labels_and_relationship_types_come_from_closed_lists(
    graph: GraphStore, scopes: tuple[Scope, Scope]
) -> None:
    scope, _ = scopes
    with pytest.raises(GraphError):
        await graph.nodes(scope, "Table) DETACH DELETE (n")
    with pytest.raises(GraphError):
        await graph.upsert_edges(scope, [Edge("a", "READS]->(b) DELETE b//", "b")])  # type: ignore[arg-type]


async def test_the_cics_family_in_the_graph(graph: GraphStore, scopes: tuple[Scope, Scope]) -> None:
    """Transaction -> Program -> Map with copybooks and files (M6): a copybook change reaches the programs that copy
    it and the transactions that start them; an unused copybook is an orphan; edges keep their properties."""
    from nexti_adapter_cobol import CobolAdapter

    fixtures = ROOT / "packages/adapters/source/cobol/tests/fixtures/pagos_cics"
    files = [SourceFile(p.relative_to(fixtures).as_posix(), p.read_text(encoding="utf-8"))
             for p in sorted(fixtures.rglob("*")) if p.suffix in (".cbl", ".cpy", ".csd", ".bms")]  # fmt: skip
    files.append(SourceFile("cpy/SINUSO.cpy", "       01  SIN-USO  PIC X.\n"))
    scope, _ = scopes
    await graph.replace_code_layer(scope, CobolAdapter().inventory(files))
    impact = await graph.impact(scope, "copybook:ORDREG", depth=2)
    assert {"program:PAGOORD", "tx:PGOR"} <= set(impact)
    assert "copybook:SINUSO" in await graph.orphans(scope)
    assert "program:PAGOORD" not in await graph.orphans(scope)
    calls = [r for r in await graph.relationships(scope) if r["type"] == "CALLS" and r["target"] == "program:PAGODEB"]
    assert calls[0]["props"]["kind"] == "LINK"
