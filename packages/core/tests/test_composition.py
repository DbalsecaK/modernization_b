"""Deterministic composition (spec 9.4, 9.7, 8.5) over the real catalog files of packages/agents, packages/skills and
nexti_core.composition (M2 acceptance: the expected team and skills; Control agents cannot be removed)."""

import pytest

import nexti_agents
import nexti_skills
from nexti_core.ai_catalog import AGENT_ROLES, PHASES
from nexti_core.composition import AXES, Catalog, Request, Target, build_catalog, evaluate
from nexti_core.composition.model import Condition

CICS_TO_SPRING = Request(
    flow="modernization",
    sources=("cobol-cics", "bms"),
    target=Target("microservices-hexagonal", "spring-boot", "angular", "postgresql", "aws"),
)


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return build_catalog(nexti_agents.definitions(), nexti_skills.definitions())


def test_the_catalog_references_only_what_exists(catalog: Catalog) -> None:
    agents = {a.key for a in catalog.agents}
    skills = {s.key for s in catalog.skills}
    options = {("source", s.key) for s in catalog.sources} | {(t.axis, t.key) for t in catalog.targets}
    technologies = {s.key for s in catalog.sources} | {t.key for t in catalog.targets}
    # The agent roles of the model assignment matrix (M1) are exactly the agents of the catalog.
    assert agents == set(AGENT_ROLES)
    assert len(catalog.agents) == 19
    assert len(catalog.skills) == 21
    for agent in catalog.agents:
        assert set(agent.phases) <= set(PHASES), agent.key
        assert agent.group in {"analysis", "design", "build", "quality", "control"}
        assert agent.mandatory == (agent.group == "control"), agent.key
        for rule in agent.recommend:
            assert rule.when.referenced_options() <= options, agent.key
    for skill in catalog.skills:
        assert set(skill.agents) <= agents, skill.key
        assert set(skill.technologies) <= technologies, skill.key
        assert set(skill.conflicts) <= skills, skill.key
        assert all(skill.key in other.conflicts for other in catalog.skills if other.key in skill.conflicts)
        assert skill.content.startswith("# "), skill.key
        assert skill.type in {"source", "target", "conversion", "crossCutting"}
    for option in catalog.sources:
        assert set(option.required_skills) <= skills
        assert option.adapter is None or option.adapter in {a.key for a in catalog.adapters}
    for compat in catalog.rules:
        assert compat.when.referenced_options() <= options, compat.key
    assert {t.axis for t in catalog.targets} == set(AXES)
    gates = {"modernization": ["C1", "C2", "C3", "C4"], "newFeature": ["C1", "C2", "C3", "C4"],
             "independentValidation": ["C1", "C2", "C4"], "extendExisting": ["C1", "C3", "C4"]}  # fmt: skip
    assert [f.key for f in catalog.flows] == list(gates)
    for flow in catalog.flows:
        assert {p.key for p in flow.phases} <= set(PHASES)
        assert [p.gate for p in flow.phases if p.gate] == gates[flow.key]
    assert all(set(t.required_gates) <= {"C1", "C2", "C3", "C4"} for t in catalog.templates)


