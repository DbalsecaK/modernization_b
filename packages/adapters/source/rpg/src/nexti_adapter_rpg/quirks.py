"""The behaviours of RPG and the IBM i a program relies on and a modern stack does differently (R4 of the RPG plan,
within ADR-0048), and the settings it runs under.

Each quirk is found in the parsed program (never by a model) with the lines that rely on it. They carry no probe yet:
the IBM i bridge (ADR-0053) runs programs, not ad-hoc statements, so the register says `not probed` and the golden
master shows what the engine did. The environment comes from what the program sets: its control keywords (H spec or
ctl-opt: DATFMT, EXPROPTS, FIXNBR...) and the keywords of its files."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from nexti_adapter_rpg.parser import READS, WRITES, RpgProgram, Statement
from nexti_core.spec.characterization import EngineQuirk, EnvironmentItem, QuirkSeverity

LINES_AT_MOST = 50
_FIXED_ARITHMETIC = {"ADD", "SUB", "MULT", "DIV", "Z-ADD", "Z-SUB", "XFOOT", "SQRT"}
_STRING = re.compile(r"'(?:[^']|'')*'")
_SPECIAL = re.compile(r"\*[A-Z][A-Z0-9]*")  # *ON, *BLANKS, *IN03, *LOVAL: names, not operators
_COMPARE = {"IF", "ELSEIF", "DOW", "DOU", "WHEN", "CAB", "CAS"}
_KEYWORD = re.compile(r"\b(DATFMT|TIMFMT|DECEDIT|EXPROPTS|FIXNBR|TRUNCNBR|ALWNULL|CCSID|DFTACTGRP|ACTGRP|SRTSEQ|"
                      r"ALTSEQ|OPENOPT)\(([^)]*)\)")  # fmt: skip


@dataclass(frozen=True)
class Spec:
    id: str
    severity: QuirkSeverity
    behavior: str
    target: str


CATALOG: dict[str, Spec] = {
    s.id: s
    for s in (
        Spec("rpg-cycle", "critical",
             "The program runs in the RPG cycle: it reads its primary file record by record without any READ in the "
             "code, runs the detail calculations for each record and ends when the file ends (*INLR on).",
             "Write the loop explicitly over the records in the file's key order, with the same detail and total "
             "steps, and stop exactly where the cycle stops."),
        Spec("level-breaks", "high",
             "Total calculations (L1-L9, LR) run when a control field changes and after the last record, before the "
             "detail of the next group; a higher level break also runs every lower one.",
             "Detect the change of each control field and run the totals of that level and every lower level, in "
             "the same order, before the next group's detail."),
        Spec("decimal-truncation", "critical",
             "Arithmetic without (H) truncates the result to the decimals of the result field (2.999 becomes 2.99, "
             "-2.999 becomes -2.99): it never rounds.",
             "Truncate toward zero at the scale of the result (RoundingMode.DOWN); never let a language default "
             "round these results."),
        Spec("half-adjust", "high",
             "(H) rounds half away from zero to the decimals of the result field (0.005 becomes 0.01, -0.005 becomes "
             "-0.01).",
             "Round HALF_UP (away from zero) at the result's scale in exactly these operations, and only in them."),
        Spec("fixed-overflow", "high",
             "The fixed-form arithmetic operations (ADD, SUB, MULT, DIV, Z-ADD...) drop the high-order digits that do "
             "not fit the result field without any error (999 + 1 into 3 digits gives 0); EVAL fails instead.",
             "Keep only the digits that fit the result's length in these operations (a modulo of 10^digits), with "
             "no exception."),
        Spec("intermediate-precision", "medium",
             "EVAL keeps intermediate results to 63 digits and, with the default EXPROPTS(*MAXDIGITS), may drop "
             "decimal positions of a division before assigning it.",
             "Compute divisions with enough scale and truncate to the result's decimals as the golden master shows; "
             "do not round the intermediate value."),
        Spec("move-semantics", "high",
             "MOVE copies right-aligned and MOVEL left-aligned, only as many characters as fit, leaving the rest of "
             "the result unchanged; between numbers and text it converts digit by digit (zoned), not by value.",
             "Copy the exact substring into the exact position and keep the untouched part of the target; convert "
             "numbers and text digit by digit."),
        Spec("division-remainder", "medium",
             "MVR right after DIV takes the remainder of that division, with the sign of the dividend.",
             "Compute the remainder of the same division with the dividend's sign (BigDecimal.remainder)."),
        Spec("record-not-found", "high",
             "A CHAIN or READ that finds no record does not fail: it sets %FOUND/%EOF off or on (or the resulting "
             "indicator) and the record's fields keep the values they had before.",
             "Return 'not found' instead of throwing, and keep the previous values of the record's fields where the "
             "program goes on using them."),
        Spec("ebcdic-order", "high",
             "Text comparisons, SORTA, LOOKUP and keyed reads follow the EBCDIC order of the job's CCSID: lowercase "
             "before uppercase and letters before digits, the opposite of ASCII and Unicode.",
             "Compare and sort with an EBCDIC collation (or translate the keys) wherever the order decides the "
             "result."),
        Spec("errors-handled-by-program", "high",
             "With an (E) extender, a resulting indicator, MONITOR or a *PSSR subroutine a failing operation does not "
             "end the program: it decides with %ERROR, %STATUS or the indicator; without them the job stops with an "
             "inquiry message.",
             "Check the outcome right after each such operation and continue as the program does; do not let an "
             "exception skip the code the legacy runs after the error."),
        Spec("immediate-writes", "high",
             "Without commitment control every WRITE, UPDATE, DELETE or SQL change is final at once: a later failure "
             "of the program does not undo it.",
             "Do not wrap the program in a transaction that rolls back on error; commit each change where the legacy "
             "makes it."),
        Spec("commitment-control", "high",
             "Changes stay pending until COMMIT and are undone by ROLBK, including those of the files opened under "
             "commitment control only.",
             "Use one transaction with the same commit and rollback points, over exactly the same files."),
        Spec("initialization-subroutine", "medium",
             "The *INZSR subroutine runs once, automatically, before the first calculation.",
             "Run its logic once at the start of the program, before anything else."),
        Spec("page-overflow", "medium",
             "The printer file's overflow indicator turns on at the overflow line and the program prints headings "
             "when it sees it.",
             "Count the lines per page as the printer file defines them and print the headings at the same points."),
    )
}  # fmt: skip


def _operands_text(s: Statement) -> str:
    return _SPECIAL.sub(" ", _STRING.sub("''", f"{s.factor1} {s.factor2}".upper()))


def _assigns_arithmetic(s: Statement) -> bool:
    """An EVAL whose right side computes (+ - * /), not a plain move of a value."""
    if s.base not in ("EVAL", "EVALR"):
        return False
    _, _, right = s.factor2.partition("=")
    text = _SPECIAL.sub(" ", _STRING.sub("''", right.upper()))
    text = re.sub(r"%\w+\(", "(", text)  # built-in names are not operands
    return bool(re.search(r"[\w)]\s*[-+*/]\s*[\w(]", text))


def _target(s: Statement) -> str:
    """The file or record format of a WRITE / UPDATE / DELETE (fixed: factor 2; free: its last operand)."""
    operands = s.factor2.split()
    return operands[-1].split("(")[0].upper() if operands else ""


def _text_fields(program: RpgProgram) -> set[str]:
    return {f.name for f in program.fields if f.kind in ("A", "CHAR", "VARCHAR", "N", "IND")}


def detect(program: RpgProgram, device_formats: Iterable[str] = ()) -> list[EngineQuirk]:
    """The quirks this program relies on, with the lines that rely on each (at most LINES_AT_MOST). The record
    formats of its display and printer files (from their DDS) are output to a device, never a database write."""
    devices = {name.upper() for name in device_formats} | {
        f.name for f in program.files if f.device in ("PRINTER", "WORKSTN")}  # fmt: skip
    found: dict[str, set[int]] = {}

    def add(quirk: str, lines: Iterable[int]) -> None:
        found.setdefault(quirk, set()).update(lines)

    statements = program.statements()
    text_fields = _text_fields(program)
    for f in program.files:
        if f.primary:
            add("rpg-cycle", [f.line])
    for s in statements:
        computes = s.base in _FIXED_ARITHMETIC or _assigns_arithmetic(s)
        if computes and "H" in s.extender:
            add("half-adjust", [s.line_start])
        elif computes:
            add("decimal-truncation", [s.line_start])
        if s.base in _FIXED_ARITHMETIC:
            add("fixed-overflow", [s.line_start])
        if s.base in ("EVAL", "EVALR") and "/" in _STRING.sub("", s.factor2.partition("=")[2]):
            add("intermediate-precision", [s.line_start])
        if s.base in ("MOVE", "MOVEL", "MOVEA"):
            add("move-semantics", [s.line_start])
        if s.base == "MVR":
            add("division-remainder", [s.line_start])
        if s.base in READS:
            add("record-not-found", [s.line_start])
            if s.base != "CHAIN" and any(f.keyed for f in program.files):  # a sequence by key, not an exact match
                add("ebcdic-order", [s.line_start])
        if s.base in ("SORTA", "LOOKUP") or "%LOOKUP" in s.factor2.upper():
            add("ebcdic-order", [s.line_start])
        ordered = re.search(r"<(?!>)|(?<!<)>", _STRING.sub("''", s.factor2))  # < > <= >=, not <>
        if s.base in _COMPARE and (ordered or s.opcode[-2:] in ("GT", "LT", "GE", "LE")):
            words = set(re.findall(r"[A-Z_#$@][A-Z0-9_#$@]*", _operands_text(s)))
            if words & text_fields or "''" in _operands_text(s):
                add("ebcdic-order", [s.line_start])
        if "E" in s.extender or s.base == "MONITOR" or "%ERROR" in s.factor2.upper() or (
                s.indicators and s.base not in _COMPARE and s.base not in ("SETON", "SETOFF")):  # fmt: skip
            add("errors-handled-by-program", [s.line_start])
        if s.level:
            add("level-breaks" if s.level != "LR" else "rpg-cycle", [s.line_start])
        if s.base in ("COMMIT", "ROLBK"):
            add("commitment-control", [s.line_start])
    for routine in program.routines:
        if routine.name == "*PSSR":
            add("errors-handled-by-program", [routine.line_start])
        if routine.name == "*INZSR":
            add("initialization-subroutine", [routine.line_start])
    writes = [s.line_start for s in statements if (s.base in WRITES and _target(s) not in devices) or (
        s.base == "EXEC SQL" and re.match(r"\s*(INSERT|UPDATE|DELETE|MERGE)\b", s.factor2, re.I))]  # fmt: skip
    committed = "commitment-control" in found or "COMMIT" in program.control
    if writes and not committed:
        add("immediate-writes", writes)
    if "OFLIND" in program.control:
        add("page-overflow", [f.line for f in program.files if f.device == "PRINTER"])
    return [EngineQuirk(id=key, severity=spec.severity, behavior=spec.behavior, target=spec.target,
                        file=program.file, lines=sorted(found[key])[:LINES_AT_MOST])
            for key, spec in CATALOG.items() if key in found]  # fmt: skip


def program_environment(program: RpgProgram) -> list[EnvironmentItem]:
    """What the program sets for itself: its control keywords and the default date format when it sets none."""
    items = [EnvironmentItem(key=f"rpg:{name.lower()}", value=value.strip().upper()[:500], source="program")
             for name, value in dict(_KEYWORD.findall(program.control)).items()]  # fmt: skip
    if "DATFMT(" not in program.control:
        items.append(EnvironmentItem(key="rpg:datfmt", value="*ISO (default)", source="program"))
    return items


__all__ = ["CATALOG", "LINES_AT_MOST", "Spec", "detect", "program_environment"]
