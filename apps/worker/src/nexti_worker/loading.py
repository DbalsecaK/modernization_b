"""The RunContext of a run, rebuilt from the database: the run, its configuration version (template gates, agents)
and the phases of the project's flow. The same run always rebuilds the same graph, so its checkpoints stay valid."""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_core.composition.loader import core_data, flows
from nexti_core.db.session import DbScope, scoped_connection
from nexti_orchestration import AgentSpec, PhaseSpec, RunContext


class RunNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class LoadedRun:
    context: RunContext
    status: str
    started_by: uuid.UUID | None
    config_version: int
    relative_cost: int  # sum of the agents' relative cost (the configuration's estimate, 9.4)


async def load_run(engine: AsyncEngine, run_id: uuid.UUID, tenant_id: uuid.UUID) -> LoadedRun:
    async with scoped_connection(engine, DbScope(tenant_id=tenant_id)) as conn:
        run = (
            (
                await conn.execute(
                    text(
                        "SELECT r.*, p.flow, c.pipeline_template, c.target, t.required_gates FROM run r "
                        "JOIN project p ON p.id = r.project_id "
                        "JOIN project_config c ON c.project_id = r.project_id AND c.version = r.config_version "
                        "JOIN pipeline_template t ON t.key = c.pipeline_template WHERE r.id = :run"
                    ),
                    {"run": run_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if run is None:
            raise RunNotFoundError(str(run_id))
        agents = (
            (
                await conn.execute(
                    text(
                        "SELECT a.key, a.name, a.phases, a.mandatory, a.relative_cost FROM project_agent pa "
                        "JOIN agent_definition a ON a.key = pa.agent_key AND a.version = pa.agent_version "
                        "WHERE pa.project_id = :project AND pa.config_version = :version ORDER BY a.position"
                    ),
                    {"project": run["project_id"], "version": run["config_version"]},
                )
            )
            .mappings()
            .all()
        )
    flow = next((f for f in flows(core_data()) if f.key == run["flow"]), None)
    if flow is None:
        raise RunNotFoundError(f"unknown flow {run['flow']}")
    context = RunContext(
        run_id=run_id,
        tenant_id=tenant_id,
        project_id=run["project_id"],
        kind=run["kind"],
        flow=flow.key,
        phases=tuple(PhaseSpec(p.key, p.gate, p.agent_required) for p in flow.phases),
        template_gates=tuple(run["required_gates"]),
        autonomy=run["autonomy"],
        max_iterations=run["max_iterations"],
        agents=tuple(AgentSpec(a["key"], a["name"], tuple(a["phases"]), a["mandatory"]) for a in agents),
        options=dict(run["options"] or {}),
        target=flat_target(run["target"] or {}),
    )
    return LoadedRun(
        context=context,
        status=run["status"],
        started_by=run["started_by"],
        config_version=run["config_version"],
        relative_cost=sum(int(a["relative_cost"]) for a in agents),
    )


def flat_target(stored: Mapping[str, Any]) -> dict[str, str]:
    """The target as the run reads it: the axes, and the chosen versions as `<axis>_version` (ADR-0037)."""
    target = {str(k): str(v) for k, v in stored.items() if v and k != "versions"}
    versions = stored.get("versions") or {}
    if isinstance(versions, Mapping):
        target.update({f"{axis}_version": str(v) for axis, v in versions.items() if v})
    return target
