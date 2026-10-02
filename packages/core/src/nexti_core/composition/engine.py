"""Deterministic composition of a project (spec 9.4, 9.7 and 8.5). No model is involved: the same request and the
same catalog always give the same team, skills and warnings, and every recommendation carries its reason.

`evaluate` is used twice: to propose (agents and skills not given yet) and to validate what the user chose before
the project is created or its configuration changes. Problems block; warnings inform.
"""

from dataclasses import dataclass

from nexti_core.composition.model import AXES, FLOWS, Catalog, Request


@dataclass(frozen=True)
class Recommendation:
    agent: str
    reason: str  # stable key, translated by the UI


@dataclass(frozen=True)
class Problem:
    """Something that prevents creating the project or saving the configuration."""

    code: str
    subject: str | None = None


@dataclass(frozen=True)
class MissingSkill:
    source: str
    skill: str


@dataclass(frozen=True)
class Evaluation:
    recommended_agents: tuple[Recommendation, ...]
    agents: tuple[str, ...]
    recommended_skills: tuple[str, ...]
    skills: tuple[str, ...]
    warnings: tuple[str, ...]  # compatibility rules that apply
    missing_skills: tuple[MissingSkill, ...]
    conflicts: tuple[tuple[str, str], ...]
    uncovered_phases: tuple[str, ...]
    problems: tuple[Problem, ...]
    estimate_usd: int

    @property
    def ok(self) -> bool:
        return not self.problems


def recommend_agents(catalog: Catalog, request: Request) -> tuple[Recommendation, ...]:
    """The first rule of each agent that matches gives the reason; catalog order."""
    out = []
    for agent in sorted(catalog.agents, key=lambda a: a.order):
        rule = next((r for r in agent.recommend if r.when.matches(request)), None)
        if rule is not None:
            out.append(Recommendation(agent.key, rule.reason))
    return tuple(out)


def recommend_skills(catalog: Catalog, agents: tuple[str, ...], request: Request) -> tuple[str, ...]:
    """Published skills that apply to a chosen agent and to the project's technologies (or to any technology)."""
    chosen = set(agents)
    techs = request.technologies()
    return tuple(
        s.key
        for s in catalog.skills
        if s.status == "published" and chosen & set(s.agents) and (not s.technologies or techs & set(s.technologies))
    )


def compatibility_warnings(catalog: Catalog, request: Request) -> tuple[str, ...]:
    return tuple(rule.key for rule in catalog.rules if rule.when.matches(request))


def _request_problems(catalog: Catalog, request: Request) -> list[Problem]:
    problems = []
    if request.flow not in FLOWS or catalog.flow(request.flow) is None:
        problems.append(Problem("unknown_flow", request.flow))
    if not request.sources:
        problems.append(Problem("no_sources"))
    for key in request.sources:
        option = catalog.source(key)
        if option is None or request.flow not in option.flows:
            problems.append(Problem("unknown_source", key))
    for axis in AXES:
        if catalog.target_option(axis, request.target.get(axis)) is None:
            problems.append(Problem("unknown_target_option", f"{axis}:{request.target.get(axis)}"))
    return problems


def _ordered(keys: set[str], order: list[str]) -> tuple[str, ...]:
    return tuple(k for k in order if k in keys)


def evaluate(
    catalog: Catalog, request: Request, agents: list[str] | None = None, skills: list[str] | None = None
) -> Evaluation:
    problems = _request_problems(catalog, request)
    recommended = recommend_agents(catalog, request)
    agent_order = [a.key for a in sorted(catalog.agents, key=lambda a: a.order)]

    if agents is None:
        # A proposal: the recommended team plus the Control agents, which are always part of it.
        final_agents = _ordered({r.agent for r in recommended} | set(catalog.mandatory_agents), agent_order)
    else:
        known = {a for a in agents if catalog.agent(a) is not None}
        problems += [Problem("unknown_agent", a) for a in dict.fromkeys(agents) if a not in known]
        final_agents = _ordered(known, agent_order)
        # Control agents cannot be removed, only their model changed (9.4, rule 6 of CLAUDE.md).
        problems += [Problem("control_agent_required", m) for m in catalog.mandatory_agents if m not in known]

    recommended_skills = recommend_skills(catalog, final_agents, request)
    skill_order = [s.key for s in catalog.skills]
    if skills is None:
        final_skills = recommended_skills
    else:
        known_skills = {s for s in skills if catalog.skill(s) is not None}
        problems += [Problem("unknown_skill", s) for s in dict.fromkeys(skills) if s not in known_skills]
        final_skills = _ordered(known_skills, skill_order)
        for key in final_skills:
            skill = catalog.skill(key)
            if skill is not None and not set(skill.agents) & set(final_agents):
                problems.append(Problem("skill_not_applicable", key))

    chosen_skills = set(final_skills)
    conflicts = []
    for key in final_skills:
        skill = catalog.skill(key)
        for other in skill.conflicts if skill else ():
            if other in chosen_skills and key < other:
                conflicts.append((key, other))
    problems += [Problem("skill_conflict", f"{a}+{b}") for a, b in conflicts]
    for key in final_skills:
        skill = catalog.skill(key)
        problems += [
            Problem("skill_requirement_missing", f"{key}>{req}")
            for req in (skill.requires if skill else ())
            if req not in chosen_skills
        ]

    missing = []
    for source in request.sources:
        option = catalog.source(source)
        missing += [
            MissingSkill(source, s) for s in (option.required_skills if option else ()) if s not in chosen_skills
        ]

    flow = catalog.flow(request.flow)
    covered = {phase for a in final_agents if (agent := catalog.agent(a)) for phase in agent.phases}
    uncovered = tuple(p.key for p in (flow.phases if flow else ()) if p.agent_required and p.key not in covered)
    problems += [Problem("uncovered_phase", p) for p in uncovered]

    cost = sum(agent.relative_cost for a in final_agents if (agent := catalog.agent(a)))
    return Evaluation(
        recommended_agents=recommended,
        agents=final_agents,
        recommended_skills=recommended_skills,
        skills=final_skills,
        warnings=compatibility_warnings(catalog, request),
        missing_skills=tuple(missing),
        conflicts=tuple(conflicts),
        uncovered_phases=uncovered,
        problems=tuple(problems),
        estimate_usd=cost * catalog.cost_unit_usd,
    )
