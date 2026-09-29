"""Classification hints and program slicing for Sybase procedures (spec 6.1 phases 4-5, 8.2 `classify_hints` and
`slice`). Deterministic: they narrow what an agent reads, they do not decide what a rule is.

- **Classification:** each statement is infrastructure (error codes, transaction control, printing, logging calls),
  control flow (IF/WHILE/GOTO/blocks) or business logic (computations, DML on business tables, business calls).
- **Slicing:** the backward slice of a statement: the statements that can change the values it uses (data
  dependencies through variables and tables) and the conditions that decide whether it runs (control dependencies),
  with the procedure parameters it depends on. A slice is a small set of line ranges an agent reads instead of the
  whole file (5.4).
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from nexti_adapter_sybase.parser import Procedure, Statement

Label = Literal["infrastructure", "control_flow", "business"]

# Calls that only report or log errors in COBIS-style code; a project can extend the list.
INFRASTRUCTURE_CALLS = {"sp_cerror", "cobis..sp_cerror", "sp_print", "sp_log", "sp_errorlog"}
INFRASTRUCTURE_KINDS = {"begin_tran", "commit", "rollback", "save_tran", "raiserror", "print", "label", "declare"}
CONTROL_KINDS = {"if", "while", "block", "goto", "break", "continue", "return"}


@dataclass(frozen=True)
class Hint:
    statement: int
    label: Label
    reason: str


def _short(name: str) -> str:
    return name.split(".")[-1]


def classify(procedure: Procedure, infrastructure_calls: Iterable[str] = ()) -> list[Hint]:
    extra = {c.lower() for c in infrastructure_calls}
    calls = INFRASTRUCTURE_CALLS | extra
    hints: list[Hint] = []
    for stmt in procedure.statements():
        if stmt.kind in INFRASTRUCTURE_KINDS:
            hints.append(Hint(stmt.id, "infrastructure", f"{stmt.kind.replace('_', ' ')} statement"))
        elif stmt.kind == "exec" and stmt.calls and (stmt.calls[0] in calls or _short(stmt.calls[0]) in calls):
            hints.append(Hint(stmt.id, "infrastructure", f"error or log call {stmt.calls[0]}"))
        elif stmt.kind in ("if", "while") and stmt.checks_error and not stmt.reads:
            hints.append(Hint(stmt.id, "infrastructure", "checks @@error / @@rowcount"))
        elif stmt.kind in CONTROL_KINDS:
            hints.append(Hint(stmt.id, "control_flow", f"{stmt.kind} statement"))
        elif stmt.kind in ("select", "set") and stmt.checks_error and not stmt.reads:
            hints.append(Hint(stmt.id, "infrastructure", "copies @@error / @@rowcount"))
        elif stmt.kind in ("insert", "update", "delete", "truncate") and all(t.startswith("#") for t in stmt.writes):
            hints.append(Hint(stmt.id, "infrastructure", "work table only"))
        else:
            hints.append(Hint(stmt.id, "business", _business_reason(stmt)))
    return hints


def _business_reason(stmt: Statement) -> str:
    if stmt.writes:
        return "writes " + ", ".join(sorted(stmt.writes))
    if stmt.calls:
        return "calls " + stmt.calls[0]
    if stmt.reads:
        return "reads " + ", ".join(sorted(stmt.reads))
    return "computes " + ", ".join(sorted(stmt.vars_written)) if stmt.vars_written else "business statement"


@dataclass
class Slice:
    target: int
    statements: list[int]
    lines: list[tuple[int, int]]  # merged line ranges, ascending
    parameters: list[str]  # procedure parameters the target depends on
    tables: list[str] = field(default_factory=list)

    @property
    def line_count(self) -> int:
        return sum(end - start + 1 for start, end in self.lines)


def _parents(procedure: Procedure) -> dict[int, list[Statement]]:
    """For each statement, the chain of IF/WHILE statements that control it (outermost first)."""
    result: dict[int, list[Statement]] = {}

    def visit(stmt: Statement, chain: list[Statement]) -> None:
        result[stmt.id] = chain
        inner = [*chain, stmt] if stmt.kind in ("if", "while") else chain
        for child in (*stmt.children, *stmt.orelse):
            visit(child, inner)

    for top in procedure.body:
        visit(top, [])
    return result


def _merge(ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def backward_slice(procedure: Procedure, target: int) -> Slice:
    """The statements that can affect statement `target`, by reaching definitions: for each variable a statement
    reads, the earlier writes are taken from the nearest backwards, stopping at a write that always runs before the
    reader (same or enclosing block, not inside a branch the reader is outside of). Writes inside an enclosing loop
    also count, because the loop can come back. Tables are conservative (every earlier write of a table read), and
    the IF/WHILE conditions that decide whether a statement runs are included with the variables they read."""
    statements = procedure.statements()
    by_id = {s.id: s for s in statements}
    if target not in by_id:
        raise KeyError(target)
    parents = _parents(procedure)
    chains = {sid: [p.id for p in chain] for sid, chain in parents.items()}
    params = {p.name for p in procedure.parameters}
    writers = [s for s in statements if s.kind not in ("block", "if", "while")]
    included: set[int] = set()
    used_vars: set[str] = set()
    work = [target]
    while work:
        sid = work.pop()
        if sid in included:
            continue
        included.add(sid)
        stmt = by_id[sid]
        used_vars |= stmt.vars_read
        work += [p.id for p in parents[sid] if p.id not in included]
        loops = [p for p in parents[sid] if p.kind == "while"]
        in_loop = {c.id for loop in loops for c in loop.walk()}
        for var in stmt.vars_read:
            for other in reversed([w for w in writers if w.id < sid]):
                if var not in other.vars_written:
                    continue
                work.append(other.id)
                # The write dominates the reader when its control chain is a prefix of the reader's chain.
                chain, own = chains[other.id], chains[sid]
                if own[: len(chain)] == chain and not other.vars_read & {var} - {var}:
                    break
            work += [w.id for w in writers if w.id > sid and w.id in in_loop and var in w.vars_written]
        for table in stmt.reads:
            work += [w.id for w in writers if (w.id < sid or w.id in in_loop) and table in w.writes]
    chosen = sorted(included)
    ranges: list[tuple[int, int]] = []
    for sid in chosen:
        stmt = by_id[sid]
        if stmt.kind in ("if", "while") and stmt.condition_lines and sid != target:
            ranges.append((stmt.line_start, stmt.condition_lines[1]))
        elif stmt.kind != "block":
            ranges.append((stmt.line_start, stmt.line_end))
    used_params = sorted(v for v in used_vars if v in params)
    tables = sorted({t for sid in chosen for t in (*by_id[sid].reads, *by_id[sid].writes)})
    return Slice(target, chosen, _merge(ranges), used_params, tables)


def slice_targets(procedure: Procedure) -> list[int]:
    """Where business outcomes happen: writes to business tables, business calls, assignments of OUTPUT parameters and
    returns with a value. Each is a candidate unit for rule extraction."""
    outputs = {p.name for p in procedure.parameters if p.output}
    hints = {h.statement: h.label for h in classify(procedure)}
    targets: list[int] = []
    for stmt in procedure.statements():
        if hints.get(stmt.id) != "business" and stmt.kind != "return":
            continue
        if (
            (stmt.writes and not all(t.startswith("#") for t in stmt.writes))
            or (stmt.kind == "exec" and stmt.calls)
            or stmt.vars_written & outputs
        ):
            targets.append(stmt.id)
    return targets