def test_cics_bms_to_spring_angular_postgres_aws_proposes_the_expected_team_and_skills(catalog: Catalog) -> None:
    result = evaluate(catalog, CICS_TO_SPRING)

    assert result.ok, result.problems
    assert {r.agent: r.reason for r in result.recommended_agents} == {
        "legacy-analyst": "legacySource",
        "rules-extractor": "legacySource",
        "data-analyst": "legacySource",
        "ui-analyst": "legacyScreens",
        "solution-architect": "always",
        "data-architect": "always",
        "ux-designer": "noFigma",
        "backend-dev": "backend",
        "frontend-dev": "frontend",
        "data-migration": "dataMigration",
        "devops": "cloud",
        "test-engineer": "always",
        "code-reviewer": "always",
        "security-auditor": "always",
        "rules-verifier": "control",
        "equivalence-validator": "control",
        "acceptance-judge": "control",
    }
    assert set(result.agents) == {r.agent for r in result.recommended_agents}
    assert "functional-analyst" not in result.agents
    assert "fullstack-dev" not in result.agents
    assert set(result.skills) == {
        "cobol-data-semantics",
        "exec-cics",
        "bms-parsing",
        "cics-to-rest",
        "bms-to-forms",
        "spring-hexagonal",
        "angular-material",
        "postgres",
        "aws-iac",
        "owasp",
        "gherkin",
        "golden-master",
        "wcag",
    }
    assert result.missing_skills == ()
    assert result.warnings == ()
    assert result.uncovered_phases == ()
    costs = {a.key: a.relative_cost for a in catalog.agents}
    assert result.estimate_usd == sum(costs[a] for a in result.agents) * 260


def test_the_same_request_always_gives_the_same_answer(catalog: Catalog) -> None:
    assert evaluate(catalog, CICS_TO_SPRING) == evaluate(catalog, CICS_TO_SPRING)


@pytest.mark.parametrize("control", ["rules-verifier", "equivalence-validator", "acceptance-judge"])
def test_a_control_agent_cannot_be_removed(catalog: Catalog, control: str) -> None:
    proposal = evaluate(catalog, CICS_TO_SPRING)
    chosen = [a for a in proposal.agents if a != control]
    result = evaluate(catalog, CICS_TO_SPRING, agents=chosen, skills=list(proposal.skills))
    assert not result.ok
    assert ("control_agent_required", control) in [(p.code, p.subject) for p in result.problems]
    # The equivalence validator is also the only agent of the verification phase.
    assert {p.code for p in result.problems} <= {"control_agent_required", "uncovered_phase"}


def test_control_agents_are_always_in_the_proposal(catalog: Catalog) -> None:
    request = Request("newFeature", ("user-stories",), Target("mvc", "dotnet-10", "none", "sqlserver", "azure"))
    result = evaluate(catalog, request)
    assert set(catalog.mandatory_agents) <= set(result.agents)


def test_new_feature_with_figma_needs_no_ux_designer(catalog: Catalog) -> None:
    request = Request(
        "newFeature", ("user-stories", "figma"), Target("mvc", "dotnet-10", "react", "sqlserver", "azure")
    )
    reasons = {r.agent: r.reason for r in evaluate(catalog, request).recommended_agents}
    assert reasons["functional-analyst"] == "documents"
    assert reasons["ui-analyst"] == "visualInputs"
    assert "ux-designer" not in reasons
    assert "legacy-analyst" not in reasons
    assert "equivalence-validator" not in reasons


def test_independent_validation_offers_the_legacy_sources_and_needs_the_analysis_agents(catalog: Catalog) -> None:
    # Flow 4 (ADR-0025): the legacy technologies of Flow 1; the target is the third party's stack.
    request = Request(
        "independentValidation", ("sybase-sp",), Target("modular-monolith", "spring-boot", "none", "postgresql", "aws")
    )
    legacy = {s.key for s in catalog.sources if "modernization" in s.flows}
    assert legacy == {s.key for s in catalog.sources if "independentValidation" in s.flows}
    agents = ["legacy-analyst", "rules-extractor", *catalog.mandatory_agents]
    result = evaluate(catalog, request, agents=agents)
    assert result.ok, result.problems
    assert result.uncovered_phases == ()
    proposed = evaluate(catalog, request)  # the proposal of the wizard: the legacy readers and the Control agents
    assert {"legacy-analyst", "rules-extractor"} <= set(proposed.agents)
    assert (proposed.ok, proposed.uncovered_phases) == (True, ())
    without = evaluate(catalog, request, agents=["rules-extractor", *catalog.mandatory_agents])
    assert without.uncovered_phases == ("inventory",)
    figma = evaluate(catalog, Request("independentValidation", ("figma",), request.target), agents=agents)
    assert ("unknown_source", "figma") in [(p.code, p.subject) for p in figma.problems]


