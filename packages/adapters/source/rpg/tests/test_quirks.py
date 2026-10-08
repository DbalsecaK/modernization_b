"""The RPG quirk catalog (R4, ADR-0048 for RPG): found in the parsed program with the lines that rely on each, on the
fictitious Cooperativa Andina programs and on small invented programs for the rest of the catalog."""

from pathlib import Path

from nexti_adapter_rpg import RpgAdapter, parse
from nexti_adapter_rpg.quirks import CATALOG, detect, program_environment
from nexti_core.adapters import SourceFile

FIXTURES = Path(__file__).parent / "fixtures" / "cooperativa"
FILES = [SourceFile(p.relative_to(FIXTURES).as_posix(), p.read_text(encoding="utf-8"))
         for p in sorted(FIXTURES.rglob("*")) if p.is_file()]  # fmt: skip
ADAPTER = RpgAdapter()


def found(program: str) -> dict[str, list[int]]:
    relied, _ = ADAPTER.program_quirks(FILES, program)
    return {q.id: q.lines for q in relied}


def test_the_cycle_rounding_and_truncation_of_an_rpg_iii_program() -> None:
    quirks = found("CALCINT")
    assert quirks["rpg-cycle"] == [2]  # the primary file: an implicit read loop
    assert quirks["half-adjust"] == [15, 16]  # MULT and DIV with H in column 53
    assert quirks["decimal-truncation"] == [17]  # ADD without H
    assert quirks["fixed-overflow"] == [15, 16, 17]
    assert "immediate-writes" not in quirks  # WRITE DETALLE goes to the printer, not to a table


def test_not_found_records_and_writes_without_commitment_control() -> None:
    quirks = found("ACTSALDO")
    assert quirks["record-not-found"] == [12]  # CHAIN
    assert quirks["decimal-truncation"] == [23, 25]  # the free-form assignments that compute
    assert quirks["immediate-writes"] == [32, 35]  # UPDATE and WRITE of database files
    assert "ebcdic-order" not in quirks  # a CHAIN by exact key does not depend on the collating order
    assert set(found("VALCTA")) == {"immediate-writes"}  # an SQL INSERT; `<>` is not an ordered comparison


def test_the_rest_of_the_catalog_on_an_invented_program() -> None:
    source = (
        "**FREE\n"
        "ctl-opt datfmt(*dmy) expropts(*resdecpos);\n"
        "dcl-f CLIENTES keyed usage(*update) commit;\n"
        "dcl-s nombre char(20);\n"
        "dcl-s total packed(9:2);\n"
        "dcl-s resto packed(5:0);\n"
        "dcl-s lista char(10) dim(5);\n"
        "begsr *inzsr;\n"
        "  total = 0;\n"
        "endsr;\n"
        "monitor;\n"
        "  total = total / 3;\n"
        "on-error;\n"
        "  rolbk;\n"
        "endmon;\n"
        "if nombre > 'M';\n"
        "  sorta lista;\n"
        "endif;\n"
        "setll nombre CLIENTES;\n"
        "read(e) CLIENTES;\n"
        "commit;\n"
    )
    program = parse("qrpglesrc/VARIOS.rpgle", source)
    quirks = {q.id: q.lines for q in detect(program)}
    assert quirks["initialization-subroutine"] == [8]
    assert quirks["intermediate-precision"] == [12]
    assert quirks["errors-handled-by-program"] == [11, 20]  # MONITOR and read(e)
    assert quirks["commitment-control"] == [14, 21]
    assert quirks["ebcdic-order"] == [16, 17, 19, 20]  # a text comparison, SORTA and the keyed sequence
    assert "immediate-writes" not in quirks  # the file is under commitment control
    environment = {e.key: e.value for e in program_environment(program)}
    assert environment == {"rpg:datfmt": "*DMY", "rpg:expropts": "*RESDECPOS"}


def test_level_breaks_moves_and_remainders_in_fixed_form() -> None:
    def c(level: str, f1: str, op: str, f2: str, res: str) -> str:
        line = [" "] * 80
        for col, text in ((6, "C"), (7, level), (12, f1), (26, op), (36, f2), (50, res)):
            line[col - 1 : col - 1 + len(text)] = text
        return "".join(line).rstrip()

    source = "\n".join(["     H", c("", "", "MOVE", "CODIGO", "TEXTO"), c("", "TOTAL", "DIV", "3", "CUOTA"),
                        c("", "", "MVR", "", "RESTO"), c("L1", "", "ADD", "CUOTA", "GRUPO")]) + "\n"  # fmt: skip
    quirks = {q.id: q.lines for q in detect(parse("qrpglesrc/FIJO.rpgle", source))}
    assert quirks["move-semantics"] == [2]
    assert quirks["division-remainder"] == [4]
    assert quirks["level-breaks"] == [5]


def test_every_quirk_says_what_the_target_must_do() -> None:
    assert all(spec.behavior and spec.target for spec in CATALOG.values())
    relied = ADAPTER.engine_quirks(FILES)
    assert {q.file for q in relied} >= {"qrpgsrc/CALCINT.rpg", "qrpglesrc/ACTSALDO.rpgle"}
    assert all(q.observed is None for q in relied)  # not probed: the golden master shows what the engine did
