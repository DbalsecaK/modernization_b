"""The COBOL/CICS adapter (spec 8.2, 8.3; ADR-0015) against the fictitious application and its reference inventory,
written by hand from the sources: transactions, programs, paragraphs, copybooks, calls, maps, files, PERFORMs, CICS
commands and neutral types, all with file and line. Plus the parser details the reference does not cover."""

import json
from collections import Counter
from pathlib import Path

import pytest

from nexti_adapter_cobol import CobolAdapter, parse_copybook, parse_csd, parse_program, to_neutral
from nexti_adapter_cobol.parser import tokens
from nexti_adapter_sybase import SybaseAdapter
from nexti_core.adapters import Inventory, SourceFile

ROOT = Path(__file__).parent / "fixtures" / "pagos_cics"
REFERENCE = json.loads((ROOT / "reference_inventory.json").read_text(encoding="utf-8"))
SUFFIXES = (".cbl", ".cpy", ".csd", ".bms")


def workspace() -> list[SourceFile]:
    return [SourceFile(p.relative_to(ROOT).as_posix(), p.read_text(encoding="utf-8"))
            for p in sorted(ROOT.rglob("*")) if p.is_file() and p.suffix in SUFFIXES]  # fmt: skip


@pytest.fixture(scope="module")
def inventory() -> Inventory:
    return CobolAdapter().inventory(workspace())


def edges(inv: Inventory, kind: str) -> set[tuple[str, str]]:
    return {(e.source, e.target) for e in inv.edges if e.type == kind}


def test_detection_tells_cobol_from_sybase() -> None:
    files = workspace()
    assert CobolAdapter().detect(files) >= 0.6
    assert SybaseAdapter().detect(files) == 0.0
    procedure = [SourceFile("sp/x.sp", "create procedure x as\nbegin\n  return 0\nend\n")]
    assert CobolAdapter().detect(procedure) == 0.0


def test_transaction_program_map_family(inventory: Inventory) -> None:
    assert inventory.problems == []
    assert edges(inventory, "STARTS") == {(f"tx:{t}", f"program:{p}") for t, p in REFERENCE["transactions"].items()}
    maps = {(f"program:{p}", f"map:PAGOSET.{m}") for p, names in REFERENCE["maps"].items() for m in names}
    assert edges(inventory, "USES_MAP") == maps
    assert all(inventory.node(target) is not None for _, target in maps)  # the maps come from the BMS adapter
    calls = {(e.source, e.target, e.properties.get("kind")) for e in inventory.edges if e.type == "CALLS"}
    assert calls == {(f"program:{a}", f"program:{b}", kind) for a, b, kind in REFERENCE["calls"]}
    external = {n.name for n in inventory.nodes if n.label == "Program" and n.properties.get("external")}
    assert external == set(REFERENCE["external_programs"])


def test_programs_and_paragraphs_have_file_and_lines(inventory: Inventory) -> None:
    for name, expected in REFERENCE["programs"].items():
        program = inventory.node(f"program:{name}")
        assert program is not None
        assert (program.file, [program.line_start, program.line_end]) == (expected["file"], expected["lines"])
        found = {n.name: n.line_start for n in inventory.nodes
                 if n.label == "Paragraph" and n.properties.get("program") == name}  # fmt: skip
        assert found == expected["paragraphs"]
    performs = {(f"para:{p}.{a}", f"para:{p}.{b}") for p, pairs in REFERENCE["performs"].items() for a, b in pairs}
    assert edges(inventory, "PERFORMS") == performs


def test_copybooks_files_and_cics_commands(inventory: Inventory) -> None:
    copies = {(f"program:{p}", f"copybook:{c}") for p, books in REFERENCE["copies"].items() for c in books}
    assert edges(inventory, "COPIES") == copies
    for system in REFERENCE["system_copybooks"]:
        assert inventory.node(f"copybook:{system}") is None
    assert edges(inventory, "READS") == {
        (f"program:{p}", f"file:{f}") for p, fs in REFERENCE["reads"].items() for f in fs
    }
    assert edges(inventory, "WRITES") == {
        (f"program:{p}", f"file:{f}") for p, fs in REFERENCE["writes"].items() for f in fs
    }
    programs = {p.name: p for f in workspace() if f.path.endswith(".cbl") for p in [parse_program(f.path, f.text)]}
    for name, expected in REFERENCE["cics_commands"].items():
        assert dict(Counter(c.command for c in (s.cics for s in programs[name].statements()) if c)) == expected, name
    assert inventory.metrics["transactions"] == 2
    assert inventory.metrics["programs"] == 3