def test_extend_existing_brings_the_application_and_the_documents_and_covers_every_phase(catalog: Catalog) -> None:
    # Flow 3 (ADR-0026): the existing Spring Boot application plus the documentary inputs of Flow 2, backend only.
    request = Request(
        "extendExisting",
        ("spring-boot-app", "user-stories"),
        Target("modular-monolith", "spring-boot", "none", "postgresql", "aws"),
    )
    offered = {s.key for s in catalog.sources if "extendExisting" in s.flows}
    assert offered == {"spring-boot-app", "user-stories", "functional-document", "user-manual"}
    proposed = evaluate(catalog, request)  # the proposal of the wizard
    assert (proposed.ok, proposed.uncovered_phases) == (True, ())
    reasons = {r.agent: r.reason for r in proposed.recommended_agents}
    assert reasons["functional-analyst"] == "documents"
    assert {"solution-architect", "backend-dev", "test-engineer"} <= set(proposed.agents)
    assert not {"legacy-analyst", "rules-extractor"} & set(proposed.agents)  # no rules mined from the code
    without = evaluate(catalog, request, agents=[a for a in proposed.agents if a != "functional-analyst"])
    assert without.uncovered_phases == ("normalization",)
    figma = evaluate(catalog, Request("extendExisting", ("figma",), request.target))
    assert ("unknown_source", "figma") in [(p.code, p.subject) for p in figma.problems]


def test_without_frontend_there_is_no_frontend_or_ux_work(catalog: Catalog) -> None:
    request = Request(
        "modernization", ("sybase-sp",), Target("modular-monolith", "spring-boot", "none", "postgresql", "aws")
    )
    result = evaluate(catalog, request)
    assert "frontend-dev" not in result.agents
    assert "ux-designer" not in result.agents
    assert "sybase-tsql" in result.skills
    assert "sybase-to-service" in result.skills


def test_conflicting_skills_block(catalog: Catalog) -> None:
    proposal = evaluate(catalog, CICS_TO_SPRING)
    result = evaluate(catalog, CICS_TO_SPRING, agents=list(proposal.agents), skills=[*proposal.skills, "quarkus"])
    assert result.conflicts == (("quarkus", "spring-hexagonal"),)
    assert [p.code for p in result.problems] == ["skill_conflict"]


def test_a_source_without_its_skill_is_warned(catalog: Catalog) -> None:
    proposal = evaluate(catalog, CICS_TO_SPRING)
    skills = [s for s in proposal.skills if s != "bms-parsing"]
    result = evaluate(catalog, CICS_TO_SPRING, agents=list(proposal.agents), skills=skills)
    assert result.ok  # a warning, not a blocker (9.7)
    assert [(m.source, m.skill) for m in result.missing_skills] == [("bms", "bms-parsing")]


def test_every_phase_needs_a_responsible_agent(catalog: Catalog) -> None:
    proposal = evaluate(catalog, CICS_TO_SPRING)
    builders = {"backend-dev", "frontend-dev", "fullstack-dev", "data-migration", "code-reviewer"}
    agents = [a for a in proposal.agents if a not in builders]
    skills = [s for s in proposal.skills if set(catalog.skill(s).agents) & set(agents)]  # type: ignore[union-attr]
    result = evaluate(catalog, CICS_TO_SPRING, agents=agents, skills=skills)
    assert result.uncovered_phases == ("generation",)
    assert [p.code for p in result.problems] == ["uncovered_phase"]


def test_full_stack_replaces_backend_and_frontend(catalog: Catalog) -> None:
    proposal = evaluate(catalog, CICS_TO_SPRING)
    agents = [a for a in proposal.agents if a not in {"backend-dev", "frontend-dev"}] + ["fullstack-dev"]
    result = evaluate(catalog, CICS_TO_SPRING, agents=agents)
    assert result.ok
    assert "spring-hexagonal" in result.skills  # applies to the full stack developer too


