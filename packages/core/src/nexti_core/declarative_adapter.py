"""A source adapter driven by a declarative specification (ADR-0039): a tenant describes a legacy technology with
patterns (what starts a unit, what calls another program, what reads or writes a table, which words are
infrastructure or control flow) and the platform inventories, classifies and slices its code with them. No code of
the tenant's or of a model runs: the specification is data, validated here, and every pattern is a regular
expression evaluated line by line.

Such an adapter is `experimental`: it has no engine to run the legacy, so the verdict of a project on it cannot pass
PARTLY PROVEN until it earns a golden master or recorded traces (spec 8.6)."""

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nexti_core.adapters import Edge, Inventory, Node, SliceView, SourceFile

KEY = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
WORD = r"(?<![A-Za-z0-9_]){}(?![A-Za-z0-9_])"
MAX_PROBLEMS = 50


def _compiled(pattern: str, groups: Sequence[str]) -> re.Pattern[str]:
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"{pattern!r} is not a valid regular expression: {exc}") from exc
    missing = [g for g in groups if g not in compiled.groupindex]
    if missing:
        raise ValueError(f"{pattern!r} needs the named group(s) {', '.join(f'(?P<{g}>...)' for g in missing)}")
    return compiled


class AdapterSpec(BaseModel):
    """What a tenant declares about a legacy technology. Patterns are regular expressions matched on one line."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=KEY.pattern, description="Unique in the tenant, e.g. rpg-iv")
    name: str = Field(min_length=1, max_length=120)
    extensions: list[str] = Field(min_length=1, max_length=20, description="File suffixes, e.g. .rpg")
    comment_prefixes: list[str] = Field(default_factory=list, max_length=10)
    unit: str = Field(description="A line that starts a unit (program, procedure), with (?P<name>...)")
    parameter: str | None = Field(default=None, description="A parameter line, with (?P<name>...) and (?P<type>...)")
    call: str | None = Field(default=None, description="A call to another program, with (?P<callee>...)")
    reads: list[str] = Field(default_factory=list, description="Statements that read a table, with (?P<table>...)")
    writes: list[str] = Field(default_factory=list, description="Statements that write a table, with (?P<table>...)")
    infrastructure_keywords: list[str] = Field(default_factory=list, max_length=100)
    control_keywords: list[str] = Field(default_factory=list, max_length=100)
    type_map: dict[str, str] = Field(default_factory=dict, description="Source type -> neutral type (4.3)")

    @field_validator("extensions")
    @classmethod
    def dotted(cls, value: list[str]) -> list[str]:
        return [v if v.startswith(".") else f".{v}" for v in (x.strip().lower() for x in value) if v]

    @field_validator("unit")
    @classmethod
    def unit_has_name(cls, value: str) -> str:
        _compiled(value, ["name"])
        return value

    @field_validator("parameter")
    @classmethod
    def parameter_has_name(cls, value: str | None) -> str | None:
        if value:
            _compiled(value, ["name"])
        return value

    @field_validator("call")
    @classmethod
    def call_has_callee(cls, value: str | None) -> str | None:
        if value:
            _compiled(value, ["callee"])
        return value

    @field_validator("reads", "writes")
    @classmethod
    def tables_have_group(cls, value: list[str]) -> list[str]:
        for pattern in value:
            _compiled(pattern, ["table"])
        return value


class _Unit:
    def __init__(self, name: str, file: str, start: int) -> None:
        self.name = name
        self.file = file
        self.start = start
        self.end = start
        self.parameters: list[tuple[str, str, int]] = []
        self.reads: list[tuple[str, int]] = []
        self.writes: list[tuple[str, int]] = []
        self.calls: list[tuple[str, int]] = []
        self.statements = 0


class DeclarativeAdapter:
    """The SourceAdapter contract (spec 8.2) implemented from an AdapterSpec."""

    def __init__(self, spec: AdapterSpec) -> None:
        self.spec = spec
        self.name = spec.key
        self._unit = _compiled(spec.unit, ["name"])
        self._parameter = _compiled(spec.parameter, ["name"]) if spec.parameter else None
        self._call = _compiled(spec.call, ["callee"]) if spec.call else None
        self._reads = [_compiled(p, ["table"]) for p in spec.reads]
        self._writes = [_compiled(p, ["table"]) for p in spec.writes]
        self._infra = [re.compile(WORD.format(re.escape(k)), re.IGNORECASE) for k in spec.infrastructure_keywords]
        self._control = [re.compile(WORD.format(re.escape(k)), re.IGNORECASE) for k in spec.control_keywords]

    # -- reading ---------------------------------------------------------------------------------------------------
    def _mine(self, file: SourceFile) -> bool:
        return PurePosixPath(file.path).suffix.lower() in self.spec.extensions

    def _is_comment(self, line: str) -> bool:
        text = line.strip()
        return any(text.startswith(p) for p in self.spec.comment_prefixes)

    def _units(self, file: SourceFile) -> list[_Unit]:
        units: list[_Unit] = []
        lines = file.text.splitlines()
        for number, line in enumerate(lines, start=1):
            if self._is_comment(line):
                continue
            match = self._unit.search(line)
            if match:
                if units:
                    units[-1].end = number - 1
                units.append(_Unit(match.group("name"), file.path, number))
                continue
            if not units:
                units.append(_Unit(PurePosixPath(file.path).stem, file.path, 1))
            unit = units[-1]
            if not line.strip():
                continue
            unit.statements += 1
            if self._parameter and (m := self._parameter.search(line)):
                unit.parameters.append((m.group("name"), (m.groupdict().get("type") or "").strip(), number))
            for pattern in self._reads:
                for m in pattern.finditer(line):
                    unit.reads.append((m.group("table"), number))
            for pattern in self._writes:
                for m in pattern.finditer(line):
                    unit.writes.append((m.group("table"), number))
            if self._call and (m := self._call.search(line)):
                unit.calls.append((m.group("callee"), number))
        if units:
            units[-1].end = len(lines)
        return units

    def _all_units(self, files: list[SourceFile]) -> list[_Unit]:
        return [u for f in files if self._mine(f) for u in self._units(f)]

    def _label(self, line: str) -> tuple[str, str]:
        if any(p.search(line) for p in self._infra):
            return "infrastructure", "matches an infrastructure keyword of the adapter"
        if any(p.search(line) for p in self._control):
            return "control_flow", "matches a control-flow keyword of the adapter"
        return "business", "a statement that is neither infrastructure nor control flow"

    # -- the contract ------------------------------------------------------------------------------------------------
    def detect(self, files: list[SourceFile]) -> float:
        if not files:
            return 0.0
        mine = [f for f in files if self._mine(f)]
        if not mine:
            return 0.0
        share = len(mine) / len(files)
        recognised = any(self._unit.search(line) for f in mine for line in f.text.splitlines())
        return min(1.0, share * (1.0 if recognised else 0.6))

    def inventory(self, files: list[SourceFile]) -> Inventory:
        inv = Inventory(self.name)
        units = self._all_units(files)
        names = {u.name.lower() for u in units}
        tables: set[str] = set()
        externals: set[str] = set()
        for unit in units:
            key = f"program:{unit.name}"
            inv.nodes.append(Node(key, "Program", unit.name, unit.file, unit.start, unit.end,
                                  {"statements": unit.statements}))  # fmt: skip
            for name, source_type, line in unit.parameters:
                field_key = f"{key}#param:{name}"
                inv.nodes.append(Node(field_key, "Field", name, unit.file, line, line, {
                    "source_type": source_type, "neutral_type": self.spec.type_map.get(source_type, "")}))  # fmt: skip
                inv.edges.append(Edge(key, "DECLARES", field_key))
                if source_type and source_type not in self.spec.type_map and len(inv.problems) < MAX_PROBLEMS:
                    inv.problems.append(f"{unit.file}:{line}: type {source_type} has no neutral mapping")
            for table, line in unit.reads:
                tables.add(table)
                inv.edges.append(Edge(key, "READS", f"table:{table}", {"line": line}))
            for table, line in unit.writes:
                tables.add(table)
                inv.edges.append(Edge(key, "WRITES", f"table:{table}", {"line": line}))
            for callee, line in unit.calls:
                inv.edges.append(Edge(key, "CALLS", f"program:{callee}", {"line": line}))
                if callee.lower() not in names:
                    externals.add(callee)
        for table in sorted(tables):
            inv.nodes.append(Node(f"table:{table}", "Table", table, properties={"schema_known": False}))
        for callee in sorted(externals):
            inv.nodes.append(Node(f"program:{callee}", "Program", callee, properties={"external": True}))
        inv.metrics = {
            "programs": len(units), "statements": sum(u.statements for u in units), "tables": len(tables),
            "files": sum(1 for f in files if self._mine(f)),
        }  # fmt: skip
        return inv

    def types(self, files: list[SourceFile]) -> dict[str, str]:
        return dict(self.spec.type_map)

    def slices(self, files: list[SourceFile]) -> list[SliceView]:
        """One slice per unit with its whole range: a declared adapter has no dependency analysis (experimental)."""
        return [
            SliceView(f"{u.name}#1", u.file, ((u.start, u.end),), tuple(n for n, _, _ in u.parameters),
                      tuple(sorted({t for t, _ in [*u.reads, *u.writes]})))
            for u in self._all_units(files)
        ]  # fmt: skip

    def classified(self, files: list[SourceFile]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for file in files:
            if not self._mine(file):
                continue
            lines = file.text.splitlines()
            for unit in self._units(file):
                for number in range(unit.start, unit.end + 1):
                    line = lines[number - 1]
                    if not line.strip() or self._is_comment(line) or self._unit.search(line):
                        continue
                    label, reason = self._label(line)
                    out.append({"unit": unit.name, "file": file.path, "line_start": number, "line_end": number,
                                "label": label, "reason": reason})  # fmt: skip
        return out

    def classification(self, files: list[SourceFile]) -> dict[str, int]:
        counts = {"business": 0, "control_flow": 0, "infrastructure": 0}
        for item in self.classified(files):
            counts[item["label"]] += 1
        return counts

    def data_of(
        self, files: list[SourceFile], file: str, ranges: list[tuple[int, int]]
    ) -> tuple[frozenset[str], frozenset[str]]:
        reads: set[str] = set()
        writes: set[str] = set()
        wanted = PurePosixPath(file).name.lower()
        for source in files:
            if PurePosixPath(source.path).name.lower() != wanted:
                continue
            for unit in self._units(source):
                for table, line in unit.reads:
                    if any(a <= line <= b for a, b in ranges):
                        reads.add(table)
                for table, line in unit.writes:
                    if any(a <= line <= b for a, b in ranges):
                        writes.add(table)
        return frozenset(reads), frozenset(writes)

    def digest(self, files: list[SourceFile]) -> str:
        inventory = self.inventory(files)
        lines = [f"Metrics: {json.dumps(inventory.metrics)}", f"Adapter: {self.spec.name} (declared, experimental)"]
        for node in inventory.nodes:
            if node.label == "Program" and not node.properties.get("external"):
                lines.append(f"Program {node.name} ({node.file}:{node.line_start}-{node.line_end})")
            elif node.label == "Field":
                lines.append(f"  parameter {node.name}: {node.properties.get('neutral_type') or '?'}")
            elif node.label == "Table":
                lines.append(f"Table {node.name}")
        for edge in inventory.edges:
            if edge.type in ("READS", "WRITES", "CALLS"):
                lines.append(f"{edge.source} {edge.type} {edge.target}")
        lines.append("Observed by: nothing yet (no engine, no traces): the verdict stays at most PARTLY PROVEN")
        return "\n".join(lines)


def first_json(content: str) -> Any:
    """The first JSON value in a model's reply (it may wrap it in ``` fences or add a sentence); ValueError when
    there is none. Here and not in the orchestration so the API, which never runs agents, can read a draft."""
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise ValueError("the answer has no JSON object")
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise ValueError(f"the JSON is not valid: {exc.msg} at character {exc.pos}") from exc
    return value


def summary(adapter: DeclarativeAdapter, files: list[SourceFile]) -> dict[str, Any]:
    """What the studio shows after trying a specification on sample files."""
    inventory = adapter.inventory(files)
    programs = [n for n in inventory.nodes if n.label == "Program" and not n.properties.get("external")]
    return {
        "detect": round(adapter.detect(files), 2),
        "metrics": inventory.metrics,
        "programs": [
            {"name": n.name, "file": n.file, "line_start": n.line_start, "line_end": n.line_end} for n in programs
        ][:50],
        "tables": sorted(n.name for n in inventory.nodes if n.label == "Table")[:100],
        "calls": sorted({e.target.split(":", 1)[1] for e in inventory.edges if e.type == "CALLS"})[:100],
        "classification": adapter.classification(files),
        "problems": inventory.problems[:20],
    }


def spec_from_mapping(data: Mapping[str, Any]) -> AdapterSpec:
    return AdapterSpec.model_validate(dict(data))
