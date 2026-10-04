"""The Sybase ASE stored procedure adapter (spec 8.2, 8.3): deterministic inventory, neutral types, classification
hints and slices. Parsing never uses a model and never executes the code."""

import json
import re
from typing import Any

from nexti_adapter_sybase.analysis import backward_slice, classify, slice_targets
from nexti_adapter_sybase.blocks import blocks
from nexti_adapter_sybase.lexer import LexError, tokenize
from nexti_adapter_sybase.parser import ParseError, Procedure, Statement, name_at, parse
from nexti_adapter_sybase.types import to_neutral
from nexti_core.adapters import Edge, Inventory, Node, SliceView, SourceFile

EXTENSIONS = (".sp", ".sql", ".prc", ".proc", ".tsql", ".syb")
_CREATE_PROC = re.compile(r"\bcreate\s+proc(edure)?\b", re.IGNORECASE)
_CREATE_TABLE = re.compile(r"\bcreate\s+table\b", re.IGNORECASE)
_SYBASE_MARKERS = re.compile(
    r"@@error|@@rowcount|\w+\.\.\w+|\bmoney\b|^\s*go\s*$|\bsp_\w+", re.IGNORECASE | re.MULTILINE
)


def _ddl_tables(files: list[SourceFile]) -> set[str]:
    """The tables whose definition (CREATE TABLE) is in the inputs, full and short names, lower case."""
    found: set[str] = set()
    for file in files:
        if not _CREATE_TABLE.search(file.text):
            continue
        try:
            tokens, _ = tokenize(file.text)
        except LexError:
            continue
        for index, token in enumerate(tokens[:-1]):
            if token.is_word("CREATE") and tokens[index + 1].is_word("TABLE"):
                name, _ = name_at(tokens, index + 2)
                if name and not name.startswith("#"):
                    found |= {name.lower(), name.lower().split(".")[-1]}
    return found


def _block_layer(inv: Inventory, file: SourceFile, proc: Procedure) -> None:
    """The logical blocks of a procedure as child nodes of it, with what each reads, writes and calls and the edges
    between them (ADR-0032). The procedure node and its own edges are not touched."""
    key = f"proc:{proc.name}"
    found, links = blocks(proc)
    for number, block in enumerate(found, start=1):
        bkey = f"block:{block.id}"
        statements: list[Statement] = [s for top in block.statements for s in top.walk()]
        inv.nodes.append(Node(bkey, "Block", block.name, file.path, block.line_start, block.line_end, {
            "phase": block.phase, "unit": key, "order": number, "statements": len(statements),
        }))  # fmt: skip
        inv.edges.append(Edge(key, "CONTAINS", bkey, {"order": number}))
        for stmt in statements:
            for table in sorted(stmt.reads):
                if not table.startswith("#"):
                    inv.edges.append(Edge(bkey, "READS", f"table:{table}", {"line": stmt.line_start}))
            for table in sorted(stmt.writes):
                if not table.startswith("#"):
                    inv.edges.append(Edge(bkey, "WRITES", f"table:{table}", {"line": stmt.line_start}))
            for callee in stmt.calls:
                if not callee.startswith("@"):
                    inv.edges.append(Edge(bkey, "CALLS", f"proc:{callee}", {"line": stmt.line_start}))
    for link in links:
        inv.edges.append(Edge(f"block:{link.source}", link.kind, f"block:{link.target}",
                              {"line": link.line} if link.line else {}))  # fmt: skip


def _procedures(files: list[SourceFile]) -> list[tuple[SourceFile, Procedure]]:
    found: list[tuple[SourceFile, Procedure]] = []
    for file in files:
        if file.path.lower().endswith(EXTENSIONS) or _CREATE_PROC.search(file.text):
            found += [(file, p) for p in parse(file.text)]
    return found


FRAGMENTED = 40  # a slice in more pieces than this is shown with its small gaps filled
SMALL_GAP = 3


def readable(lines: list[tuple[int, int]] | tuple[tuple[int, int], ...]) -> tuple[tuple[int, int], ...]:
    """The ranges of a backward slice as the agent reads them. A slice in a hundred pieces (a late statement of a
    long procedure depends on much of it) hides the flow between them; gaps of a few lines are filled so it reads as
    blocks. Slices in few pieces are left exactly as they are."""
    ranges = sorted(lines)
    if len(ranges) <= FRAGMENTED:
        return tuple(ranges)
    merged = [ranges[0]]
    for start, end in ranges[1:]:
        last_start, last_end = merged[-1]
        if start - last_end - 1 <= SMALL_GAP:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return tuple(merged)


