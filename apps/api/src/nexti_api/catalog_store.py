"""The global catalog in the database (spec 9, 19.4).

`sync_catalog` loads the repository files (packages/agents, packages/skills and nexti_core.composition) into the
catalog tables; `load_catalog` builds the composition engine's catalog from the current rows. Agents and skills are
versioned: a project pins the versions it uses (9.7), so a definition that changed must carry a new version.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

import nexti_agents
import nexti_skills
from nexti_core.composition import AXES, Catalog, build_catalog, core_data, option_flows
from nexti_core.db.models import (
    AgentDefinition,
    CompatibilityRuleDefinition,
    PipelineTemplateDefinition,
    SkillDefinition,
    SourceAdapterDefinition,
    SourceOptionDefinition,
    TargetOptionDefinition,
)


class CatalogVersionError(RuntimeError):
    """A definition changed but kept its version: the projects that pinned it would silently change."""


@dataclass
class SyncReport:
    added: list[str] = field(default_factory=list)
    unchanged: int = 0
    retired: list[str] = field(default_factory=list)


def _agent_row(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": str(doc["id"]),
        "version": str(doc["version"]),
        "position": int(doc["order"]),
        "name": doc["name"],
        "name_es": doc.get("name_es") or doc["name"],
        "agent_group": doc["group"],
        "description": doc["description"],
        "description_es": doc.get("description_es") or doc["description"],
        "phases": list(doc.get("phases") or []),
        "capabilities": list(doc.get("capabilities") or []),
        "tools": list(doc.get("tools") or []),
        "mandatory": bool(doc.get("mandatory", False)),
        "level": doc["level"],
        "default_profile": doc.get("default_profile", ""),
        "relative_cost": int(doc.get("relative_cost", 1)),
        "recommend": list(doc.get("recommend") or []),
    }


def _skill_row(doc: dict[str, Any]) -> dict[str, Any]:
    applies = doc.get("applies_to") or {}
    content = str(doc.get("content", ""))
    score = doc.get("eval_score")
    return {
        "key": str(doc["name"]),
        "version": str(doc["version"]),
        "title": doc.get("title") or doc["name"],
        "description": doc["description"],
        "skill_type": doc["type"],
        "agents": list(applies.get("agents") or []),
        "technologies": list(applies.get("technologies") or []),
        "conflicts": list(doc.get("conflicts") or []),
        "requires": list(doc.get("requires") or []),
        "status": doc.get("status", "draft"),
        "eval_score": score,
        "content": content,
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


def _same(existing: Any, row: dict[str, Any], ignore: set[str]) -> bool:
    def norm(value: Any) -> Any:
        return float(value) if hasattr(value, "as_integer_ratio") and not isinstance(value, bool) else value

    return all(norm(getattr(existing, k)) == norm(v) for k, v in row.items() if k not in ignore)


async def _sync_versioned(
    conn: AsyncConnection, table: Any, rows: list[dict[str, Any]], kind: str, report: SyncReport
) -> None:
    keys = {r["key"] for r in rows}
    for row in rows:
        existing = (
            await conn.execute(select(table).where(table.key == row["key"], table.version == row["version"]))
        ).first()
        if existing is not None and not _same(existing, row, {"key", "version"}):
            raise CatalogVersionError(
                f"{kind} {row['key']} {row['version']} changed without a new version; bump its version"
            )
        # Only one current version per key (partial unique index): clear first, then mark.
        await conn.execute(update(table).where(table.key == row["key"]).values(current=False))
        if existing is None:
            await conn.execute(pg_insert(table).values(**row, current=True))
            report.added.append(f"{kind}:{row['key']}@{row['version']}")
        else:
            await conn.execute(
                update(table).where(table.key == row["key"], table.version == row["version"]).values(current=True)
            )
            report.unchanged += 1
    gone: list[str] = list(
        (await conn.execute(select(table.key).where(table.current, table.key.not_in(keys)))).scalars().all()
    )
    if gone:
        await conn.execute(update(table).where(table.key.in_(gone)).values(current=False))
        report.retired += [f"{kind}:{k}" for k in gone]


async def _upsert(conn: AsyncConnection, table: Any, rows: list[dict[str, Any]], keys: list[str]) -> None:
    for row in rows:
        await conn.execute(
            pg_insert(table)
            .values(**row)
            .on_conflict_do_update(index_elements=keys, set_={k: v for k, v in row.items() if k not in keys})
        )


async def sync_catalog(conn: AsyncConnection) -> SyncReport:
    """Load the repository catalog into the database (platform_owner connection). Idempotent."""
    agents = nexti_agents.definitions()
    skills = nexti_skills.definitions()
    data = core_data()
    build_catalog(agents, skills, data)  # parse everything first: a broken file changes nothing

    report = SyncReport()
    await _sync_versioned(conn, AgentDefinition, [_agent_row(a) for a in agents], "agent", report)
    await _sync_versioned(conn, SkillDefinition, [_skill_row(s) for s in skills], "skill", report)

    src = data["sources"]
    await _upsert(conn, SourceAdapterDefinition, [dict(a) for a in src["adapters"]], ["key"])
    await _upsert(
        conn,
        SourceOptionDefinition,
        [
            {
                "key": o["key"],
                "position": i,
                "name": o["name"],
                "flows": list(option_flows(o["flow"])),
                "adapter_key": o.get("adapter"),
                "required_skills": list(o.get("required_skills") or []),
                "versions": list(o.get("versions") or []),
            }
            for i, o in enumerate(src["options"])
        ],
        ["key"],
    )
    await _upsert(
        conn,
        TargetOptionDefinition,
        [
            {"axis": axis, "key": o["key"], "position": i, "name": o["name"], "level": o.get("level"),
             "wave": o.get("wave"), "versions": list(o.get("versions") or [])}
            for axis in AXES
            for i, o in enumerate(data["targets"]["axes"][axis])
        ],
        ["axis", "key"],
    )  # fmt: skip
    await _upsert(
        conn,
        CompatibilityRuleDefinition,
        [
            {"key": r["key"], "position": i, "condition": r["when"], "message": r["message"]}
            for i, r in enumerate(data["compatibility"]["rules"])
        ],
        ["key"],
    )
    await _upsert(
        conn,
        PipelineTemplateDefinition,
        [
            {"key": t["key"], "position": i, "name": t["name"], "description": t["description"],
             "required_gates": list(t["required_gates"]), "default_autonomy": t["default_autonomy"]}
            for i, t in enumerate(data["templates"]["templates"])
        ],
        ["key"],
    )  # fmt: skip
    return report


async def load_catalog(conn: AsyncConnection) -> Catalog:
    """The catalog the engine uses: the current version of every agent and skill, and the options of the tables."""
    agents = (
        (await conn.execute(select(AgentDefinition).where(AgentDefinition.current).order_by(AgentDefinition.position)))
        .mappings()
        .all()
    )
    skills = (await conn.execute(select(SkillDefinition).where(SkillDefinition.current))).mappings().all()
    adapters = (await conn.execute(select(SourceAdapterDefinition))).mappings().all()
    options = (
        (await conn.execute(select(SourceOptionDefinition).order_by(SourceOptionDefinition.position))).mappings().all()
    )
    targets = (
        (await conn.execute(select(TargetOptionDefinition).order_by(TargetOptionDefinition.position))).mappings().all()
    )
    rules = (
        (await conn.execute(select(CompatibilityRuleDefinition).order_by(CompatibilityRuleDefinition.position)))
        .mappings()
        .all()
    )
    templates = (
        (await conn.execute(select(PipelineTemplateDefinition).order_by(PipelineTemplateDefinition.position)))
        .mappings()
        .all()
    )
    data = dict(core_data())
    data["sources"] = {
        "adapters": [dict(a) for a in adapters],
        "options": [
            {"key": o["key"], "name": o["name"], "flow": list(o["flows"]), "adapter": o["adapter_key"],
             "required_skills": o["required_skills"], "versions": list(o["versions"] or [])}
            for o in options
        ],
    }  # fmt: skip
    data["targets"] = {
        "axes": {
            axis: [
                {
                    "key": t["key"],
                    "name": t["name"],
                    "level": t["level"],
                    "wave": t["wave"],
                    "versions": list(t["versions"] or []),
                }
                for t in targets
                if t["axis"] == axis
            ]
            for axis in AXES
        }
    }
    data["compatibility"] = {
        "rules": [{"key": r["key"], "when": r["condition"], "message": r["message"]} for r in rules]
    }
    data["templates"] = {"templates": [dict(t) for t in templates]}
    agent_docs = [{**a, "id": a["key"], "order": a["position"], "group": a["agent_group"]} for a in agents]
    skill_docs = [
        {**s, "name": s["key"], "type": s["skill_type"],
         "applies_to": {"agents": s["agents"], "technologies": s["technologies"]}}
        for s in skills
    ]  # fmt: skip
    return build_catalog(agent_docs, skill_docs, data)
