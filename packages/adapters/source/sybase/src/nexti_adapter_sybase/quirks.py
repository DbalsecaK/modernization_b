"""The behaviours of Sybase ASE a program relies on and a modern stack does differently, and the settings it runs
under (M28).

Each quirk of the catalog is found in the program by its tokens (never by the model), carries the lines that rely on
it, and a probe: a few statements the runner executes on the same engine that records the golden master, so the
register says what THIS engine does with ITS options, not what the manual says. The environment is measured the
same way (isolation, date format, language, character set, time zone) and completed with what the program and its
sources set (SET options, triggers)."""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from nexti_adapter_sybase.lexer import Token, tokenize
from nexti_adapter_sybase.parser import Procedure, Statement
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import EngineQuirk, EnvironmentItem, QuirkSeverity

QUIRK_MARK = "NXQ|"
ENV_MARK = "NXE|"
LINES_AT_MOST = 50

_CHAR = re.compile(r"^(n|uni)?(var)?char\b|^(uni)?text\b|^sysname\b", re.IGNORECASE)
_FIXED_CHAR = re.compile(r"^(n|uni)?char\b", re.IGNORECASE)
_INT = re.compile(r"^(int|integer|smallint|tinyint|bigint|unsigned\s+\w*int)\b", re.IGNORECASE)
_COMPARING = {"IF", "WHILE", "WHERE", "AND", "OR", "WHEN", "HAVING", "ON", "NOT"}
_TRIGGER = re.compile(r"create\s+trigger\s+([\w.\[\]]+)\s+on\s+([\w.\[\]]+)", re.IGNORECASE)


@dataclass(frozen=True)
class Spec:
    id: str
    severity: QuirkSeverity
    behavior: str
    target: str
    probe: str = ""
    expected: str = ""


CATALOG: dict[str, Spec] = {
    s.id: s
    for s in (
        Spec("null-compare", "critical",
             "With ansinull off (the default) `x = NULL` is true when x is NULL and `x <> NULL` is true when it is "
             "not: the comparison works as IS NULL / IS NOT NULL.",
             "Write these comparisons as null checks (== null / is null), never as SQL three-valued comparisons.",
             "declare @n int\nselect @n = null\nif @n = null select 'NXQ|null-compare|true' "
             "else select 'NXQ|null-compare|false'",
             "true"),
        Spec("null-concat", "high",
             "Concatenating a string with NULL gives the string ('a' + NULL = 'a'), not NULL.",
             "Treat a null operand as an empty string when concatenating.",
             "select 'NXQ|null-concat|' + isnull('a' + null, '<null>')", "a"),
        Spec("empty-string", "high",
             "The empty string '' is a single space: its length is 1 and it is stored as ' '.",
             "Where the program writes or compares '', produce and compare ' ' (or trim consistently) as the golden "
             "master shows.",
             "select 'NXQ|empty-string|' + convert(varchar(10), datalength(''))", "1"),
        Spec("select-assign-from-table", "high",
             "`select @v = col from t where ...` leaves @v unchanged when no row matches and keeps the LAST row "
             "when several match; it never fails.",
             "Keep the previous value when the query returns nothing and take the last row when it returns several; "
             "do not throw on an empty or multiple result.",
             "declare @v int\nselect @v = 5\nselect @v = id from sysobjects where 1 = 2\n"
             "select 'NXQ|select-assign-from-table|' + convert(varchar(10), @v)",
             "5"),
        Spec("error-continues", "high",
             "A failing statement does not stop the procedure: execution goes on and the program decides with "
             "@@error and @@rowcount, which every statement resets.",
             "Read the outcome of each statement right after it (rows affected, error) and continue as the program "
             "does; do not let an exception skip the code the legacy runs after the error."),
        Spec("nested-tran", "high",
             "Transactions nest by count (@@trancount); a ROLLBACK at any level rolls back everything and sets the "
             "count to 0.",
             "Use one transaction for the whole program and roll it back entirely where the program rolls back.",
             "begin tran\nbegin tran\nrollback tran\nselect 'NXQ|nested-tran|' + convert(varchar(10), @@trancount)",
             "0"),
        Spec("rowcount-option", "high",
             "`set rowcount N` limits every following statement of the session (selects, updates, deletes) until "
             "`set rowcount 0`.",
             "Apply the same row limit to every statement between the two SETs.",
             "create table #nxq (a int)\ninsert #nxq values (1)\ninsert #nxq values (2)\nset rowcount 1\n"
             "update #nxq set a = 0\nselect 'NXQ|rowcount-option|' + convert(varchar(10), @@rowcount)\n"
             "set rowcount 0\ndrop table #nxq",
             "1"),
        Spec("char-padding", "medium",
             "Comparisons ignore trailing spaces ('a' = 'a  ') and CHAR(n) values are padded with spaces to n.",
             "Compare strings without their trailing spaces and pad or trim CHAR values as the golden master shows.",
             "if 'a' = 'a  ' select 'NXQ|char-padding|true' else select 'NXQ|char-padding|false'", "true"),
        Spec("integer-division", "medium",
             "Dividing two integers truncates toward zero (7 / 2 = 3).",
             "Use integer division where both operands are integers.",
             "select 'NXQ|integer-division|' + convert(varchar(10), 7 / 2)", "3"),
        Spec("date-style", "medium",
             "CONVERT with a style number formats dates in the engine's fixed formats (style 103 is dd/mm/yyyy).",
             "Format with the exact pattern of each style used, independent of the locale.",
             "select 'NXQ|date-style|' + convert(varchar(10), convert(datetime, '20240305'), 103)", "05/03/2024"),
    )
}  # fmt: skip

