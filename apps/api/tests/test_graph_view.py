"""The graph view with blocks (ADR-0032, plan M17 section 1), from the inventory of the fictitious Sybase procedure as
the graph store returns it: blocks with their unit and phase, the edges between blocks, CONTAINS for nesting,
`schemaKnown` on tables and the summary; the flows are still walked from the units."""

from pathlib import Path
from typing import Any

from nexti_adapter_sybase import SybaseAdapter
from nexti_api.graph.router import GraphOut
from nexti_api.graph.view import RuleRef, build, lift
from nexti_core.adapters import Inventory, SourceFile
from nexti_graph import GraphNode

FIXTURE = Path(__file__).parents[3] / "packages/adapters/source/sybase/tests/fixtures/pago_orden/sp_pago_orden.sp"
PROC = "proc:dbo.sp_pago_orden"
DDL = SourceFile("ddl/pg_orden.sql", "create table pg_orden (ord_numero int not null)\ngo\n")


def as_stored(inventory: Inventory) -> tuple[list[GraphNode], list[dict[str, Any]]]:
    """What GraphStore.nodes and GraphStore.relationships return for this inventory."""
    nodes = [
        GraphNode(n.key, (n.label,), n.name, {**{k: v for k, v in n.properties.items() if v is not None},
                                              "file": n.file, "line_start": n.line_start, "line_end": n.line_end})
        for n in inventory.nodes
    ]  # fmt: skip
    edges = [{"source": e.source, "type": e.type, "target": e.target, "props": dict(e.properties)}
             for e in inventory.edges]  # fmt: skip
    return nodes, edges


def view() -> dict[str, Any]:
    inventory = SybaseAdapter().inventory([SourceFile("sp_pago_orden.sp", FIXTURE.read_text(encoding="utf-8")), DDL])
    nodes, edges = as_stored(inventory)
    rules = [RuleRef("RULE-008", "Order paid", "P0", (("sp_pago_orden.sp", 144, 149),))]
    return build(nodes, edges, [], rules, set(), False)


def test_blocks_are_nodes_of_their_unit_with_their_phase() -> None:
    graph = view()
    nodes = {n["id"]: n for n in graph["nodes"]}
    blocks = [n for n in graph["nodes"] if n["kind"] == "Block"]
    assert len(blocks) == 10
    assert all(b["type"] == "program" and b["parent"] == PROC for b in blocks)
    assert {b["phase"] for b in blocks} == {"pre", "transaction", "post", "error"}
    paid = nodes["block:dbo.sp_pago_orden#B8"]
    assert (paid["phase"], paid["line_start"], paid["line_end"], paid["rules"]) == ("transaction", 143, 161,
                                                                                   ["RULE-008"])  # fmt: skip
    assert paid["domain"] == nodes[PROC]["domain"]
    assert nodes["block:dbo.sp_pago_orden#B10"]["name"] == "ERROR"
    unit = nodes[PROC]
    assert (unit["parent"], unit["phase"], unit["schema_known"]) == (None, None, None)


def test_the_edges_between_blocks_and_contains_are_in_the_list() -> None:
    edges = {(e["from"], e["kind"], e["to"]) for e in view()["edges"]}
    b = "block:dbo.sp_pago_orden#B"
    assert (PROC, "CONTAINS", f"{b}1") in edges
    assert {(f"{b}1", "NEXT", f"{b}2"), (f"{b}1", "GOTO", f"{b}10"), (f"{b}6", "ON_ERROR", f"{b}10")} <= edges
    assert (f"{b}9", "NEXT", f"{b}10") not in edges
    # The unit keeps its own edges.
    assert (PROC, "WRITES", "table:db_pagos..pg_orden") in edges
    assert (PROC, "CALLS", "proc:db_cuentas..sp_debito") in edges


def test_tables_say_whether_their_ddl_is_in_the_inputs() -> None:
    nodes = {n["id"]: n for n in view()["nodes"]}
    assert nodes["table:db_pagos..pg_orden"]["schema_known"] is True
    assert nodes["table:db_cuentas..ct_cuenta"]["schema_known"] is False


def test_the_summary_and_the_flows_count_units_not_blocks() -> None:
    graph = view()
    # 1 procedure + 10 blocks (the two called procedures are external), 4 tables, 1 entry point.
    edges = [e for e in graph["edges"] if e["kind"] != "CONTAINS"]
    assert graph["summary"] == {"modules": 11, "stores": 4, "relations": len(edges), "entryPoints": 1}
    (flow,) = graph["flows"]
    assert flow["entry"] == PROC
    assert all(not node.startswith("block:") for step in flow["steps"] for node in step["nodes"])
    out = GraphOut.model_validate(graph).model_dump(by_alias=True)
    assert out["summary"]["entryPoints"] == 1
    assert next(n for n in out["nodes"] if n["id"] == "table:db_pagos..pg_orden")["schemaKnown"] is True
    assert next(n for n in out["nodes"] if n["id"] == f"{PROC}")["phase"] is None


def test_impact_lifts_a_block_to_its_procedure() -> None:
    assert lift(["block:dbo.sp_pago_orden#B8", "table:x"], {PROC}) == [PROC]
