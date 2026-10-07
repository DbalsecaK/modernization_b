"""Which branches of the legacy program the golden master exercises (M27a, ADR-0047).

The golden master is always recorded with the original program. Coverage comes from a second pass over the same
cases with an instrumented COPY: a `print 'NXB|<id>'` as the first statement of every branch body (the THEN and ELSE
of an IF, an implicit ELSE, the body of a WHILE). A case whose instrumented run observes anything different from the
original is marked unreliable, so the instrumentation never changes the oracle. A branch that cannot be instrumented
without risk (a one-statement body sharing its line with other code) is reported as not measurable, never as
covered."""

import re
from dataclasses import dataclass, field

from nexti_adapter_sybase.parser import Procedure, Statement

MARK = "NXB|"
_BEGIN = re.compile(r"\bbegin\b(?!\s+tran)", re.IGNORECASE)
_ELSE = re.compile(r"\belse\b", re.IGNORECASE)


@dataclass(frozen=True)
class Branch:
    id: str
    kind: str  # if-true, if-false, else, loop
    line_start: int
    line_end: int
    measurable: bool


@dataclass
class Instrumented:
    text: str
    branches: list[Branch] = field(default_factory=list)


def instrument(text: str, program: Procedure) -> Instrumented:
    """The program text with a mark at the start of every measurable branch, and every branch found."""
    lines = text.split("\n")
    before: dict[int, list[str]] = {}  # 1-based line -> lines inserted before it
    after: dict[int, list[str]] = {}  # 1-based line -> lines inserted after it
    inline: dict[int, list[tuple[int, str]]] = {}  # line -> (occurrence of BEGIN, text inserted after it)
    statements = program.statements()
    begins_by_line: dict[int, list[Statement]] = {}
    for stmt in statements:
        if stmt.kind == "block":
            begins_by_line.setdefault(stmt.line_start, []).append(stmt)
    starts: dict[int, int] = {}
    for stmt in statements:
        starts[stmt.line_start] = starts.get(stmt.line_start, 0) + 1
    found: list[Branch] = []

    def alone(body: Statement) -> bool:
        """The body owns its lines: no other statement starts on them and no ELSE shares its last line."""
        inside = {id(s) for s in body.walk()}
        for stmt in statements:
            if id(stmt) not in inside and body.line_start <= stmt.line_start <= body.line_end:
                return False
        last = lines[body.line_end - 1] if body.line_end - 1 < len(lines) else ""
        return not _ELSE.search(last)

    def mark(owner: Statement, body: Statement, kind: str) -> None:
        branch_id = f"{body.line_start}-{body.line_end}:{kind}"
        if body.kind == "block":
            occurrence = begins_by_line[body.line_start].index(body)
            inline.setdefault(body.line_start, []).append((occurrence, f" print '{MARK}{branch_id}' "))
            found.append(Branch(branch_id, kind, body.line_start, body.line_end, True))
            return
        conditions_end = owner.condition_lines[1] if owner.condition_lines else owner.line_start
        own_line = (body.line_start > conditions_end and kind != "else") or body.line_start > _else_line(owner, lines)
        if own_line and alone(body):
            before.setdefault(body.line_start, []).append(f"begin print '{MARK}{branch_id}'")
            after.setdefault(body.line_end, []).append("end")
            found.append(Branch(branch_id, kind, body.line_start, body.line_end, True))
        else:
            found.append(Branch(branch_id, kind, body.line_start, body.line_end, False))

    for stmt in statements:
        if stmt.kind not in ("if", "while") or not stmt.children:
            continue
        then = stmt.children[0]
        mark(stmt, then, "loop" if stmt.kind == "while" else "if-true")
        if stmt.kind != "if":
            continue
        if stmt.orelse:
            mark(stmt, stmt.orelse[0], "else")
            continue
        # An IF without ELSE: its false path is a branch too. An ELSE is added after the IF only when nothing else
        # follows on that line and it cannot attach to an inner IF.
        branch_id = f"{stmt.line_start}-{stmt.line_end}:if-false"
        safe = then.kind != "if" and starts.get(stmt.line_end, 0) <= _starting_inside(stmt, stmt.line_end)
        if safe and stmt.line_end not in inline_lines(inline):
            after.setdefault(stmt.line_end, []).append(f"else print '{MARK}{branch_id}'")
            found.append(Branch(branch_id, "if-false", stmt.line_start, stmt.line_end, True))
        else:
            found.append(Branch(branch_id, "if-false", stmt.line_start, stmt.line_end, False))

    out: list[str] = []
    for number, line in enumerate(lines, start=1):
        out.extend(before.get(number, []))
        if number in inline:
            line = _insert_after_begins(line, inline[number])
        out.append(line)
        out.extend(after.get(number, []))
    return Instrumented("\n".join(out), found)


def inline_lines(inline: dict[int, list[tuple[int, str]]]) -> set[int]:
    return set(inline)


def _starting_inside(stmt: Statement, line: int) -> int:
    return sum(1 for s in stmt.walk() if s.line_start == line)


def _else_line(owner: Statement, lines: list[str]) -> int:
    """The line of the ELSE of an IF (the line before its ELSE body when it is not on the same line)."""
    then = owner.children[0] if owner.children else None
    start = then.line_end if then else owner.line_start
    for number in range(start, owner.line_end + 1):
        if _ELSE.search(lines[number - 1] if number - 1 < len(lines) else ""):
            return number
    return start


def _insert_after_begins(line: str, inserts: list[tuple[int, str]]) -> str:
    positions = [m.end() for m in _BEGIN.finditer(line)]
    for occurrence, text in sorted(inserts, reverse=True):
        if occurrence < len(positions):
            at = positions[occurrence]
            line = line[:at] + text + line[at:]
    return line


def executed(output: str) -> tuple[set[str], str]:
    """The branches a run printed, and its output without the marks (what `observe` reads)."""
    hits: set[str] = set()
    kept: list[str] = []
    for line in output.splitlines():
        text = line.strip()
        if text.startswith(MARK):
            hits.add(text[len(MARK) :])
        else:
            kept.append(line)
    return hits, "\n".join(kept)
