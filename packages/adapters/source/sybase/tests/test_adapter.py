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
    # ADR-0055: the unit of work decides what the business keeps or undoes, and sp_cerror is the error contract the
    # caller receives: business, never infrastructure (the first proven migration lost every rollback).
    assert hints[at(proc, 108)] == "business"  # begin tran
    assert hints[at(proc, 119)] == "business"  # rollback tran
    assert hints[at(proc, 161)] == "business"  # commit tran
    assert hints[at(proc, 167)] == "business"  # sp_cerror: the error contract
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
    assert 167 in targets  # sp_cerror is the error contract the caller receives (ADR-0055)
    assert 108 not in targets  # begin tran is business but not an outcome a rule is extracted from


def test_the_unit_of_work_lists_where_the_procedure_keeps_or_undoes_its_work(proc: Procedure) -> None:
    from nexti_adapter_sybase import SybaseAdapter
    from nexti_adapter_sybase.analysis import unit_of_work

    work = unit_of_work(proc)
    assert work[0] == (108, "begin_tran")
    assert (119, "rollback") in work
    assert (161, "commit") in work
    assert [k for _, k in work].count("rollback") == 3
    files = [SourceFile("sp/x.sp", FIXTURE.read_text(encoding="utf-8"))]
    assert SybaseAdapter().unit_of_work(files, "dbo.sp_pago_orden") == work
    assert SybaseAdapter().unit_of_work(files, "sp_otro") == []


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
    writes = {(e.source, e.target) for e in inventory.edges if e.type == "WRITES" and e.source.startswith("proc:")}
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


def test_the_classified_statements_are_the_detail_behind_the_counts() -> None:
    from nexti_adapter_sybase import SybaseAdapter
    from nexti_core.adapters import SourceFile

    files = [SourceFile("sp/sp_pago_orden.sp", SOURCE)]
    adapter = SybaseAdapter()
    counts = adapter.classification(files)
    detail = adapter.classified(files)
    assert {label: sum(1 for d in detail if d["label"] == label) for label in counts} == counts
    assert {d["unit"] for d in detail} == {"dbo.sp_pago_orden"}
    writes = [d for d in detail if d["label"] == "business" and d["reason"].startswith("writes ")]
    assert writes
    assert all(d["line_start"] <= d["line_end"] for d in writes)


def test_a_slice_in_many_pieces_reads_as_blocks_and_a_short_one_is_left_as_it_is() -> None:
    from nexti_adapter_sybase import readable

    pieces = [(n, n + 1) for n in range(1, 200, 4)]  # 50 pieces with gaps of 2 lines
    assert readable(pieces) == ((1, 198),)
    few = [(1, 2), (10, 12)]
    assert readable(few) == ((1, 2), (10, 12))


def test_the_signature_of_every_call_the_program_makes_is_read_from_the_code() -> None:
    # ADR-0055 (phase F): sp_pago_orden calls sp_debito by name and keeps its return status in @w_return; the
    # design cannot map @w_return as an output parameter, the adapter would ask the program for it.
    from nexti_core.adapters import SourceFile

    files = [SourceFile("sp/sp_pago_orden.sp", FIXTURE.read_text(encoding="utf-8"))]
    found = SybaseAdapter().call_signatures(files, "sp_pago_orden")
    parameters, receivers = found["sp_debito"]
    assert "@w_return" in receivers
    assert parameters
    assert all(p.startswith("@") for p in parameters)
    assert "sp_cerror" in found
    assert SybaseAdapter().call_signatures(files, "nope") == {}


def test_the_columns_a_program_loads_are_keyed_by_the_table_as_it_names_it() -> None:
    # Phase F (ADR-0055): a bare name is a table of the procedure's own database and `db..name` another table;
    # the columns loaded from each stay apart, so an entity keeping one is not asked for the other's columns.
    from nexti_core.adapters import SourceFile

    text = (
        "create procedure sp_x as\ndeclare @a int, @b int\n"
        "select @a = dt_nombre_beneficiario from bp_detalle where dt_orden = 1\n"
        "select @b = dt_tipo_cta from db_otra..bp_detalle where dt_orden = 1\nreturn 0\n"
    )
    found = SybaseAdapter().columns_read([SourceFile("sp/x.sp", text)])
    assert found == {"bp_detalle": {"dt_nombre_beneficiario"}, "db_otra..bp_detalle": {"dt_tipo_cta"}}


def test_the_adapter_says_when_a_program_returns_its_status_as_data() -> None:
    # Phase F of ADR-0055: `return @o_error`, or `select @o_error = @w_num_error ... return @w_num_error`, is a
    # status the caller reads together with the outputs; `return @w_error` after sp_cerror is a plain rejection.
    adapter = SybaseAdapter()
    assert adapter.status_as_data([SourceFile("sp/sp_pago_orden.sp", SOURCE)], "dbo.sp_pago_orden") is False
    data = """create procedure dbo.sp_debito_empresa
(
    @i_cuenta   char(10),
    @i_aplcobis char(1),
    @o_error    int output
)
as
declare @w_num_error int, @w_return int
begin tran
update bp_orden set or_estado = 'P' where or_cuenta = @i_cuenta
if @@error <> 0
begin
    select @w_num_error = 122002
    goto lbl_error
end
commit tran
select @o_error = 0
return 0
lbl_error:
    if @@trancount > 0
        rollback tran
    if @i_aplcobis = 'S'
    begin
        exec cobis..sp_cerror @i_num = @w_num_error
        return @w_num_error
    end
    select @o_error = @w_num_error
    return 0
"""
    assert adapter.status_as_data([SourceFile("sp/sp_debito_empresa.sp", data)], "sp_debito_empresa") is True
    direct = data.replace("select @o_error = @w_num_error" + chr(10) + "    return 0", "return @o_error")
    assert adapter.status_as_data([SourceFile("sp/x.sp", direct)], "sp_debito_empresa") is True
    assert adapter.status_as_data([SourceFile("sp/x.sp", direct)], "sp_otro") is False
