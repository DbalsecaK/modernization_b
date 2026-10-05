"""The platform's composition data (flows, sources, targets, compatibility rules, pipeline templates) from the YAML
files next to this module, and `build_catalog` to join it with the agent cards and the skills."""

from collections.abc import Iterable, Mapping
from functools import cache
from importlib.resources import files
from typing import Any

import yaml

from nexti_core.composition.model import (
    AXES,
    FLOWS,
    Agent,
    Catalog,
    CompatibilityRule,
    Condition,
    Flow,
    Phase,
    PipelineTemplate,
    Skill,
    SourceAdapter,
    SourceOption,
    TargetOption,
    Version,
)

DATA_FILES = ("flows", "sources", "targets", "compatibility", "templates")


@cache
def core_data() -> Mapping[str, Any]:
    """The five data files, parsed once. `yaml.safe_load` only: these files never build Python objects."""
    base = files("nexti_core.composition") / "data"
    return {name: yaml.safe_load((base / f"{name}.yaml").read_text(encoding="utf-8")) for name in DATA_FILES}


def adapters(data: Mapping[str, Any]) -> tuple[SourceAdapter, ...]:
    return tuple(
        SourceAdapter(str(a["key"]), str(a["name"]), str(a["level"]), str(a["version"]), str(a["validation"]))
        for a in data["sources"]["adapters"]
    )


def option_flows(value: Any) -> tuple[str, ...]:
    """The `flow` of a source option: one flow or a list of them (a legacy technology serves Flow 1 and Flow 4)."""
    found = (str(value),) if isinstance(value, str) else tuple(str(v) for v in value or ())
    unknown = set(found) - set(FLOWS)
    if not found or unknown:
        raise ValueError(f"a source option needs known flows, got {value!r}")
    return found


def versions(option: Mapping[str, Any]) -> tuple[Version, ...]:
    """The versions an option lists (ADR-0037), in catalog order."""
    return tuple(
        Version(str(v["key"]), str(v["name"]), v.get("level"), bool(v.get("default", False)))
        for v in option.get("versions") or []
    )


def sources(data: Mapping[str, Any]) -> tuple[SourceOption, ...]:
    return tuple(
        SourceOption(
            key=str(o["key"]),
            name=str(o["name"]),
            flows=option_flows(o["flow"]),
            adapter=o.get("adapter"),
            required_skills=tuple(o.get("required_skills") or ()),
            versions=versions(o),
        )
        for o in data["sources"]["options"]
    )


def targets(data: Mapping[str, Any]) -> tuple[TargetOption, ...]:
    out = []
    for axis in AXES:
        for o in data["targets"]["axes"][axis]:
            out.append(TargetOption(axis, str(o["key"]), str(o["name"]), o.get("level"), o.get("wave"),
                                    versions(o)))  # fmt: skip
    return tuple(out)


def rules(data: Mapping[str, Any]) -> tuple[CompatibilityRule, ...]:
    return tuple(
        CompatibilityRule(str(r["key"]), Condition.from_mapping(r["when"]), str(r["message"]))
        for r in data["compatibility"]["rules"]
    )


def flows(data: Mapping[str, Any]) -> tuple[Flow, ...]:
    return tuple(
        Flow(
            str(f["key"]),
            tuple(Phase(str(p["key"]), p.get("gate"), bool(p.get("agent_required", False))) for p in f["phases"]),
        )
        for f in data["flows"]["flows"]
    )


def templates(data: Mapping[str, Any]) -> tuple[PipelineTemplate, ...]:
    return tuple(
        PipelineTemplate(
            str(t["key"]),
            str(t["name"]),
            str(t["description"]),
            tuple(t["required_gates"]),
            str(t["default_autonomy"]),
        )
        for t in data["templates"]["templates"]
    )


def build_catalog(
    agent_docs: Iterable[Mapping[str, Any]],
    skill_docs: Iterable[Mapping[str, Any]],
    data: Mapping[str, Any] | None = None,
) -> Catalog:
    data = data or core_data()
    return Catalog(
        agents=tuple(sorted((Agent.from_mapping(d) for d in agent_docs), key=lambda a: a.order)),
        skills=tuple(sorted((Skill.from_mapping(d) for d in skill_docs), key=lambda s: s.key)),
        adapters=adapters(data),
        sources=sources(data),
        targets=targets(data),
        rules=rules(data),
        flows=flows(data),
        templates=templates(data),
        cost_unit_usd=int(data["flows"]["cost_unit_usd"]),
    )
