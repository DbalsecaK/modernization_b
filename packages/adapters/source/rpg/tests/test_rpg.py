"""The RPG / IBM i source adapter (ADR-0051, R1) on the fictitious Cooperativa Andina workspace: one program per RPG
form (RPG III, RPG IV fixed, mixed and fully free), the DDS of its files and the CL that starts the batch."""

from pathlib import Path

from nexti_adapter_rpg import RpgAdapter, cl, dds, flow, kind_of, parse
from nexti_core.adapters import SourceFile

FIXTURES = Path(__file__).parent / "fixtures" / "cooperativa"
ADAPTER = RpgAdapter()


def workspace() -> list[SourceFile]:
    return [SourceFile(p.relative_to(FIXTURES).as_posix(), p.read_text(encoding="utf-8"))
            for p in sorted(FIXTURES.rglob("*")) if p.is_file()]  # fmt: skip


def source(name: str) -> SourceFile:
    return next(f for f in workspace() if Path(f.path).stem == name)


def test_it_detects_an_ibm_i_workspace_and_ignores_other_code() -> None:
    assert ADAPTER.detect(workspace()) >= 0.9
    assert ADAPTER.detect([SourceFile("p.sp", "create proc sp_p as\nselect 1\n")]) == 0.0
    cobol = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. PAGO.\n"
    assert ADAPTER.detect([SourceFile("x/PAGO.cbl", cobol)]) == 0.0


def test_it_reads_the_four_forms_of_rpg() -> None:
    variants = {p: parse(f.path, f.text).variant for p, f in
                ((n, source(n)) for n in ("CALCINT", "ACTSALDO", "CONSCTA", "VALCTA"))}  # fmt: skip
    assert variants == {"CALCINT": "rpg3", "ACTSALDO": "rpg4-mixed", "CONSCTA": "rpg4-fixed", "VALCTA": "rpg4-free"}
    assert all(not parse(f.path, f.text).problems for f in map(source, variants))


def test_the_entry_parameters_come_from_the_plist_or_the_procedure_interface() -> None:
    calcint = parse(source("CALCINT").path, source("CALCINT").text)
    assert calcint.parameters == ["WTASA", "WFECHA"]
    assert {f.name: f.role for f in calcint.fields}["WTASA"] == "parameter"
    actsaldo = parse(source("ACTSALDO").path, source("ACTSALDO").text)
    assert actsaldo.parameters == ["PCUENTA", "PMONTO", "PTIPO", "PRESULT"]


def test_subroutines_and_exported_procedures_are_routines() -> None:
    calcint = parse(source("CALCINT").path, source("CALCINT").text)
    assert [(r.name, r.kind) for r in calcint.routines] == [("*MAIN", "mainline"), ("CALINT", "subroutine"),
                                                           ("IMPRIM", "subroutine")]  # fmt: skip
    valcta = parse(source("VALCTA").path, source("VALCTA").text)
    assert valcta.nomain
    (procedure,) = valcta.routines
    assert (procedure.name, procedure.kind, procedure.exported) == ("VALIDARCUENTA", "procedure", True)
    # The one-line prototype closes itself; the data structure keeps its subfields' types.
    fields = {f.name: (f.kind, f.length, f.decimals, f.role) for f in valcta.fields}
    assert fields["SALDO"] == ("PACKED", 11, 2, "subfield")
    assert fields["PCUENTA"][3] == "parameter"


def test_rpg_iii_opcodes_keep_their_relational_code_and_half_adjust() -> None:
    calcint = parse(source("CALCINT").path, source("CALCINT").text)
    mult = next(s for s in calcint.statements() if s.opcode == "MULT")
    assert (mult.factor1, mult.factor2, mult.result) == ("CTSALD", "WTASA", "WINT")
    assert next(s for s in calcint.statements() if s.opcode == "IFEQ").base == "IF"


def test_the_inventory_links_programs_files_screens_reports_and_calls() -> None:
    inventory = ADAPTER.inventory(workspace())
    edges = {(e.source, e.type, e.target) for e in inventory.edges}
    assert {
        ("program:ACTSALDO", "READS", "table:CUENTAS"), ("program:ACTSALDO", "WRITES", "table:CUENTAS"),
        ("program:ACTSALDO", "WRITES", "table:MOVIMI"), ("program:ACTSALDO", "PERFORMS", "para:ACTSALDO.GRABAR"),
        ("program:CONSCTA", "USES_MAP", "file:CONSCTAD"), ("program:CONSCTA", "READS", "table:CUENTASL1"),
        ("program:CALCINT", "WRITES", "file:REPINT"), ("program:VALCTA", "READS", "table:CUENTAS"),
        ("program:VALCTA", "WRITES", "table:AUDITA"), ("program:VALCTA", "CONTAINS", "proc:VALCTA.VALIDARCUENTA"),
        ("table:CUENTASL1", "DERIVED_FROM", "table:CUENTAS"), ("program:CIERRE", "CALLS", "program:CALCINT"),
        ("program:CIERRE", "CALLS", "program:ENVIAREP"), ("program:CIERRE", "DEPENDS_ON", "table:CUENTAS"),
    } <= edges  # fmt: skip
    # A printer record is a report line, never a table.
    assert not any(target == "table:REPINT" for _, _, target in edges)
    assert inventory.metrics["programs"] == 4
    assert inventory.metrics["cl_programs"] == 1
    assert inventory.problems == ["file AUDITA has no DDS in the inputs: its fields are unknown"]


