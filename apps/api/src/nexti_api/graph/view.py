"""The knowledge graph as the Inventario tab shows it (spec 5.2, 5.2.1): the code units (transactions, programs,
maps, copybooks, files) with their domain, migration state, size, rules and origin; the relations between them;
orphans; and the business flows walked from each entry point in the order of the code. Everything here is computed
by code from the graph, the rules and the generated artifacts: no model takes part."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from nexti_graph import GraphNode

# The label of a graph node -> the type the tab draws. Paragraphs, fields and statements stay out of the picture:
# they are reached through the detail of their program.
VIEW_TYPES = {"Transaction": "transaction", "Program": "program", "StoredProcedure": "program", "BmsMap": "map",
              "Copybook": "copybook", "File": "file", "Table": "file"}  # fmt: skip
VIEW_EDGES = ("STARTS", "CALLS", "READS", "WRITES", "COPIES", "USES_MAP")
DATA_DOMAIN = "data"


@dataclass(frozen=True)
class RuleRef:
    id: str
    name: str
    priority: str
    sources: tuple[tuple[str, int, int], ...]


@dataclass
class ViewNode:
    id: str
    name: str
    type: str
    domain: str = ""
    state: str = "pending"
    loc: int | None = None
    rules: list[str] = field(default_factory=list)
    source: str | None = None
    file: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    external: bool = False
    orphan: bool = False


def _view_type(labels: Sequence[str]) -> str | None:
    return next((VIEW_TYPES[label] for label in labels if label in VIEW_TYPES), None)


def _same_file(a: str | None, b: str) -> bool:
    return bool(a) and PurePosixPath(str(a)).name.lower() == PurePosixPath(b).name.lower()


def rules_at(rules: Iterable[RuleRef], file: str | None, start: int | None, end: int | None) -> list[str]:
    """The rules whose citations overlap the lines of a unit."""
    if not file or start is None or end is None:
        return []
    return sorted({r.id for r in rules for f, a, b in r.sources if _same_file(file, f) and a <= end and b >= start})


def build(
    nodes: Sequence[GraphNode], relationships: Sequence[Mapping[str, Any]], orphans: Iterable[str],
    rules: Sequence[RuleRef], generated_rules: set[str], verified: bool,
) -> dict[str, Any]:  # fmt: skip
    orphan_keys = set(orphans)
    domain_names = {n.key: n.name for n in nodes if "Domain" in n.labels}
    domain_of: dict[str, str] = {}
    for r in relationships:
        if r["type"] == "BELONGS_TO" and r["target"] in domain_names:
            domain_of[r["source"]] = domain_names[r["target"]]
    view: dict[str, ViewNode] = {}
    for n in nodes:
        kind = _view_type(n.labels)
        if kind is None:
            continue
        p = n.properties
        start, end = p.get("line_start"), p.get("line_end")
        loc = p.get("lines") or (end - start + 1 if isinstance(start, int) and isinstance(end, int) else None)
        node_rules = rules_at(rules, p.get("file"), start, end) if kind == "program" else []
        state = "pending"
        if node_rules:
            state = "inProgress"
            if set(node_rules) & generated_rules:
                state = "verified" if verified and set(node_rules) <= generated_rules else "generated"
        view[n.key] = ViewNode(
            id=n.key, name=n.name or n.key.split(":", 1)[-1], type=kind, domain=domain_of.get(n.key, ""),
            state=state, loc=loc, rules=node_rules,
            source=f"{p['file']}:{start}-{end}" if p.get("file") and start else p.get("file"),
            file=p.get("file"), line_start=start, line_end=end, external=bool(p.get("external")),
            orphan=n.key in orphan_keys,
        )  # fmt: skip
    edges = [r for r in relationships if r["type"] in VIEW_EDGES and r["source"] in view and r["target"] in view]
    _inherit_domains(view, edges)
    return {
        "nodes": [vars(v) for v in sorted(view.values(), key=lambda v: (v.type, v.name))],
        "edges": [
            {"from": e["source"], "to": e["target"], "kind": e["type"], "detail": (e.get("props") or {}).get("kind")}
            for e in edges
        ],
        "rules": [{"id": r.id, "name": r.name, "priority": r.priority} for r in sorted(rules, key=lambda r: r.id)],
        "flows": flows(view, edges, rules),
    }


def _inherit_domains(view: dict[str, ViewNode], edges: Sequence[Mapping[str, Any]]) -> None:
    """Files and tables go to the data group; a map, copybook or transaction takes the domain of the program that
    uses it (or that it starts)."""
    for node in view.values():
        if node.type == "file":
            node.domain = DATA_DOMAIN
        elif node.type == "program" and not node.domain and not node.external:
            node.domain = node.name  # a program outside any proposed domain is its own group
    for _ in range(2):
        for e in edges:
            source, target = view[e["source"]], view[e["target"]]
            if e["type"] in ("USES_MAP", "COPIES") and source.domain and not target.domain:
                target.domain = source.domain
            elif e["type"] == "STARTS" and target.domain and not source.domain:
                source.domain = target.domain
            elif e["type"] == "CALLS" and source.domain and not target.domain and target.type == "program":
                target.domain = source.domain
    for node in view.values():
        node.domain = node.domain or node.name


def _line(edge: Mapping[str, Any]) -> int:
    line = (edge.get("props") or {}).get("line")
    return int(line) if isinstance(line, int) else 0


def flows(
    view: Mapping[str, ViewNode], edges: Sequence[Mapping[str, Any]], rules: Sequence[RuleRef]
) -> list[dict[str, Any]]:
    """One business flow per entry point (a transaction, or a program nobody calls): its steps follow the code in
    line order: screens shown, data read and written, programs linked (walked into) and transferred to. Each step
    carries the rule cited at its line."""
    out: dict[str, list[Mapping[str, Any]]] = {}
    for e in edges:
        out.setdefault(e["source"], []).append(e)
    for items in out.values():
        items.sort(key=_line)
    called = {e["target"] for e in edges if e["type"] in ("CALLS", "STARTS")}
    entries = [n for n in view.values() if n.type == "transaction"] or [
        n for n in view.values() if n.type == "program" and not n.external and n.id not in called
    ]
    found = []
    for entry in sorted(entries, key=lambda n: n.name):
        steps: list[dict[str, Any]] = []
        start = entry
        if entry.type == "transaction":
            target = next((e["target"] for e in out.get(entry.id, []) if e["type"] == "STARTS"), None)
            if target is None:
                continue
            steps.append({"kind": "start", "nodes": [entry.id, target], "rule": None})
            start = view[target]
        _walk(view, out, rules, start, steps, {start.id})
        cited = sorted({s["rule"] for s in steps if s["rule"]})
        found.append(
            {"id": f"flow:{entry.name}", "name": entry.name, "entry": entry.id, "rules": cited, "steps": steps}
        )
    return found


_STEP = {"USES_MAP": "screen", "READS": "read", "WRITES": "write"}


def _walk(
    view: Mapping[str, ViewNode], out: Mapping[str, list[Mapping[str, Any]]], rules: Sequence[RuleRef],
    program: ViewNode, steps: list[dict[str, Any]], seen: set[str],
) -> None:  # fmt: skip
    for e in out.get(program.id, []):
        line = _line(e)
        cited = rules_at(rules, program.file, line, line) if line else []
        rule = cited[0] if cited else None
        if e["type"] in _STEP:
            steps.append({"kind": _STEP[e["type"]], "nodes": [program.id, e["target"]], "rule": rule})
        elif e["type"] == "CALLS":
            detail = str((e.get("props") or {}).get("kind") or "CALL").lower()
            steps.append({"kind": "transfer" if detail == "xctl" else "call", "nodes": [program.id, e["target"]],
                          "rule": rule})  # fmt: skip
            callee = view[e["target"]]
            if detail != "xctl" and not callee.external and callee.id not in seen and len(steps) < 60:
                seen.add(callee.id)
                _walk(view, out, rules, callee, steps, seen)


def lift(keys: Iterable[str], view_ids: set[str]) -> list[str]:
    """Graph keys -> the units the tab draws (a paragraph or field lifts to its program or copybook)."""
    found = set()
    for key in keys:
        if key in view_ids:
            found.add(key)
            continue
        kind, _, rest = key.partition(":")
        owner = rest.split(".", 1)[0]
        for candidate in (f"program:{owner}", f"copybook:{owner}", f"proc:{owner}"):
            if kind in ("para", "field") and candidate in view_ids:
                found.add(candidate)
    return sorted(found)
