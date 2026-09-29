"""The Sybase ASE stored procedure adapter (spec 8.2, 8.3): deterministic inventory, neutral types, classification
hints and slices. Parsing never uses a model and never executes the code."""

import re

from nexti_adapter_sybase.analysis import backward_slice, classify, slice_targets
from nexti_adapter_sybase.lexer import LexError
from nexti_adapter_sybase.parser import ParseError, Procedure, parse
from nexti_adapter_sybase.types import to_neutral
from nexti_core.adapters import Edge, Inventory, Node, SliceView, SourceFile

EXTENSIONS = (".sp", ".sql", ".prc", ".proc", ".tsql", ".syb")
_CREATE_PROC = re.compile(r"\bcreate\s+proc(edure)?\b", re.IGNORECASE)
_SYBASE_MARKERS = re.compile(
    r"@@error|@@rowcount|\w+\.\.\w+|\bmoney\b|^\s*go\s*$|\bsp_\w+", re.IGNORECASE | re.MULTILINE
)


def _procedures(files: list[SourceFile]) -> list[tuple[SourceFile, Procedure]]:
    found: list[tuple[SourceFile, Procedure]] = []
    for file in files:
        if file.path.lower().endswith(EXTENSIONS) or _CREATE_PROC.search(file.text):
            found += [(file, p) for p in parse(file.text)]
    return found


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
        for file in files:
            if not (file.path.lower().endswith(EXTENSIONS) or _CREATE_PROC.search(file.text)):
                continue
            try:
                procedures = parse(file.text)
            except (ParseError, LexError) as exc:
                inv.problems.append(f"{file.path}:{exc.line}: {exc}")
                continue
            for proc in procedures:
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
        for table in sorted(tables):
            inv.nodes.append(Node(f"table:{table}", "Table", table))
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

    def slices(self, files: list[SourceFile]) -> list[SliceView]:
        views: list[SliceView] = []
        for file, proc in _procedures(files):
            for target in slice_targets(proc):
                cut = backward_slice(proc, target)
                views.append(SliceView(f"{proc.name}#{target}", file.path, tuple(cut.lines), tuple(cut.parameters),
                                       tuple(cut.tables)))  # fmt: skip
        return views


__all__ = ["SybaseAdapter", "backward_slice", "classify", "parse", "slice_targets", "to_neutral"]