def test_neutral_types_of_the_data(inventory: Inventory) -> None:
    types = CobolAdapter().types(workspace())
    for name, expected in REFERENCE["data_items"].items():
        assert types[name] == expected["neutral"], name
    valor = next(n for n in inventory.nodes if n.key == "field:ORDREG.ORD-VALOR")
    assert valor.properties["source_type"] == "PIC S9(9)V99 COMP-3"
    estado = next(n for n in inventory.nodes if n.key == "field:ORDREG.ORD-ESTADO")
    assert estado.properties["conditions"] == "ORD-PENDIENTE,ORD-PAGADA"


def test_slices_classification_and_data_of_a_range() -> None:
    adapter = CobolAdapter()
    files = workspace()
    views = {v.unit: v for v in adapter.slices(files)}
    assert set(views) == {"PAGOMNU", "PAGOORD", "PAGODEB"}
    order = views["PAGOORD"]
    assert order.tables == ("ORDENES",)
    assert {"ORDENI", "EMPRESAI", "TIPCTAI", "CUENTAI", "VALORI", "CANALI", "CLAVEI"} <= set(order.parameters)
    assert views["PAGODEB"].parameters == ("DEB-CUENTA", "DEB-MONTO", "DEB-TIPO")
    assert (82, 103) in order.lines
    assert (1, 35) not in order.lines
    counts = adapter.classification(files)
    assert set(counts) == {"infrastructure", "control_flow", "business"}
    assert all(counts.values())
    detail = adapter.classified(files)  # the statements behind the counts, for the Inventory tab
    assert {label: sum(1 for d in detail if d["label"] == label) for label in counts} == counts
    assert all(d["unit"] and d["file"].endswith(".cbl") and d["line_start"] <= d["line_end"] for d in detail)
    reads, writes = adapter.data_of(files, "cbl/PAGOORD.cbl", [(129, 138)])
    assert reads == {"ORD-VALOR", "CANALI", "WS-COMISION"}
    assert writes == {"WS-COMISION", "WS-TOTAL"}
    reads, writes = adapter.data_of(files, "cbl/PAGODEB.cbl", [(35, 39)])
    assert {"CUENTAS", "CTA-SALDO"} <= writes
    assert "DEB-MONTO" in reads


@pytest.mark.parametrize(
    ("picture", "usage", "neutral"),
    [
        ("X(3)", "DISPLAY", "text(fixed,3,ebcdic)"),
        ("9(7)", "DISPLAY", "decimal(7,0,unsigned)"),
        ("S9(9)V99", "COMP-3", "decimal(11,2,signed)"),
        ("S9(4)", "COMP", "integer(16,signed)"),
        ("S9(8)", "COMP", "integer(32,signed)"),
        ("9(12)", "COMP", "integer(64,unsigned)"),
        ("ZZZ,ZZ9.99", "DISPLAY", "text(fixed,10,ebcdic)"),
    ],
)
def test_pictures_to_neutral_types(picture: str, usage: str, neutral: str) -> None:
    assert str(to_neutral(picture, usage).neutral) == neutral


def test_parser_details_beyond_the_reference() -> None:
    continued = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. CONT.\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN.\n"
        "           MOVE 'UN MENSAJE MUY LARGO QUE SIGUE EN LA LINEA\n"
        "      -    'SIGUIENTE' TO WS-X.\n"
        "           CALL WS-PROGRAMA.\n"
        "           EXEC CICS WEIRD END-EXEC.\n"
    )
    program = parse_program("cbl/CONT.cbl", continued)
    literal = next(t for t in tokens(continued) if t.kind == "string")
    assert literal.text == "'UN MENSAJE MUY LARGO QUE SIGUE EN LA LINEASIGUIENTE'"
    assert program.paragraph("0000-MAIN") is not None
    assert any("dynamic CALL" in p for p in program.problems)
    book = parse_copybook("REC", "cpy/REC.cpy", "       01  R.\n           05  A  PIC 9(3) OCCURS 5 TIMES.\n"
                                               "           05  B  REDEFINES A PIC X(15).\n")  # fmt: skip
    assert [(i.name, i.occurs, i.redefines) for i in book.data] == [("R", None, None), ("A", 5, None), ("B", None, "A")]
    (tx,) = parse_csd("csd/X.csd", " DEFINE TRANSACTION(AB12) GROUP(G) PROGRAM(PGM1)\n")
    assert (tx.transid, tx.program, tx.line) == ("AB12", "PGM1", 1)
    data = "       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n           COPY NOPE.\n"
    with_copy = continued.replace("       PROCEDURE DIVISION.", data + "       PROCEDURE DIVISION.")
    missing = CobolAdapter().inventory([SourceFile("cbl/CONT.cbl", with_copy)])
    assert any("copybook NOPE is not in the inputs" in p for p in missing.problems), missing.problems