def test_a_skill_needs_an_agent_that_uses_it(catalog: Catalog) -> None:
    proposal = evaluate(catalog, CICS_TO_SPRING)
    result = evaluate(catalog, CICS_TO_SPRING, agents=list(proposal.agents), skills=[*proposal.skills, "azure-iac"])
    assert result.ok  # devops is in the team, so the skill applies
    no_devops = [a for a in proposal.agents if a != "devops"]
    result = evaluate(catalog, CICS_TO_SPRING, agents=no_devops, skills=["azure-iac"])
    assert ("skill_not_applicable", "azure-iac") in [(p.code, p.subject) for p in result.problems]


@pytest.mark.parametrize(
    ("target", "sources", "warning"),
    [
        (Target("serverless", "spring-boot", "react", "postgresql", "aws"), ("cobol",), "serverlessBatch"),
        (Target("serverless", "spring-boot", "react", "postgresql", "aws"), ("cobol-cics",), "serverlessCics"),
        (Target("mvc", "nextjs", "react", "postgresql", "aws"), ("cobol",), "nextBff"),
        (Target("mvc", "go", "react", "postgresql", "aws"), ("cobol",), "goConventions"),
        (Target("mvc", "spring-boot", "react", "mongodb", "aws"), ("cobol",), "mongoModeling"),
        (Target("mvc", "dotnet-10", "react", "sqlserver", "azure"), ("dotnet-framework",), "upliftOption"),
    ],
)
def test_compatibility_rules(catalog: Catalog, target: Target, sources: tuple[str, ...], warning: str) -> None:
    assert warning in evaluate(catalog, Request("modernization", sources, target)).warnings


def test_next_js_on_both_sides_is_not_a_bff_warning(catalog: Catalog) -> None:
    request = Request("modernization", ("cobol",), Target("mvc", "nextjs", "nextjs", "postgresql", "aws"))
    assert "nextBff" not in evaluate(catalog, request).warnings


def test_a_version_must_be_listed_and_available(catalog: Catalog) -> None:
    def codes(versions: dict[str, str]) -> set[tuple[str, str | None]]:
        target = Target("mvc", "spring-boot", "react", "postgresql", "aws", versions)
        return {(p.code, p.subject) for p in evaluate(catalog, Request("modernization", ("cobol",), target)).problems}

    assert codes({"backend": "3.5", "frontend": "19"}) == set()
    assert ("unknown_target_version", "backend:spring-boot:2.7") in codes({"backend": "2.7"})
    assert ("target_version_not_available", "frontend:react:18") in codes({"frontend": "18"})
    spring = catalog.target_option("backend", "spring-boot")
    assert spring is not None
    assert [v.key for v in spring.versions if v.default] == ["3.5"]


def test_invalid_requests_are_problems_not_crashes(catalog: Catalog) -> None:
    request = Request("modernization", ("figma", "zos-assembler"), Target("mvc", "cobol", "react", "postgresql", "aws"))
    codes = {(p.code, p.subject) for p in evaluate(catalog, request).problems}
    assert ("unknown_source", "figma") in codes  # a flow 2 input in a modernization project
    assert ("unknown_source", "zos-assembler") in codes
    assert ("unknown_target_option", "backend:cobol") in codes
    assert ("no_sources", None) in {
        (p.code, p.subject) for p in evaluate(catalog, Request("newFeature", (), request.target)).problems
    }


def test_conditions_reject_unknown_keys() -> None:
    with pytest.raises(ValueError, match="unknown condition keys"):
        Condition.from_mapping({"flwo": "modernization"})
    with pytest.raises(ValueError, match="unknown target axes"):
        Condition.from_mapping({"target": {"language": ["java"]}})
