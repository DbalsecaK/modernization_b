"""The ASP.NET WebForms adapter (spec 8.3, ADR-0020) on the fictitious "Transferencias" application: pages and their
code-behind become the code layer and the screens (with their validators and navigation), each event handler and
App_Code method is a citable slice, the SQL gives the tables, the traces give the golden master (PARTLY PROVEN at
most) and the uplift assessment separates what is rewritten from what can be uplifted."""

import asyncio
from pathlib import Path

import pytest

from nexti_adapter_aspx import AspxAdapter, assess, screen_id
from nexti_adapter_aspx.parser import parse_csharp, parse_markup
from nexti_adapter_cobol.traces import TraceRunner
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import Case, Suite

ROOT = Path(__file__).parent / "fixtures" / "transferencias"
FILES = [SourceFile(p.relative_to(ROOT).as_posix(), p.read_text(encoding="utf-8"))
         for p in sorted(ROOT.rglob("*")) if p.is_file()]  # fmt: skip
ADAPTER = AspxAdapter()


def test_webforms_inputs_are_recognised_and_others_are_not() -> None:
    assert ADAPTER.detect(FILES) == 1.0
    assert ADAPTER.detect([SourceFile("sp/x.sp", "create procedure x as select 1")]) == 0.0


def test_the_inventory_links_pages_handlers_library_and_tables() -> None:
    inv = ADAPTER.inventory(FILES)
    assert inv.problems == []
    assert inv.metrics["pages"] == 2
    assert inv.metrics["tables"] == 2
    page = inv.node("page:Transferencia")
    assert page is not None
    assert (page.label, page.file, page.properties["uplift"]) == ("Program", "Transferencia.aspx.cs", "rewrite")
    library = inv.node("class:ComisionService")
    assert library is not None
    assert (library.file, library.properties["uplift"]) == ("App_Code/ComisionService.cs", "uplift")
    edges = {(e.source, e.type, e.target) for e in inv.edges}
    assert ("page:Transferencia", "CALLS", "class:ComisionService") in edges
    assert ("method:Transferencia.btnTransferir_Click", "WRITES", "table:TRANSFERENCIAS") in edges
    assert ("method:Transferencia.btnTransferir_Click", "READS", "table:CUENTAS") in edges
    assert ("page:Comprobante", "READS", "table:TRANSFERENCIAS") in edges
    assert inv.node("trace:TRANSFERENCIA") is not None


def test_each_page_is_a_screen_with_its_validators_and_navigation() -> None:
    screens = {s.id: s for s in ADAPTER.screens(FILES)}
    transfer = screens[screen_id("Transferencia")]
    assert transfer.name == "Transferencia entre cuentas"
    origin = transfer.field("txtCuentaOrigen")
    assert origin is not None
    assert (origin.kind, origin.label, origin.length, origin.required) == ("input", "Cuenta origen", 10, True)
    assert origin.validation == "required; pattern ^\\d{10}$"
    assert "La cuenta tiene 10 dígitos" in origin.message
    amount = transfer.field("txtMonto")
    assert amount is not None
    assert (amount.type, amount.validation) == ("decimal(19,4,signed)", "required; range 1..10000 (Currency)")
    kind = transfer.field("ddlTipo")
    assert kind is not None
    assert kind.type == "enum(PRO|INM)"
    assert [f.name for f in transfer.fields if f.kind == "output"] == ["lblComision", "lblMensaje"]
    actions = {a.key: a for a in transfer.actions}
    assert actions["btnTransferir"].target == "SCR-COMPROBANTE"  # Response.Redirect in its handler
    assert actions["btnCancelar"].target is None  # Inicio.aspx is not in the inputs
    assert "Inicio" in actions["btnCancelar"].description
    assert str(transfer.sources[0]).startswith("Transferencia.aspx:")
    receipt = screens["SCR-COMPROBANTE"]
    assert [f.name for f in receipt.fields] == ["lblNumero", "lblMonto"]
    assert receipt.field("lblNumero").label == "Número"  # type: ignore[union-attr]
    assert receipt.navigation_out == ("SCR-TRANSFERENCIA",)