def test_a_missing_copy_member_is_a_problem_not_a_guess() -> None:
    text = "**FREE\n/copy qcpysrc,CPYCTA\ndcl-s x int(10);\nx = 1;\n"
    inventory = ADAPTER.inventory([SourceFile("qrpglesrc/USACOPY.rpgle", text)])
    assert ("program:USACOPY", "COPIES", "copybook:CPYCTA") in {(e.source, e.type, e.target) for e in inventory.edges}
    assert "qrpglesrc/USACOPY.rpgle:2: /COPY member CPYCTA is not in the inputs" in inventory.problems


def test_neutral_types_from_programs_and_dds() -> None:
    types = ADAPTER.types(workspace())
    assert types["PMONTO"] == "decimal(11,2,signed)"
    assert types["PRESULT"] == "decimal(3,0,signed)"  # zoned
    assert types["WCOMIS"] == "decimal(3,2,signed)"  # a named numeric constant
    assert types["WSALIR"] == "boolean"
    assert types["CTNUME"] == "text(fixed,10,ebcdic)"
    assert types["MVFECH"] == "timestamp(local)"


def test_a_logical_file_field_takes_the_type_of_its_physical_file() -> None:
    nodes = {n.key: n for n in ADAPTER.inventory(workspace()).nodes}
    assert nodes["column:CUENTASL1.CTSALD"].properties["neutral_type"] == "decimal(11,2,signed)"


def test_dds_reads_screens_and_function_keys() -> None:
    screen = dds.parse(source("CONSCTAD").path, source("CONSCTAD").text)
    assert screen.kind == "DSPF"
    (record,) = screen.records
    assert dds.function_keys(record) == ["CF03"]
    assert (4, 2, "Cuenta:") in record.texts
    assert {f.name: (f.usage, f.row, f.column) for f in record.fields}["SCCTA"] == ("B", 4, 12)


def test_cl_reads_calls_submitted_jobs_and_overrides() -> None:
    program = cl.parse(source("CIERRE").path, source("CIERRE").text)
    assert program.parameters == ["&TASA", "&FECHA"]
    assert program.calls() == [("CALCINT", 7, "CALL"), ("ENVIAREP", 9, "SBMJOB")]
    assert program.overrides() == [("CUENTAS", "CUENTAS", 5)]


def test_classification_and_slices() -> None:
    counts = ADAPTER.classification(workspace())
    assert counts["business"] > 0
    assert counts["control_flow"] > 0
    slices = {s.unit: s for s in ADAPTER.slices(workspace())}
    assert slices["ACTSALDO"].tables == ("CUENTAS", "MOVIMI")
    assert slices["CALCINT"].tables == ("CUENTAS",)  # the report is not a table
    assert slices["VALCTA"].tables == ("AUDITA", "CUENTAS")
    exfmt = next(s for s in parse(source("CONSCTA").path, source("CONSCTA").text).statements() if s.opcode == "EXFMT")
    assert kind_of(exfmt) == "infrastructure"


def test_data_of_names_variables_and_files_not_builtins_or_subroutines() -> None:
    program = parse(source("ACTSALDO").path, source("ACTSALDO").text)
    reads, writes = flow(program, [(12, 36)], {"RCUENTA": "CUENTAS", "RMOVIM": "MOVIMI"})
    assert reads == {"CUENTAS", "CTSALD", "PTIPO", "PCUENTA", "WNUEVO", "PMONTO", "WCOMIS"}
    assert writes == {"CUENTAS", "MOVIMI", "CTSALD", "WNUEVO", "PRESULT", "MVCTA", "MVMONT"}


def test_coverage_branches_and_digest() -> None:
    assert [b.id for b in ADAPTER.coverage_branches(workspace(), "CALCINT")] == ["CALINT", "IMPRIM"]
    digest = ADAPTER.digest(workspace())
    assert "Program VALCTA (rpg4-free service program module (no main)" in digest
    assert "exported procedures: VALIDARCUENTA" in digest
    assert "Table CUENTASL1 (LF, keys CTNUME): CTNUME A(10), CTSALD P(11:2)" in digest