class SybaseAdapter:
    name = "sybase-ase"

    def detect(self, files: list[SourceFile]) -> float:
        candidates = [f for f in files if _CREATE_PROC.search(f.text)]
        if not candidates:
            return 0.0
        markers = sum(min(len(_SYBASE_MARKERS.findall(f.text)), 20) for f in candidates)
        return round(min(1.0, 0.5 + markers / (40 * len(candidates))), 2)

    def inventory(self, files: list[SourceFile]) -> Inventory:
        inv = Inventory(self.name)
        tables: set[str] = set()
        calls: set[str] = set()
        statements = 0
        decisions = 0
        parsed: list[tuple[SourceFile, Procedure]] = []
        for file in files:
            if not (file.path.lower().endswith(EXTENSIONS) or _CREATE_PROC.search(file.text)):
                continue
            try:
                procedures = parse(file.text)
            except (ParseError, LexError) as exc:
                inv.problems.append(f"{file.path}:{exc.line}: {exc}")
                continue
            for proc in procedures:
                parsed.append((file, proc))
                key = f"proc:{proc.name}"
                stmts = proc.statements()
                statements += len(stmts)
                decisions += sum(1 for s in stmts if s.kind in ("if", "while") or s.kind == "goto")
                inv.nodes.append(Node(key, "StoredProcedure", proc.name, file.path, proc.line_start, proc.line_end, {
                    "parameters": len(proc.parameters), "statements": len(stmts),
                    "complexity": 1 + sum(1 for s in stmts if s.kind in ("if", "while")),
                    "transactions": sum(1 for s in stmts if s.kind == "begin_tran"),
                }))  # fmt: skip
                for param in proc.parameters:
                    mapping = to_neutral(param.type)
                    field_key = f"field:{proc.name}.{param.name}"
                    inv.nodes.append(Node(field_key, "Field", param.name, file.path, param.line, param.line, {
                        "source_type": param.type, "neutral_type": str(mapping.neutral) if mapping.neutral else "",
                        "output": param.output, "default": param.default, "note": mapping.note,
                    }))  # fmt: skip
                    inv.edges.append(Edge(key, "DECLARES", field_key))
                    if not mapping.resolved:
                        inv.problems.append(f"{file.path}:{param.line}: {param.name} {param.type}: {mapping.note}")
                for stmt in stmts:
                    for table in stmt.reads | stmt.writes:
                        if not table.startswith("#"):
                            tables.add(table)
                    for table in sorted(stmt.reads):
                        if not table.startswith("#"):
                            inv.edges.append(Edge(key, "READS", f"table:{table}", {"line": stmt.line_start}))
                    for table in sorted(stmt.writes):
                        if not table.startswith("#"):
                            inv.edges.append(Edge(key, "WRITES", f"table:{table}", {"line": stmt.line_start}))
                    for callee in stmt.calls:
                        if callee.startswith("@"):
                            inv.problems.append(f"{file.path}:{stmt.line_start}: dynamic call through {callee}")
                            continue
                        calls.add(callee)
                        inv.edges.append(Edge(key, "CALLS", f"proc:{callee}", {"line": stmt.line_start}))
        known = {n.name for n in inv.nodes if n.label == "StoredProcedure"}
        defined = _ddl_tables(files)
        for table in sorted(tables):
            schema_known = table in defined or table.split(".")[-1] in defined
            inv.nodes.append(Node(f"table:{table}", "Table", table, properties={"schema_known": schema_known}))
        for callee in sorted(calls - known):
            inv.nodes.append(Node(f"proc:{callee}", "StoredProcedure", callee, properties={"external": True}))
        # Keep one READS/WRITES/CALLS edge per pair (the first line), so the graph stays small.
        seen: set[tuple[str, str, str]] = set()
        unique: list[Edge] = []
        for edge in inv.edges:
            pair = (edge.source, edge.type, edge.target)
            if pair not in seen:
                seen.add(pair)
                unique.append(edge)
        # The blocks go last, after the units and their edges, which stay exactly as they were.
        for file, proc in parsed:
            before = len(inv.edges)
            _block_layer(inv, file, proc)
            for edge in inv.edges[before:]:
                pair = (edge.source, edge.type, edge.target)
                if pair not in seen:
                    seen.add(pair)
                    unique.append(edge)
        inv.edges = unique
        inv.metrics = {
            "procedures": len(known), "statements": statements, "decisions": decisions, "tables": len(tables),
            "external_calls": len(calls - known),
            "lines": sum(f.text.count("\n") + 1 for f in files if f.path.lower().endswith(EXTENSIONS)),
        }  # fmt: skip
        return inv

    def types(self, files: list[SourceFile]) -> dict[str, str]:
        result: dict[str, str] = {}
        for _, proc in _procedures(files):
            declared = [p.type for p in proc.parameters] + [t for s in proc.statements() for t in s.declared.values()]
            for source in declared:
                mapping = to_neutral(source)
                result[source] = str(mapping.neutral) if mapping.neutral else ""
        return result

    def classification(self, files: list[SourceFile]) -> dict[str, int]:
        """How many statements are infrastructure, control flow or business logic (6.1 phase 4)."""
        counts: dict[str, int] = {}
        for _, proc in _procedures(files):
            for hint in classify(proc):
                counts[hint.label] = counts.get(hint.label, 0) + 1
        return counts

    def classified(self, files: list[SourceFile]) -> list[dict[str, Any]]:
        """Every statement with its class and why (the detail behind `classification`, for the Inventory tab)."""
        found: list[dict[str, Any]] = []
        for source, proc in _procedures(files):
            statements = {s.id: s for s in proc.statements()}
            for hint in classify(proc):
                stmt = statements[hint.statement]
                found.append({"unit": proc.name, "file": source.path, "line_start": stmt.line_start,
                              "line_end": stmt.line_end, "statement": stmt.kind, "label": hint.label,
                              "reason": hint.reason})  # fmt: skip
        return found

    def data_of(
        self, files: list[SourceFile], file: str, ranges: list[tuple[int, int]]
    ) -> tuple[frozenset[str], frozenset[str]]:
        """Tables read and written by the statements inside the given line ranges of `file` (work tables excluded):
        what a rule reads and writes, for the dependencies between user stories (7.7)."""
        reads: set[str] = set()
        writes: set[str] = set()
        for source, proc in _procedures(files):
            if source.path != file:
                continue
            for stmt in proc.statements():
                if any(stmt.line_start <= end and stmt.line_end >= start for start, end in ranges):
                    reads |= {t for t in stmt.reads if not t.startswith("#")}
                    writes |= {t for t in stmt.writes if not t.startswith("#")}
        return frozenset(reads), frozenset(writes)

    def slices(self, files: list[SourceFile]) -> list[SliceView]:
        views: list[SliceView] = []
        for file, proc in _procedures(files):
            for target in slice_targets(proc):
                cut = backward_slice(proc, target)
                views.append(SliceView(f"{proc.name}#{target}", file.path, readable(cut.lines),
                                       tuple(cut.parameters), tuple(cut.tables)))  # fmt: skip
        return views

    def digest(self, files: list[SourceFile]) -> str:
        inventory = self.inventory(files)
        lines = [f"Metrics: {json.dumps(inventory.metrics)}"]
        for node in inventory.nodes:
            if node.label == "StoredProcedure" and not node.properties.get("external"):
                lines.append(f"Procedure {node.name} ({node.file}:{node.line_start}-{node.line_end})")
            elif node.label == "Field":
                lines.append(f"  parameter {node.name}: {node.properties.get('neutral_type')}"
                             f"{' OUTPUT' if node.properties.get('output') else ''}")  # fmt: skip
            elif node.label == "Table":
                lines.append(f"Table {node.name}")
        # Blocks stay out of the digest: the prompts it feeds do not change (recordings replay by request hash).
        for edge in inventory.edges:
            if edge.type in ("READS", "WRITES", "CALLS") and not edge.source.startswith("block:"):
                lines.append(f"{edge.source} {edge.type} {edge.target}")
        return "\n".join(lines)


__all__ = ["SybaseAdapter", "backward_slice", "classify", "parse", "slice_targets", "to_neutral"]