def test_each_handler_and_library_method_is_a_citable_slice() -> None:
    views = {v.unit: v for v in ADAPTER.slices(FILES)}
    click = views["Transferencia.btnTransferir_Click"]
    assert click.file == "Transferencia.aspx.cs"
    text = FILES[[f.path for f in FILES].index("Transferencia.aspx.cs")].text.split("\n")
    start, end = click.lines[0]
    assert "btnTransferir_Click" in text[start - 1]
    assert text[end - 1].strip() == "}"
    assert click.tables == ("CUENTAS", "TRANSFERENCIAS")
    assert set(click.parameters) == {"txtCuentaOrigen", "txtCuentaDestino", "txtMonto", "ddlTipo"}
    assert views["ComisionService.Calcular"].parameters == ("monto", "tipo")
    reads, writes = ADAPTER.data_of(FILES, "Transferencia.aspx.cs", [click.lines[0]])
    assert (set(reads), set(writes)) == ({"CUENTAS", "TRANSFERENCIAS"}, {"CUENTAS", "TRANSFERENCIAS"})


def test_types_and_classification_come_from_the_code() -> None:
    assert ADAPTER.types(FILES) == {"decimal": "decimal(19,4,signed)", "string": "text(var,max,utf8)"}
    counts = ADAPTER.classification(FILES)
    assert counts["business"] > 0
    assert counts["infrastructure"] > counts["control_flow"] > 0


def test_the_uplift_assessment_separates_rewrite_from_uplift() -> None:
    items = {i.file: i for i in assess(FILES)}
    assert items["Transferencia.aspx"].verdict == "rewrite"
    assert "server controls (asp:)" in items["Transferencia.aspx"].blockers
    behind = items["Transferencia.aspx.cs"]
    assert behind.verdict == "rewrite"
    assert "derives from Page / UserControl" in behind.blockers
    assert "System.Data.SqlClient -> Microsoft.Data.SqlClient" in behind.changes
    library = items["App_Code/ComisionService.cs"]
    assert (library.verdict, library.blockers) == ("uplift", ())
    assert items["Web.config"].verdict == "replace"
    assert "uplift assessment" in ADAPTER.digest(FILES).lower()


def test_the_traces_are_the_golden_master_and_cap_the_verdict() -> None:
    suite = Suite(program="TRANSFERENCIA", cases=[
        Case(name="tope_de_comision", rules=["RULE-007"], inputs={}),
        Case(name="saldo_insuficiente", rules=["RULE-009"], inputs={}),
    ])  # fmt: skip
    runner = TraceRunner()
    master = asyncio.run(runner.run(FILES, suite))
    assert (master.engine, master.from_traces, runner.engine) == ("aspx-trace", True, "aspx-trace")
    capped = master.results[0]
    assert capped.observation.outputs["lblComision"] == "5.00"
    assert capped.case.rules == ["RULE-007"]
    with pytest.raises(ValueError, match="no recorded trace"):
        asyncio.run(runner.run(FILES, Suite(program="TRANSFERENCIA", cases=[
            Case(name="caso_inventado", rules=["RULE-001"], inputs={"txtMonto": "1"})])))  # fmt: skip


def test_the_parser_reads_markup_and_csharp_as_they_are() -> None:
    page = (
        '<%@ Page CodeFile="x.aspx.cs" Inherits="X" %>\n<%-- <asp:TextBox ID="hidden" /> --%>\n'
        '<asp:TextBox ID="a" runat="server"\n MaxLength="3" />'
    )
    markup = parse_markup("x.aspx", page)
    assert [(c.id, c.line, c.get("maxlength")) for c in markup.controls] == [("a", 3, "3")]
    code = (
        "public class X : Page\n{\n    // void Hidden() {}\n    protected void Go(object s, EventArgs e)\n"
        '    {\n        var q = "SELECT A FROM T";\n        lbl.Text = "{";\n    }\n}\n'
    )
    (cls,) = parse_csharp("x.cs", code)
    (method,) = cls.methods
    assert (method.name, method.line_start, method.line_end, method.tables_read, method.writes) == (
        "Go",
        4,
        8,
        ("T",),
        ("lbl",),
    )
