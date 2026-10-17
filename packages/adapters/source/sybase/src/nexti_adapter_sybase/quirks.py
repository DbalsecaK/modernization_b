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
_MONEY = re.compile(r"^(small)?money\b", re.IGNORECASE)
_SIZED_CHAR = re.compile(r"^(n|uni)?(var)?char\s*\(\s*(\d+)\s*\)", re.IGNORECASE)
_DECIMAL = re.compile(r"^(decimal|numeric)\s*\(\s*\d+\s*,\s*(\d+)\s*\)", re.IGNORECASE)
_ENDS_EXPRESSION = {"SELECT", "SET", "FROM", "WHERE", "IF", "ELSE", "WHILE", "BEGIN", "END", "RETURN", "EXEC",
                    "EXECUTE", "DECLARE", "INSERT", "UPDATE", "DELETE", "PRINT", "GOTO", "BREAK",
                    "CONTINUE"}  # fmt: skip
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
        # ADR-0055 (I.18): the behaviours the double check of sp_debcred_empresa named, measured on the engine.
        Spec("varchar-assign-truncates", "medium",
             "Assigning a longer value to a CHAR/VARCHAR(n) variable or column keeps its first n characters "
             "silently (no error, no warning).",
             "Truncate to the declared length wherever the program assigns to a sized string, as the golden master "
             "shows; never let a longer value through or fail on it.",
             "declare @v varchar(5)\nselect @v = 'ABCDEFGH'\nselect 'NXQ|varchar-assign-truncates|' + @v", "ABCDE"),
        Spec("money-to-int-rounds", "high",
             "Converting MONEY to an integer rounds to the nearest unit (2.7 -> 3, -2.7 -> -3), and dividing two "
             "MONEY values keeps four decimals (7 / 2 = 3.50), so an integer variable receives 4, not 3.",
             "Round half away from zero when a money amount lands in an integer; keep money division exact "
             "(scale 4) and round only at the assignment.",
             "declare @i int, @j int, @m money, @a money, @b money\nselect @m = 2.7, @a = 7, @b = 2\n"
             "select @i = @m\nselect @j = @a / @b\nselect 'NXQ|money-to-int-rounds|' + convert(varchar(10), @i) "
             "+ '|' + convert(varchar(10), convert(int, convert(money, -2.7))) + '|' + convert(varchar(10), @j)",
             "3|-3|4"),
        Spec("substring-no-match-errors", "high",
             "SUBSTRING with a length below 1 (PATINDEX/CHARINDEX found nothing, minus one) raises error 536; the "
             "assignment is skipped, the variable keeps its previous value and the procedure goes on.",
             "When the searched separator is absent, do what the legacy does after the error: keep the previous "
             "value of the variable and continue (or whatever the program does with @@error); never slice "
             "with a negative length nor throw out of the program.",
             "declare @v varchar(10), @e int\nselect @v = 'KEEP'\n"
             "select @v = substring('ABC', 1, patindex('%-%', 'ABC') - 1)\nselect @e = @@error\n"
             "select 'NXQ|substring-no-match-errors|' + @v + '|' + convert(varchar(10), @e)",
             "KEEP|536"),
        Spec("decimal-scale-assign-errors", "high",
             "Assigning a value with more decimals than the scale to a DECIMAL(p,s) variable (a literal, a variable "
             "of a larger scale, the result of a division) raises error 241 (scale error) and aborts the batch; "
             "the value is not rounded.",
             "Give decimal variables exactly the scale of the legacy and fail where the legacy fails; do not "
             "round a value the legacy rejects.",
             "declare @e int\nexec('declare @d decimal(10,2) select @d = 2.345')\nselect @e = @@error\n"
             "select 'NXQ|decimal-scale-assign-errors|' + convert(varchar(10), @e)",
             "241"),
        Spec("decimal-convert-truncates", "medium",
             "CONVERT to DECIMAL(p,s) cuts the extra decimals, it does not round (2.345 -> 2.34, 2.355 -> 2.35).",
             "Truncate (round toward zero) when the program converts to a decimal of fewer decimals; use the "
             "rounding the golden master shows, never the platform's default half-up rounding.",
             "select 'NXQ|decimal-convert-truncates|' + convert(varchar(20), convert(decimal(10,2), 2.345)) + '|' "
             "+ convert(varchar(20), convert(decimal(10,2), 2.355))",
             "2.34|2.35"),
        Spec("isnull-keeps-replacement", "low",
             "ISNULL returns the replacement whole, even when it is longer than the type of the first argument "
             "(isnull(convert(varchar(2), null), 'LONGER') = 'LONGER').",
             "Return the replacement as it is; do not truncate it to the length of the value it replaces.",
             "select 'NXQ|isnull-keeps-replacement|' + isnull(convert(varchar(2), null), 'LONGER')", "LONGER"),
        Spec("param-default-vs-null", "high",
             "A parameter with a default takes it only when the caller omits the argument; an explicit NULL stays "
             "NULL and the default does not apply.",
             "Distinguish an omitted argument (the default applies) from a null one (it stays null): a request "
             "field that is absent is not the same as one that is null.",
             "exec('create proc nxq_p @a int = 7, @o int output as select @o = @a')\n"
             "declare @r1 int, @r2 int\nexec nxq_p @o = @r1 output\nexec nxq_p null, @r2 output\n"
             "select 'NXQ|param-default-vs-null|' + isnull(convert(varchar(10), @r1), '<null>') + '|' "
             "+ isnull(convert(varchar(10), @r2), '<null>')\ndrop proc nxq_p",
             "7|<null>"),
        Spec("callee-raiserror-continues", "high",
             "An error raised inside a called procedure (raiserror) does not abort the caller: execution goes on, "
             "@@error is 0 after the exec, and only the return status (exec @rc = proc) carries the failure.",
             "Read the status the called program returns and act on it as the legacy does; do not expect an "
             "exception from the call, and do not let one abort what the legacy continues.",
             "exec('create proc nxq_f as raiserror 20001 ''fallo'' return 5')\n"
             "declare @rc int, @e int\nselect @rc = 99\nexec @rc = nxq_f\nselect @e = @@error\n"
             "select 'NXQ|callee-raiserror-continues|' + isnull(convert(varchar(10), @rc), '<null>') + '|' "
             "+ convert(varchar(10), @e)\ndrop proc nxq_f",
             "5|0"),
        Spec("rowcount-per-statement", "medium",
             "@@rowcount holds the row count of the LAST statement and an assignment to a variable counts as one "
             "row: `select @e = @@error` leaves @@rowcount at 1. An IF or WHILE condition reads it without "
             "resetting it.",
             "Capture the row count right after the statement it belongs to (or in the same step as @@error); a "
             "later read sees the count of whatever ran in between.",
             "declare @e int, @n int, @m int\nselect name from sysobjects where 1 = 2\n"
             "if @@rowcount = 0 select @m = @@rowcount\nselect name from sysobjects where 1 = 2\n"
             "select @e = @@error\nselect @n = @@rowcount\n"
             "select 'NXQ|rowcount-per-statement|' + convert(varchar(10), @n) + '|' + convert(varchar(10), @m)",
             "1|0"),
        Spec("money-to-char", "medium",
             "Converting MONEY to a string gives exactly two decimals and no separators (1234.50); style 1 adds "
             "thousands separators (1,234.50); an amount that rounds to zero keeps its sign (-0.00).",
             "Format money with two decimals as the legacy does (separators only where it uses style 1); keep the "
             "sign of a negative amount that rounds to zero when the golden master shows it.",
             "select 'NXQ|money-to-char|' + convert(varchar(20), convert(money, 1234.5)) + '|' "
             "+ convert(varchar(20), convert(money, 1234.5), 1) + '|' + convert(varchar(20), convert(money, -0.004))",
             "1234.50|1,234.50|-0.00"),
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

    def size_of(tok: Token | None, pattern: re.Pattern[str], group: int) -> int | None:
        """The declared length (or scale) of a variable, when its type carries one."""
        if tok is None or tok.kind != "variable":
            return None
        match = pattern.match(types.get(tok.text.lower(), ""))
        return int(match.group(group)) if match else None

    def expression(start: int) -> list[Token]:
        """The tokens of the expression that starts at `start`: up to the next statement word, a comma outside
        parentheses or a change of line outside parentheses."""
        out: list[Token] = []
        depth = 0
        for later in tokens[start:]:
            if depth == 0 and (later.is_symbol(",") or (later.kind == "word" and later.upper in _ENDS_EXPRESSION)):
                break
            if depth == 0 and out and later.line != out[-1].line:
                break
            if later.is_symbol("("):
                depth += 1
            elif later.is_symbol(")"):
                if depth == 0:
                    break
                depth -= 1
            out.append(later)
        return out

    def decimals(tok: Token) -> int:
        return len(tok.text.rsplit(".", 1)[1]) if tok.kind == "number" and "." in tok.text else 0

    def overflows(value: list[Token], size: int) -> bool:
        """Whether a value may be longer than `size`: a literal or a sized variable that is, or a concatenation
        whose known lengths add up to more (or include something of unknown length: a function, an unsized
        variable)."""
        lengths = [len(t.text) - 2 if t.kind == "string" else size_of(t, _SIZED_CHAR, 3)
                   for t in value if t.kind in ("string", "variable")]  # fmt: skip
        if any(length is not None and length > size for length in lengths):
            return True
        if not any(t.is_symbol("+") for t in value):
            return False
        unknown = any(t.kind == "word" for t in value) or None in lengths
        return unknown or sum(length or 0 for length in lengths) > size

    def expression_after(start: int, commas: int) -> list[Token]:
        """The tokens of the argument `commas` commas after the one that starts at `start`."""
        at = start
        for _ in range(commas):
            at += len(expression(at)) + 1
            if at >= len(tokens) or not tokens[at - 1].is_symbol(","):
                return []
        return expression(at)

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
        if tok.is_symbol("=") and prev is not None and prev.kind == "variable" and not comparing(i):
            value = expression(i + 1)
            size = size_of(prev, _SIZED_CHAR, 3)
            if size is not None and overflows(value, size):
                add("varchar-assign-truncates", tok.line)
            if typed(prev, _INT) and any(typed(t, _MONEY) for t in value):
                add("money-to-int-rounds", tok.line)
            scale = size_of(prev, _DECIMAL, 2)
            if scale is not None and (
                any(decimals(t) > scale for t in value)
                or any((size_of(t, _DECIMAL, 2) or 0) > scale for t in value)
                or any(t.is_symbol("/") for t in value)
            ):
                add("decimal-scale-assign-errors", tok.line)
        if tok.is_word("CONVERT") and nxt is not None and nxt.is_symbol("("):
            inside = expression(i + 2)
            argument = expression(i + 2 + len(inside) + 1)
            if inside and _INT.match(inside[0].text) and any(typed(t, _MONEY) for t in argument):
                add("money-to-int-rounds", tok.line)
            if inside and _DECIMAL.match(" ".join(t.text for t in inside)):
                add("decimal-convert-truncates", tok.line)
            if inside and _CHAR.match(inside[0].text) and any(typed(t, _MONEY) for t in argument):
                add("money-to-char", tok.line)
        if tok.is_word("SUBSTRING") and nxt is not None and nxt.is_symbol("("):
            arguments = expression(i + 2) + expression_after(i + 2, 2)
            if any(t.is_word("PATINDEX", "CHARINDEX") for t in arguments):
                add("substring-no-match-errors", tok.line)
        if tok.is_word("ISNULL") and nxt is not None and nxt.is_symbol("("):
            first = expression(i + 2)
            second = expression_after(i + 2, 1)
            if any(t.kind == "string" for t in second) and not any(t.kind == "string" for t in first):
                add("isnull-keeps-replacement", tok.line)
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


