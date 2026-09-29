"""The Sybase adapter on the fictitious reference application (spec 8.2): header, statements with exact lines,
tables, calls, neutral types, classification and slices."""

from pathlib import Path

import pytest

from nexti_adapter_sybase import SybaseAdapter, backward_slice, classify, parse, slice_targets, to_neutral
from nexti_adapter_sybase.lexer import tokenize
from nexti_adapter_sybase.parser import Procedure
from nexti_core.adapters import SourceFile

FIXTURE = Path(__file__).parent / "fixtures" / "pago_orden" / "sp_pago_orden.sp"
SOURCE = FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def proc() -> Procedure:
    (procedure,) = parse(SOURCE)
    return procedure


def at(proc: Procedure, line: int) -> int:
    """The id of the innermost statement that starts on `line`."""
    return max(s.id for s in proc.statements() if s.line_start == line)


def test_the_header_has_the_parameters_with_types_defaults_and_output(proc: Procedure) -> None:
    assert proc.name == "dbo.sp_pago_orden"
    assert (proc.line_start, proc.line_end) == (6, 171)
    names = [p.name for p in proc.parameters]
    assert names[:3] == ["@i_orden", "@i_empresa", "@i_servicio"]
    by_name = {p.name: p for p in proc.parameters}
    assert by_name["@i_canal"].type == "char(3)"
    assert by_name["@i_canal"].default == "'WEB'"
    assert by_name["@o_mensaje"].output
    assert not by_name["@i_valor"].output
    assert by_name["@i_valor"].line == 13


def test_statements_know_their_lines_tables_and_calls(proc: Procedure) -> None:
    statements = proc.statements()
    kinds = {s.kind for s in statements}
    assert {"declare", "select", "if", "goto", "begin_tran", "exec", "rollback", "update", "commit", "label",
            "return"} <= kinds  # fmt: skip
    update = next(s for s in statements if s.kind == "update")
    assert (update.line_start, update.line_end) == (144, 149)
    assert update.writes == {"db_pagos..pg_orden"}
    assert {"@i_orden", "@i_empresa", "@i_fecha_proceso", "@w_comision"} <= update.vars_read
    order = next(s for s in statements if s.kind == "select" and s.line_start == 42)
    assert order.reads == {"db_pagos..pg_orden"}
    assert order.vars_written == {"@w_estado"}
    debit = next(s for s in statements if s.kind == "exec" and s.line_start == 110)
    assert debit.calls == ["db_cuentas..sp_debito"]
    assert {"@w_return", "@o_movimiento"} <= debit.vars_written
    error = next(s for s in statements if s.kind == "select" and s.line_start == 151)
    assert error.checks_error
    label = next(s for s in statements if s.kind == "label")
    assert (label.label, label.line_start) == ("ERROR", 166)


def test_if_else_nests_and_conditions_keep_their_lines(proc: Procedure) -> None:
    channel = next(s for s in proc.statements() if s.kind == "if" and s.line_start == 80)
    assert channel.condition_lines == (80, 80)
    assert [c.line_start for c in channel.children] == [81]
    assert [c.line_start for c in channel.orelse] == [83]
    balance = next(s for s in proc.statements() if s.kind == "if" and s.line_start == 100)
    assert balance.condition_lines == (100, 101)


def test_neutral_types() -> None:
    assert str(to_neutral("money").neutral) == "decimal(19,4,signed)"
    assert str(to_neutral("char(10)").neutral) == "text(fixed,10,iso8859-1)"
    assert str(to_neutral("varchar(120)").neutral) == "text(var,120,iso8859-1)"
    assert str(to_neutral("datetime").neutral) == "timestamp(local)"
    assert str(to_neutral("numeric(12,2)").neutral) == "decimal(12,2,signed)"
    assert str(to_neutral("tinyint").neutral) == "integer(8,unsigned)"
    assert not to_neutral("cuenta").resolved
    assert str(to_neutral("cuenta", {"cuenta": "char(10)"}).neutral) == "text(fixed,10,iso8859-1)"


def test_classification_separates_infrastructure_control_and_business(proc: Procedure) -> None:
    hints = {h.statement: h.label for h in classify(proc)}
    assert hints[at(proc, 108)] == "infrastructure"  # begin tran
    assert hints[at(proc, 167)] == "infrastructure"  # error log call
    assert hints[at(proc, 47)] == "infrastructure"  # if @@rowcount = 0
    assert hints[at(proc, 80)] == "control_flow"
    assert hints[at(proc, 81)] == "business"  # half tariff for WEB
    assert hints[at(proc, 144)] == "business"  # update of the order


def test_the_slice_of_the_order_update_follows_the_commission_back_to_the_tariff(proc: Procedure) -> None:
    cut = backward_slice(proc, at(proc, 144))
    covered = {line for start, end in cut.lines for line in range(start, end + 1)}
    assert {144, 148, 81, 83, 86, 62, 70, 77} <= covered  # update, commission, tariff
    assert 34 not in covered  # the account type check does not feed the update
    assert cut.parameters == ["@i_canal", "@i_empresa", "@i_fecha_proceso", "@i_orden", "@i_servicio"]
    assert "db_admin..ad_tarifa_empresa" in cut.tables


def test_slice_targets_are_the_business_outcomes(proc: Procedure) -> None:
    targets = {s.line_start for s in proc.statements() if s.id in slice_targets(proc)}
    assert {110, 128, 144} <= targets
    assert 167 not in targets  # the error log is infrastructure


def test_the_adapter_contract() -> None:
    files = [SourceFile("sp_pago_orden.sp", SOURCE), SourceFile("README.md", "not sql")]
    adapter = SybaseAdapter()
    assert adapter.detect(files) >= 0.9
    assert adapter.detect([SourceFile("a.cbl", "IDENTIFICATION DIVISION.")]) == 0.0
    inventory = adapter.inventory(files)
    assert inventory.problems == []
    assert inventory.metrics["procedures"] == 1
    assert inventory.metrics["tables"] == 4
    labels = {(n.label, n.name) for n in inventory.nodes}
    assert ("Table", "db_admin..ad_tarifa_empresa") in labels
    assert ("StoredProcedure", "db_cuentas..sp_debito") in labels
    writes = {(e.source, e.target) for e in inventory.edges if e.type == "WRITES"}
    assert writes == {("proc:dbo.sp_pago_orden", "table:db_pagos..pg_orden")}
    types = adapter.types(files)
    assert types["money"] == "decimal(19,4,signed)"
    assert types["varchar(120)"] == "text(var,120,iso8859-1)"
    slices = adapter.slices(files)
    assert slices
    assert all(view.file == "sp_pago_orden.sp" and view.lines for view in slices)


def test_comments_are_kept_apart_with_their_lines() -> None:
    tokens, comments = tokenize(SOURCE)
    assert comments[0].line_start == 1
    assert any("RF-04" in c.text and c.line_start == 79 for c in comments)
    assert all("RF-" not in t.text for t in tokens)


def test_an_unknown_statement_is_an_inventory_problem_not_a_crash() -> None:
    broken = SourceFile("broken.sp", "create procedure p as\nselect 'unterminated\n")
    inventory = SybaseAdapter().inventory([broken])
    assert inventory.problems
    assert inventory.problems[0].startswith("broken.sp:")
