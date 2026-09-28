"""Typed catalog of the composition engine (spec 8 and 9): agents, skills, sources, target options, compatibility
rules, flows and pipeline templates. Built from plain mappings (the YAML files or the catalog tables)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

AXES: tuple[str, ...] = ("architecture", "backend", "frontend", "database", "cloud")
FLOWS: tuple[str, ...] = ("modernization", "newFeature")
NO_FRONTEND = "none"
_CONDITION_KEYS = {"flow", "sources_any", "sources_none", "target", "target_not"}


def _strs(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list | tuple):
        raise ValueError(f"expected a list, got {value!r}")
    return tuple(str(v) for v in value)


def _axes(value: Any) -> Mapping[str, frozenset[str]]:
    if not value:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"expected axis -> options, got {value!r}")
    unknown = set(value) - set(AXES)
    if unknown:
        raise ValueError(f"unknown target axes: {sorted(unknown)}")
    return {axis: frozenset(_strs(options)) for axis, options in value.items()}


@dataclass(frozen=True)
class Target:
    architecture: str
    backend: str
    frontend: str
    database: str
    cloud: str

    def get(self, axis: str) -> str:
        value: str = getattr(self, axis)
        return value

    def technologies(self) -> set[str]:
        return {self.get(axis) for axis in AXES} - {NO_FRONTEND}

    @property
    def has_frontend(self) -> bool:
        return self.frontend != NO_FRONTEND


@dataclass(frozen=True)
class Request:
    """What the user chose so far: the flow, the sources (or documentary inputs) and the target stack."""

    flow: str
    sources: tuple[str, ...]
    target: Target

    def technologies(self) -> set[str]:
        return set(self.sources) | self.target.technologies()


@dataclass(frozen=True)
class Condition:
    """All given parts must hold. An empty condition always holds."""

    flow: str | None = None
    sources_any: frozenset[str] = frozenset()
    sources_none: frozenset[str] = frozenset()
    target: Mapping[str, frozenset[str]] = field(default_factory=dict)
    target_not: Mapping[str, frozenset[str]] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "Condition":
        data = data or {}
        unknown = set(data) - _CONDITION_KEYS
        if unknown:
            raise ValueError(f"unknown condition keys: {sorted(unknown)}")
        flow = data.get("flow")
        if flow is not None and flow not in FLOWS:
            raise ValueError(f"unknown flow in condition: {flow}")
        return cls(
            flow=flow,
            sources_any=frozenset(_strs(data.get("sources_any"))),
            sources_none=frozenset(_strs(data.get("sources_none"))),
            target=_axes(data.get("target")),
            target_not=_axes(data.get("target_not")),
        )

    def matches(self, request: Request) -> bool:
        sources = set(request.sources)
        if self.flow is not None and request.flow != self.flow:
            return False
        if self.sources_any and not sources & self.sources_any:
            return False
        if sources & self.sources_none:
            return False
        if any(request.target.get(axis) not in allowed for axis, allowed in self.target.items()):
            return False
        return not any(request.target.get(axis) in denied for axis, denied in self.target_not.items())

    def referenced_options(self) -> set[tuple[str, str]]:
        """(kind, key) pairs used by the condition, to check the catalog references only existing options."""
        refs = {("source", s) for s in self.sources_any | self.sources_none}
        for axes in (self.target, self.target_not):
            refs |= {(axis, key) for axis, keys in axes.items() for key in keys}
        return refs


@dataclass(frozen=True)
class RecommendRule:
    when: Condition
    reason: str


@dataclass(frozen=True)
class Agent:
    key: str
    version: str
    order: int
    name: str
    name_es: str
    group: str
    description: str
    description_es: str
    phases: tuple[str, ...]
    capabilities: tuple[str, ...]
    tools: tuple[str, ...]
    mandatory: bool
    level: str
    default_profile: str
    relative_cost: int
    recommend: tuple[RecommendRule, ...]

    @classmethod
    def from_mapping(cls, d: Mapping[str, Any]) -> "Agent":
        return cls(
            key=str(d["id"]),
            version=str(d["version"]),
            order=int(d.get("order", 0)),
            name=str(d["name"]),
            name_es=str(d.get("name_es") or d["name"]),
            group=str(d["group"]),
            description=str(d["description"]),
            description_es=str(d.get("description_es") or d["description"]),
            phases=_strs(d.get("phases")),
            capabilities=_strs(d.get("capabilities")),
            tools=_strs(d.get("tools")),
            mandatory=bool(d.get("mandatory", False)),
            level=str(d["level"]),
            default_profile=str(d.get("default_profile", "")),
            relative_cost=int(d.get("relative_cost", 1)),
            recommend=tuple(
                RecommendRule(Condition.from_mapping(r.get("when")), str(r["reason"])) for r in d.get("recommend") or []
            ),
        )


@dataclass(frozen=True)
class Skill:
    key: str
    version: str
    title: str
    description: str
    type: str
    agents: tuple[str, ...]
    technologies: tuple[str, ...]  # empty: cross-cutting, applies to any technology
    conflicts: tuple[str, ...]
    requires: tuple[str, ...]
    status: str
    eval_score: float | None
    content: str

    @classmethod
    def from_mapping(cls, d: Mapping[str, Any]) -> "Skill":
        applies = d.get("applies_to") or {}
        score = d.get("eval_score")
        return cls(
            key=str(d["name"]),
            version=str(d["version"]),
            title=str(d.get("title") or d["name"]),
            description=str(d["description"]),
            type=str(d["type"]),
            agents=_strs(applies.get("agents")),
            technologies=_strs(applies.get("technologies")),
            conflicts=_strs(d.get("conflicts")),
            requires=_strs(d.get("requires")),
            status=str(d.get("status", "draft")),
            eval_score=float(score) if score is not None else None,
            content=str(d.get("content", "")),
        )


@dataclass(frozen=True)
class SourceAdapter:
    key: str
    name: str
    level: str
    version: str
    validation: str


@dataclass(frozen=True)
class SourceOption:
    key: str
    name: str
    flow: str
    adapter: str | None
    required_skills: tuple[str, ...]


@dataclass(frozen=True)
class TargetOption:
    axis: str
    key: str
    name: str
    level: str | None
    wave: int | None


@dataclass(frozen=True)
class CompatibilityRule:
    key: str
    when: Condition
    message: str


@dataclass(frozen=True)
class Phase:
    key: str
    gate: str | None
    agent_required: bool


@dataclass(frozen=True)
class Flow:
    key: str
    phases: tuple[Phase, ...]


@dataclass(frozen=True)
class PipelineTemplate:
    key: str
    name: str
    description: str
    required_gates: tuple[str, ...]
    default_autonomy: str


@dataclass(frozen=True)
class Catalog:
    agents: tuple[Agent, ...]
    skills: tuple[Skill, ...]
    adapters: tuple[SourceAdapter, ...]
    sources: tuple[SourceOption, ...]
    targets: tuple[TargetOption, ...]
    rules: tuple[CompatibilityRule, ...]
    flows: tuple[Flow, ...]
    templates: tuple[PipelineTemplate, ...]
    cost_unit_usd: int

    def agent(self, key: str) -> Agent | None:
        return next((a for a in self.agents if a.key == key), None)

    def skill(self, key: str) -> Skill | None:
        return next((s for s in self.skills if s.key == key), None)

    def flow(self, key: str) -> Flow | None:
        return next((f for f in self.flows if f.key == key), None)

    def source(self, key: str) -> SourceOption | None:
        return next((s for s in self.sources if s.key == key), None)

    def target_option(self, axis: str, key: str) -> TargetOption | None:
        return next((t for t in self.targets if t.axis == axis and t.key == key), None)

    def template(self, key: str) -> PipelineTemplate | None:
        return next((t for t in self.templates if t.key == key), None)

    @property
    def mandatory_agents(self) -> tuple[str, ...]:
        return tuple(a.key for a in self.agents if a.mandatory)
