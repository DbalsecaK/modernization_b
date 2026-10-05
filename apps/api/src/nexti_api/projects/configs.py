"""Versioned project configuration (spec 9.4, 9.7, 18.3): every change evaluates the composition with the
deterministic engine and, if valid, writes a new version with the catalog versions of its agents and skills pinned."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.errors import ProblemError
from nexti_core.composition import Catalog, Evaluation, Problem, Request, Target, evaluate
from nexti_core.db.models import ProjectAgent, ProjectConfig, ProjectSkill

AUTONOMY_LEVELS = ("guided", "balanced", "autonomous")


@dataclass(frozen=True)
class ConfigInput:
    sources: tuple[str, ...]
    target: Target
    pipeline_template: str
    autonomy: str
    max_iterations: int
    sampling_pct: int
    agents: list[str] | None = None  # None: the recommended team plus the Control agents
    skills: list[str] | None = None  # None: the recommended skills of the team
    change_note: str | None = None


class CompositionError(ProblemError):
    """422 with the first problem as the stable code and every problem in `problems`."""

    def __init__(self, problems: list[Problem]) -> None:
        first = problems[0]
        super().__init__(
            422,
            first.code,
            "The composition of the project is not valid.",
            problems=[{"code": p.code, "subject": p.subject} for p in problems],
        )


def check(catalog: Catalog, flow: str, config: ConfigInput) -> Evaluation:
    """Evaluate the composition; raise CompositionError if something blocks it."""
    evaluation = evaluate(catalog, Request(flow, config.sources, config.target), config.agents, config.skills)
    problems = list(evaluation.problems)
    if catalog.template(config.pipeline_template) is None:
        problems.append(Problem("unknown_pipeline_template", config.pipeline_template))
    if config.autonomy not in AUTONOMY_LEVELS:
        problems.append(Problem("unknown_autonomy", config.autonomy))
    if problems:
        raise CompositionError(problems)
    return evaluation


async def write_config(
    conn: AsyncConnection,
    catalog: Catalog,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    flow: str,
    config: ConfigInput,
    by: uuid.UUID | None,
) -> tuple[int, Evaluation]:
    """Insert the next configuration version. The caller's transaction scope must see the project (RLS)."""
    evaluation = check(catalog, flow, config)
    current = (
        await conn.execute(select(func.max(ProjectConfig.version)).where(ProjectConfig.project_id == project_id))
    ).scalar_one()
    version = (current or 0) + 1
    target: dict[str, Any] = {
        axis: config.target.get(axis) for axis in ("architecture", "backend", "frontend", "database", "cloud")
    }
    if config.target.versions:
        target["versions"] = dict(config.target.versions)
    await conn.execute(
        insert(ProjectConfig).values(
            tenant_id=tenant_id,
            project_id=project_id,
            version=version,
            sources=list(config.sources),
            target=target,
            pipeline_template=config.pipeline_template,
            autonomy=config.autonomy,
            max_iterations=config.max_iterations,
            sampling_pct=config.sampling_pct,
            warnings=list(evaluation.warnings),
            change_note=config.change_note,
            created_by=by,
        )
    )
    reasons = {r.agent: r.reason for r in evaluation.recommended_agents}
    agent_rows = [
        {"tenant_id": tenant_id, "project_id": project_id, "config_version": version, "agent_key": key,
         "agent_version": agent.version, "reason": reasons.get(key)}
        for key in evaluation.agents
        if (agent := catalog.agent(key)) is not None
    ]  # fmt: skip
    skill_rows = [
        {"tenant_id": tenant_id, "project_id": project_id, "config_version": version, "skill_key": key,
         "skill_version": skill.version, "recommended": key in evaluation.recommended_skills}
        for key in evaluation.skills
        if (skill := catalog.skill(key)) is not None
    ]  # fmt: skip
    await conn.execute(insert(ProjectAgent), agent_rows)
    if skill_rows:
        await conn.execute(insert(ProjectSkill), skill_rows)
    return version, evaluation