ENVIRONMENT_PROBES: tuple[tuple[str, str], ...] = (
    ("version", "substring(@@version, 1, 120)"),
    ("isolation-level", "convert(varchar(10), @@isolation)"),
    ("datefirst", "convert(varchar(10), @@datefirst)"),
    ("language", "@@language"),
    ("client-charset", "@@client_csname"),
    ("textsize", "convert(varchar(20), @@textsize)"),
    ("utc-offset-minutes", "convert(varchar(10), datediff(mi, getutcdate(), getdate()))"),
    ("date-input-03/05/2024", "convert(varchar(10), convert(datetime, '03/05/2024'), 112)"),
)


def _types(procedure: Procedure) -> dict[str, str]:
    types = {p.name.lower(): p.type for p in procedure.parameters}
    for stmt in procedure.statements():
        types.update({name.lower(): kind for name, kind in stmt.declared.items()})
    return types


def _matches(tokens: Sequence[Token], types: dict[str, str]) -> dict[str, set[int]]:
    """Quirk id -> lines, from the tokens of the program."""
    found: dict[str, set[int]] = {}

    def typed(tok: Token | None, pattern: re.Pattern[str]) -> bool:
        return tok is not None and tok.kind == "variable" and bool(pattern.match(types.get(tok.text.lower(), "")))

    def integer(tok: Token | None) -> bool:
        if tok is None:
            return False
        return (tok.kind == "number" and tok.text.isdigit()) or typed(tok, _INT)

    def comparing(index: int) -> bool:
        """An `=` inside a condition (IF, WHERE, AND, WHEN...), not an assignment (SELECT @v =, SET col =, a
        parameter default): the nearest owner word back decides, and a comma means a list of assignments."""
        for back in range(index - 1, -1, -1):
            tok = tokens[back]
            if tok.kind == "word" and tok.upper in _COMPARING:
                return True
            if tok.is_symbol(",") or tok.is_word("SELECT", "SET", "UPDATE", "DECLARE", "PROC", "PROCEDURE"):
                return False
        return False

    def add(quirk: str, line: int) -> None:
        found.setdefault(quirk, set()).add(line)

    for i, tok in enumerate(tokens):
        prev = tokens[i - 1] if i > 0 else None
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if tok.kind == "string" and tok.text == "''":
            add("empty-string", tok.line)
        if tok.is_symbol("+") and any(t is not None and (t.kind == "string" or typed(t, _CHAR)) for t in (prev, nxt)):
            add("null-concat", tok.line)
        if (
            tok.is_symbol("=", "<>", "!=")
            and ((nxt is not None and nxt.is_word("NULL")) or (prev is not None and prev.is_word("NULL")))
            and comparing(i)
        ):
            add("null-compare", tok.line)
        if tok.is_symbol("/") and integer(prev) and integer(nxt):
            add("integer-division", tok.line)
        if tok.is_symbol("=", "<>", "!=") and (typed(prev, _FIXED_CHAR) or typed(nxt, _FIXED_CHAR)):
            add("char-padding", tok.line)
        if tok.is_word("SET") and nxt is not None and nxt.is_word("ROWCOUNT"):
            add("rowcount-option", tok.line)
        if tok.is_word("CONVERT") and nxt is not None and nxt.is_symbol("("):
            depth, commas = 0, 0
            for later in tokens[i + 1 :]:
                if later.is_symbol("("):
                    depth += 1
                elif later.is_symbol(")"):
                    depth -= 1
                    if depth == 0:
                        break
                elif later.is_symbol(",") and depth == 1:
                    commas += 1
            if commas >= 2:
                add("date-style", tok.line)
    return found


