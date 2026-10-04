"""Logical blocks inside a stored procedure (ADR-0032): cuts, names, phases, tables and the edges between blocks, on
the fictitious reference procedure and on small synthetic procedures written here."""

from pathlib import Path

from nexti_adapter_sybase import SybaseAdapter, parse
from nexti_adapter_sybase.blocks import LARGE_BRANCH, Block, BlockEdge, blocks
from nexti_core.adapters import SourceFile

FIXTURE = Path(__file__).parent / "fixtures" / "pago_orden" / "sp_pago_orden.sp"
SOURCE = FIXTURE.read_text(encoding="utf-8")

SYNTHETIC = """create procedure dbo.sp_demo @p int as
declare @w_error int, @w_total money
------------------------------------------------
-- B1 Validate the input
------------------------------------------------
if @p is null
begin
    select @w_error = 1
    goto FAIL
end
select @w_total = sum(amount) from t_input where id = @p
select @w_total = @w_total * 2
select @w_total = @w_total + 1
/****************************************
 * B2 Post the movement
 ****************************************/
begin tran
insert into t_move (id, total) values (@p, @w_total)
if @@error <> 0
begin
    rollback tran
    goto FAIL
end
update t_balance set total = total + @w_total where id = @p
select @w_error = @@error
if @w_error <> 0
    goto FAIL
exec sp_audit @p
commit tran
-- B3 Done
select @w_error = 0
return 0
FAIL:
exec sp_log @w_error
return 1
go
"""


def line_of(source: str, text: str) -> int:
    return next(n for n, line in enumerate(source.splitlines(), start=1) if text in line)


def cut(source: str) -> tuple[list[Block], list[BlockEdge]]:
    (procedure,) = parse(source)
    return blocks(procedure)


def edges_of(found: list[BlockEdge]) -> set[tuple[str, str, str]]:
    return {(e.source.split("#")[1], e.kind, e.target.split("#")[1]) for e in found}


def test_banners_transactions_and_labels_cut_the_synthetic_procedure() -> None:
    found, _ = cut(SYNTHETIC)
    summary = [(b.id, b.name, b.phase) for b in found]
    assert summary == [
        ("dbo.sp_demo#B1", "B1 Validate the input", "pre"),
        ("dbo.sp_demo#B2", "B2 Post the movement", "transaction"),
        ("dbo.sp_demo#B3", "B3 Done", "post"),
        ("dbo.sp_demo#B4", "FAIL", "error"),
    ]
    first, post, done, fail = found
    # The tiny declarations join the first section; a section starts at its banner and ends at its last statement.
    assert (first.line_start, first.line_end) == (2, line_of(SYNTHETIC, "@w_total + 1"))
    assert (post.line_start, post.line_end) == (line_of(SYNTHETIC, "/****"), line_of(SYNTHETIC, "commit tran"))
    assert (done.line_start, fail.line_start) == (line_of(SYNTHETIC, "-- B3"), line_of(SYNTHETIC, "FAIL:"))
    assert first.reads == {"t_input"}
    assert not first.writes
    assert post.writes == {"t_move", "t_balance"}
    assert post.calls == ["sp_audit"]
    assert fail.calls == ["sp_log"]
    assert fail.label == "FAIL"


def test_the_edges_follow_the_code_jumps_and_error_exits() -> None:
    _, found = cut(SYNTHETIC)
    assert edges_of(found) == {
        ("B1", "NEXT", "B2"), ("B2", "NEXT", "B3"),  # no NEXT after `return 0`: B3 never falls into FAIL
        ("B1", "GOTO", "B4"),  # a validation, not an error check
        ("B2", "ON_ERROR", "B4"),  # after @@error and ROLLBACK, and after the copied error code
    }  # fmt: skip
    # One edge per pair of blocks, at the first jump.
    assert [e.line for e in found if e.kind == "ON_ERROR"] == [line_of(SYNTHETIC, "rollback tran") + 1]


