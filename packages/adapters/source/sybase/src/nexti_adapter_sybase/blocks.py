"""Logical blocks inside a stored procedure (spec 5.2.1, ADR-0032): deterministic, no model involved.

A procedure is cut into blocks at its top level, in the order of the code:

- **hard cuts** (never merged away): a label (`ERROR:`, the target of GOTOs), `BEGIN TRAN` / `SAVE TRAN` (a block
  starts there) and `COMMIT` / `ROLLBACK` (the block ends with them);
- **soft cuts:** a section comment alone on its lines between two top-level statements (a banner made of `----`,
  `****` or `====`, or a comment that starts with a section tag such as `B1`, `RF-01:`, `STEP 2`), and a top-level
  IF / WHILE longer than `LARGE_BRANCH` lines (a block of its own);
- a block started by a soft cut that is shorter than `TINY_BLOCK` lines is merged into the previous one (a tiny
  opening block, usually the declarations, joins the next one instead).

When the whole body is one `BEGIN ... END`, its statements are the top level.

Each block has its phase: `pre` (before the first BEGIN TRAN), `transaction` (from BEGIN TRAN to its COMMIT or
ROLLBACK), `post` (after it) and `error` (a label targeted by an error GOTO, or a block that rolls back at its top
level and ends returning). The edges between blocks are `NEXT` (the code falls through to the next block: not after
an unconditional RETURN or GOTO), `GOTO` (a jump to a label) and `ON_ERROR` (a GOTO taken after checking `@@error`,
`@@rowcount`, a variable copied from them or named as an error or return code, or right after a ROLLBACK).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Literal

from nexti_adapter_sybase.lexer import Comment
from nexti_adapter_sybase.parser import Procedure, Statement

Phase = Literal["pre", "transaction", "post", "error"]
BlockEdgeKind = Literal["NEXT", "GOTO", "ON_ERROR"]

TINY_BLOCK = 8  # lines: a softly cut block shorter than this joins the previous one
LARGE_BRANCH = 40  # lines: a top-level IF / WHILE longer than this is a block of its own
_RULER = re.compile(r"[-*=#~_]{4,}")
_TAG = re.compile(r"^(?:[A-Z]{1,4}[-_ ]?\d+(?:\.\d+)*\b|(?i:section|secci[oó]n|step|paso|block|bloque|part|parte)\b)")
_ERROR_NAME = re.compile(
    r"^@(?:\w*_)?(?:err|error|errno|ret|return|rc|status|sqlcode|cod_error|codigo_error)$", re.IGNORECASE
)
_HARD_ENDS = ("commit", "rollback")


@dataclass(frozen=True)
class BlockEdge:
    source: str
    kind: BlockEdgeKind
    target: str
    line: int | None = None


@dataclass
class Block:
    id: str  # "<procedure>#B<n>", stable for the same code
    name: str
    line_start: int
    line_end: int
    phase: Phase
    statements: list[Statement]
    reads: set[str] = field(default_factory=set)  # tables (work tables excluded)
    writes: set[str] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)  # procedures, in order, without dynamic calls
    label: str | None = None


@dataclass
class _Part:
    statements: list[Statement]
    start: int  # first line (the banner when there is one)
    name: str | None
    hard: bool
    label: str | None = None


def _top_level(procedure: Procedure) -> list[Statement]:
    body = procedure.body
    while len(body) == 1 and body[0].kind == "block":
        body = body[0].children
    return body


def _comment_text(comment: Comment) -> list[str]:
    lines = []
    for raw in comment.text.splitlines():
        text = raw.strip()
        for marker in ("--", "/*", "*/"):
            text = text.replace(marker, " ")
        text = _RULER.sub(" ", text).strip(" *-=#/~_\t")
        if text:
            lines.append(" ".join(text.split()))
    return lines


def _banners(comments: Sequence[Comment], statements: Sequence[Statement]) -> dict[int, tuple[int, str | None]]:
    """For each top-level statement index preceded by a section comment: (first line of the banner, its title)."""
    groups: list[list[Comment]] = []
    for comment in sorted(comments, key=lambda c: c.line_start):
        if groups and comment.line_start <= groups[-1][-1].line_end + 1:
            groups[-1].append(comment)
        else:
            groups.append([comment])
    found: dict[int, tuple[int, str | None]] = {}
    for group in groups:
        first, last = group[0].line_start, group[-1].line_end
        index = next((k for k, s in enumerate(statements) if s.line_start > last), None)
        if index is None or (index > 0 and statements[index - 1].line_end >= first):
            continue  # after the last statement, or a comment trailing code / inside a statement
        texts = [t for c in group for t in _comment_text(c)]
        ruler = any(_RULER.search(c.text.replace("/*", "").replace("*/", "")) for c in group)
        if ruler or (texts and _TAG.match(texts[0])):
            found[index] = (first, texts[0][:80] if texts else None)
    return found


def _span(stmt: Statement) -> int:
    return stmt.line_end - stmt.line_start + 1


def _parts(procedure: Procedure, statements: list[Statement]) -> list[_Part]:
    banners = _banners(procedure.comments, statements)
    parts: list[_Part] = []
    previous: Statement | None = None
    for index, stmt in enumerate(statements):
        banner = banners.get(index)
        hard = stmt.kind in ("label", "begin_tran", "save_tran") or (
            previous is not None and previous.kind in _HARD_ENDS
        )
        large = stmt.kind in ("if", "while") and _span(stmt) > LARGE_BRANCH
        after_large = previous is not None and previous.kind in ("if", "while") and _span(previous) > LARGE_BRANCH
        if not parts or hard or banner or large or after_large:
            name = banner[1] if banner else None
            if stmt.kind == "label" and stmt.label:
                name = name or stmt.label
            parts.append(_Part([stmt], banner[0] if banner else stmt.line_start, name, hard,
                               stmt.label if stmt.kind == "label" else None))  # fmt: skip
        else:
            parts[-1].statements.append(stmt)
        previous = stmt
    merged: list[_Part] = []
    for part in parts:
        size = part.statements[-1].line_end - part.start + 1
        if merged and not part.hard and size < TINY_BLOCK:
            merged[-1].statements += part.statements
            merged[-1].name = merged[-1].name or part.name
        else:
            merged.append(part)
    # A tiny opening (the declarations) has no previous block: it joins the next one when that one is soft.
    opening = merged[0]
    if (
        len(merged) > 1 and not opening.hard and not merged[1].hard
        and opening.statements[-1].line_end - opening.start + 1 < TINY_BLOCK
    ):  # fmt: skip
        merged.pop(0)
        merged[0] = _Part(opening.statements + merged[0].statements, opening.start, merged[0].name or opening.name,
                          False)  # fmt: skip
    return merged


def _error_vars(procedure: Procedure) -> set[str]:
    """Variables that hold an error code: copied from @@error / @@rowcount, or named like one
    (`@w_error`, `@w_return`, `@rc`)."""
    found: set[str] = set()
    for stmt in procedure.statements():
        if stmt.kind in ("select", "set") and stmt.checks_error:
            found |= stmt.vars_written
        found |= {v for v in stmt.vars_read | stmt.vars_written if _ERROR_NAME.match(v)}
    return found


def _gotos(stmt: Statement) -> list[tuple[Statement, list[Statement], list[Statement]]]:
    """Every GOTO inside a top-level statement, with the IF / WHILE chain that controls it and the statements that
    run before it in its own block."""
    found: list[tuple[Statement, list[Statement], list[Statement]]] = []

    def visit(items: list[Statement], conditions: list[Statement]) -> None:
        for position, item in enumerate(items):
            if item.kind == "goto":
                found.append((item, conditions, items[:position]))
            inner = [*conditions, item] if item.kind in ("if", "while") else conditions
            for branch in (item.children, item.orelse):
                visit(branch, inner)

    visit([stmt], [])
    return found


def _on_error(conditions: list[Statement], before: list[Statement], error_vars: set[str]) -> bool:
    if any(s.kind == "rollback" for s in before):
        return True
    if not conditions:
        return False
    test = conditions[-1]
    return test.checks_error or bool(test.vars_read & error_vars)


def _unconditional_exit(stmt: Statement) -> bool:
    if stmt.kind in ("return", "goto"):
        return True
    if stmt.kind == "block" and stmt.children:
        return _unconditional_exit(stmt.children[-1])
    return False


def blocks(procedure: Procedure) -> tuple[list[Block], list[BlockEdge]]:
    statements = _top_level(procedure)
    if not statements:
        return [], []
    parts = _parts(procedure, statements)
    result: list[Block] = []
    state: Phase = "pre"
    for number, part in enumerate(parts, start=1):
        kinds = [s.kind for s in part.statements]
        phase: Phase = "transaction" if state == "transaction" or "begin_tran" in kinds else state
        for kind in kinds:
            if kind == "begin_tran":
                state = "transaction"
            elif kind in _HARD_ENDS and state == "transaction":
                state = "post"
        first, last = part.statements[0], part.statements[-1]
        name = part.name or f"Statements {first.line_start}-{last.line_end}"
        block = Block(f"{procedure.name}#B{number}", name, part.start, last.line_end, phase, part.statements,
                      label=part.label)  # fmt: skip
        for stmt in (s for top in part.statements for s in top.walk()):
            block.reads |= {t for t in stmt.reads if not t.startswith("#")}
            block.writes |= {t for t in stmt.writes if not t.startswith("#")}
            block.calls += [c for c in stmt.calls if not c.startswith("@") and c not in block.calls]
        result.append(block)
    by_label = {b.label.lower(): b for b in result if b.label}
    error_vars = _error_vars(procedure)
    edges: list[BlockEdge] = []
    error_targets: set[str] = set()
    for block in result:
        for top in block.statements:
            for goto, conditions, before in _gotos(top):
                target = by_label.get((goto.label or "").lower())
                if target is None:
                    continue
                jump: BlockEdgeKind = "ON_ERROR" if _on_error(conditions, before, error_vars) else "GOTO"
                if jump == "ON_ERROR":
                    error_targets.add(target.id)
                edges.append(BlockEdge(block.id, jump, target.id, goto.line_start))
    for block in result:
        top_kinds = [s.kind for s in block.statements]
        rolls_back = "rollback" in top_kinds and block.statements[-1].kind == "return"
        if block.id in error_targets or rolls_back:
            block.phase = "error"
    for current, following in pairwise(result):
        if not _unconditional_exit(current.statements[-1]):
            edges.append(BlockEdge(current.id, "NEXT", following.id))
    unique: list[BlockEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in sorted(edges, key=lambda e: (_index(e.source), e.kind != "NEXT", e.line or 0)):
        if (edge.source, edge.kind, edge.target) not in seen:
            seen.add((edge.source, edge.kind, edge.target))
            unique.append(edge)
    return result, unique


def _index(block_id: str) -> int:
    return int(block_id.rsplit("#B", 1)[-1])