def _statement_quirks(statements: Sequence[Statement], rowcount_lines: set[int] | None = None) -> dict[str, set[int]]:
    """`rowcount_lines`: the lines that read @@rowcount; one read right after a plain assignment sees 1."""
    found: dict[str, set[int]] = {}
    rules: dict[str, Callable[[Statement], bool]] = {
        "select-assign-from-table": lambda s: s.kind == "select" and bool(s.vars_written) and bool(s.reads),
        "error-continues": lambda s: s.checks_error,
        "nested-tran": lambda s: s.kind in ("begin_tran", "rollback", "save_tran"),
        "callee-raiserror-continues": lambda s: s.kind == "exec" and bool(s.calls),
    }
    previous: Statement | None = None
    for stmt in statements:
        for quirk, applies in rules.items():
            if applies(stmt):
                found.setdefault(quirk, set()).add(stmt.line_start)
        if (
            stmt.line_start in (rowcount_lines or set())
            and previous is not None
            and previous.kind in ("select", "set")
            and previous.vars_written
            and not previous.reads
            and not previous.writes
        ):
            found.setdefault("rowcount-per-statement", set()).add(stmt.line_start)
        previous = stmt
    return found


def detect(source: SourceFile, procedure: Procedure) -> list[EngineQuirk]:
    """The quirks of the catalog the program relies on, each with its lines (not probed yet)."""
    tokens, _ = tokenize(source.text)
    body = [t for t in tokens if procedure.line_start <= t.line <= procedure.line_end]
    found = _matches(body, _types(procedure))
    rowcount_lines = {t.line for t in body if t.kind == "global" and t.upper == "@@ROWCOUNT"}
    for quirk, lines in _statement_quirks(procedure.statements(), rowcount_lines).items():
        found.setdefault(quirk, set()).update(lines)
    for parameter in procedure.parameters:
        if parameter.default is not None:
            found.setdefault("param-default-vs-null", set()).add(parameter.line)
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