def test_the_reference_procedure_has_its_rule_sections_as_blocks() -> None:
    found, links = cut(SOURCE)
    assert [b.id for b in found] == [f"dbo.sp_pago_orden#B{n}" for n in range(1, 11)]
    assert [b.phase for b in found] == ["pre"] * 5 + ["transaction"] * 3 + ["post", "error"]
    assert found[1].name.startswith("RF-02")
    assert found[1].reads == {"db_pagos..pg_orden"}
    assert found[3].name.startswith("RF-04")  # RF-05 is tiny: it joined RF-04
    assert (found[3].line_start, found[3].line_end) == (79, 92)
    assert (found[5].name, found[5].line_start, found[5].calls) == ("Statements 108-123", 108,
                                                                    ["db_cuentas..sp_debito"])  # fmt: skip
    assert found[7].writes == {"db_pagos..pg_orden"}
    assert found[7].line_end == 161
    assert (found[9].name, found[9].line_start, found[9].line_end) == ("ERROR", 166, 171)
    pairs = edges_of(links)
    assert ("B8", "NEXT", "B9") in pairs
    assert ("B9", "NEXT", "B10") not in pairs
    assert {("B1", "GOTO", "B10"), ("B5", "GOTO", "B10")} <= pairs  # business validations
    assert {("B2", "ON_ERROR", "B10"), ("B6", "ON_ERROR", "B10"), ("B7", "ON_ERROR", "B10"),
            ("B8", "ON_ERROR", "B10")} <= pairs  # fmt: skip
    # Deterministic: the same code gives the same blocks.
    assert [(b.id, b.line_start, b.line_end) for b in cut(SOURCE)[0]] == [(b.id, b.line_start, b.line_end)
                                                                          for b in found]  # fmt: skip


def test_a_long_branch_is_a_block_of_its_own_and_one_body_block_is_unwrapped() -> None:
    body = "\n".join(f"    select @w_total = @w_total + {n}" for n in range(LARGE_BRANCH + 2))
    source = (
        "create procedure sp_long @p int as\nbegin\ndeclare @w_total int\nselect @w_total = 0\n"
        "select @w_total = @w_total + @p\nselect @w_total = @w_total * 2\nselect @w_total = @w_total - 1\n"
        "select @w_total = @w_total + 3\nselect @w_total = @w_total + 4\nselect @w_total = @w_total + 5\n"
        f"if @p > 0\nbegin\n{body}\nend\nselect @p = @w_total\nselect @p = @p + 1\nreturn @p\nend\n"
    )
    found, links = cut(source)
    names = [b.name for b in found]
    start = line_of(source, "if @p > 0")
    assert names == ["Statements 3-10", f"Statements {start}-{start + LARGE_BRANCH + 7}"]  # the tail is tiny
    assert edges_of(links) == {("B1", "NEXT", "B2")}


def test_the_inventory_adds_blocks_without_touching_the_procedure_or_the_digest() -> None:
    adapter = SybaseAdapter()
    files = [SourceFile("sp_pago_orden.sp", SOURCE)]
    inventory = adapter.inventory(files)
    block_nodes = [n for n in inventory.nodes if n.label == "Block"]
    assert len(block_nodes) == 10
    first = block_nodes[0]
    assert (first.key, first.file, first.properties["phase"], first.properties["unit"]) == (
        "block:dbo.sp_pago_orden#B1", "sp_pago_orden.sp", "pre", "proc:dbo.sp_pago_orden")  # fmt: skip
    edges = {(e.source, e.type, e.target) for e in inventory.edges}
    assert ("proc:dbo.sp_pago_orden", "CONTAINS", "block:dbo.sp_pago_orden#B1") in edges
    assert ("block:dbo.sp_pago_orden#B8", "WRITES", "table:db_pagos..pg_orden") in edges
    assert ("block:dbo.sp_pago_orden#B6", "CALLS", "proc:db_cuentas..sp_debito") in edges
    assert ("block:dbo.sp_pago_orden#B6", "ON_ERROR", "block:dbo.sp_pago_orden#B10") in edges
    assert len(edges) == len(inventory.edges)  # one edge per pair
    # The procedure keeps its own edges, before every block edge, and the digest the prompts read has no blocks.
    proc_edges = [e for e in inventory.edges if e.source == "proc:dbo.sp_pago_orden" and e.type != "CONTAINS"]
    assert inventory.edges[: len(proc_edges)] == proc_edges
    assert "block" not in adapter.digest(files).lower()
    assert "blocks" not in inventory.metrics


def test_a_table_is_known_only_when_its_ddl_is_in_the_inputs() -> None:
    ddl = SourceFile("ddl/pg_orden.sql", "use db_pagos\ngo\ncreate table dbo.pg_orden (ord_numero int not null)\ngo\n")
    inventory = SybaseAdapter().inventory([SourceFile("sp_pago_orden.sp", SOURCE), ddl])
    known = {n.name: n.properties["schema_known"] for n in inventory.nodes if n.label == "Table"}
    assert known["db_pagos..pg_orden"] is True
    assert known["db_cuentas..ct_cuenta"] is False
    assert inventory.metrics["tables"] == 4  # the DDL adds no table of its own