def _statement_quirks(statements: Sequence[Statement]) -> dict[str, set[int]]:
    found: dict[str, set[int]] = {}
    rules: dict[str, Callable[[Statement], bool]] = {
        "select-assign-from-table": lambda s: s.kind == "select" and bool(s.vars_written) and bool(s.reads),
        "error-continues": lambda s: s.checks_error,
        "nested-tran": lambda s: s.kind in ("begin_tran", "rollback", "save_tran"),
    }
    for stmt in statements:
        for quirk, applies in rules.items():
            if applies(stmt):
                found.setdefault(quirk, set()).add(stmt.line_start)
    return found


def detect(source: SourceFile, procedure: Procedure) -> list[EngineQuirk]:
    """The quirks of the catalog the program relies on, each with its lines (not probed yet)."""
    tokens, _ = tokenize(source.text)
    body = [t for t in tokens if procedure.line_start <= t.line <= procedure.line_end]
    found = _matches(body, _types(procedure))
    for quirk, lines in _statement_quirks(procedure.statements()).items():
        found.setdefault(quirk, set()).update(lines)
    order = list(CATALOG)
    return [
        EngineQuirk(id=spec.id, severity=spec.severity, behavior=spec.behavior, target=spec.target, file=source.path,
                    lines=sorted(found[spec.id])[:LINES_AT_MOST], probe=spec.probe, expected=spec.expected)
        for spec in (CATALOG[q] for q in sorted(found, key=order.index))
    ]  # fmt: skip


def probe_script(quirks: Sequence[EngineQuirk]) -> str:
    """One batch per probe: a probe the engine rejects leaves the others standing."""
    return "".join(f"{q.probe}\ngo\n" for q in quirks if q.probe)


def environment_script() -> str:
    return "".join(f"select '{ENV_MARK}{key}|' + {expr}\ngo\n" for key, expr in ENVIRONMENT_PROBES)


def _marked(output: str, mark: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        at = line.find(mark)
        if at < 0:
            continue
        key, _, value = line[at + len(mark) :].partition("|")
        if key and _:
            values[key] = value.rstrip()
    return values


def probe_answers(output: str) -> dict[str, str]:
    """Quirk id -> what the engine answered to its probe."""
    return _marked(output, QUIRK_MARK)


def engine_environment(output: str) -> list[EnvironmentItem]:
    values = _marked(output, ENV_MARK)
    return [EnvironmentItem(key=k, value=values[k][:500], source="engine") for k, _ in ENVIRONMENT_PROBES
            if k in values]  # fmt: skip


def program_environment(files: Sequence[SourceFile], source: SourceFile, procedure: Procedure) -> list[EnvironmentItem]:
    """The SET options the program changes and the triggers its sources define (they run on the program's writes)."""
    items: list[EnvironmentItem] = []
    tokens, _ = tokenize(source.text)
    body = [t for t in tokens if procedure.line_start <= t.line <= procedure.line_end]
    seen: set[str] = set()
    starts = {s.line_start for s in procedure.statements() if s.kind == "set"}  # SET statements, not UPDATE ... SET
    for i, tok in enumerate(body):
        nxt = body[i + 1] if i + 1 < len(body) else None
        if not tok.is_word("SET") or tok.line not in starts or nxt is None or nxt.kind != "word":
            continue
        if nxt.upper in seen:
            continue
        rest = " ".join(t.text for t in body[i + 2 :] if t.line == tok.line)
        seen.add(nxt.upper)
        items.append(EnvironmentItem(key=f"set {nxt.text.lower()}", value=f"{rest} (line {tok.line})"[:500],
                                     source="program"))  # fmt: skip
    for file in files:
        for match in _TRIGGER.finditer(file.text):
            items.append(EnvironmentItem(key=f"trigger {match.group(1)}", value=f"on {match.group(2)} ({file.path})",
                                         source="program"))  # fmt: skip
    return items
