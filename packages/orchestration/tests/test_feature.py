"""Flow 2, analysis half (spec 7.2 phases 1-3, ADR-0018), on the fictitious "Simulador de crédito": code checks every
citation, the Gherkin and the coverage of what the analyst answers, and finds the gaps of 7.3; each gap becomes a
question whose recommended answer is applied when a person answers."""

import json
import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from nexti_core.composition.loader import core_data, flows
from nexti_core.spec.design import Design
from nexti_core.spec.model import Capability, Rule
from nexti_core.spec.screens import ScreenSpec
from nexti_ingest.documents import Document
from nexti_orchestration import AgentSpec, PhaseSpec, RunContext, compile_graph, executors_for
from nexti_orchestration.extraction import ModelReply, ReplyError
from nexti_orchestration.feature import (
    FeatureStory,
    apply_gaps,
    gaps,
    numbered,
    parse_contradictions,
    parse_normalized,
    stories_of,
)
from nexti_orchestration.feature_build import endpoint_missing, untraced
from nexti_orchestration.memory import MemoryStore
from nexti_orchestration.model import Answer
from nexti_orchestration.store import Usage
from nexti_orchestration.stories import Stories

from .feature_example import FIGMA, FIGMA_FILE, INPUTS, normalized
from .test_modernization import OkProbe, run_until_wait

FEATURE_PHASES = tuple(
    PhaseSpec(p.key, p.gate, p.agent_required) for f in flows(core_data()) if f.key == "newFeature" for p in f.phases
)
FEATURE_TEAM = (
    AgentSpec("functional-analyst", "Functional analyst", ("ingestion", "normalization", "consolidation"), False),
    AgentSpec("rules-verifier", "Rules verifier", ("consolidation",), True),
)


def test_the_inputs_go_to_the_agent_with_numbered_lines() -> None:
    text = numbered(INPUTS)
    assert "=== docs/requisitos.md (" in text
    assert f"=== figma/{FIGMA_FILE} (" in text
    assert f"figma/{FIGMA_FILE}.json" not in text  # the raw file is evidence, not citable
    assert " 1| # Simulador de crédito de consumo — Requisitos" in text


def test_a_valid_answer_becomes_the_specification() -> None:
    result = parse_normalized(json.dumps(normalized()), INPUTS)
    assert [r.id for r in result.rules] == [f"RULE-00{i}" for i in range(1, 7)]
    assert [s.id for s in result.screens] == ["SCR-SIMULADOR", "SCR-RESULTADO"]
    assert str(result.rules[0].sources[0]).startswith("docs/requisitos.md:")
    assert len(result.stories) == 2
    assert result.stories[0].criteria[0].startswith("Escenario: Cuota de un crédito a 12 meses")
    plan = stories_of(result.stories)
    assert (plan.origin, plan.waves) == ("document", [["US-001", "US-002"]])


def test_citations_gherkin_and_coverage_are_checked_by_code() -> None:
    answer = normalized()
    answer["rules"][0]["sources"] = ["docs/requisitos.md:900-901"]
    answer["rules"][1]["sources"] = ["docs/otro.md:1"]
    answer["stories"][1]["criteria"] = ["Escenario: sin pasos"]
    answer["stories"][1]["links"] = ["RULE-099"]
    with pytest.raises(ReplyError) as problems:
        parse_normalized(json.dumps(answer), INPUTS)
    text = str(problems.value)
    assert "RULE-001: cites docs/requisitos.md:900-901, but docs/requisitos.md has" in text
    assert "RULE-002: cites docs/otro.md, which is not an input" in text
    assert "story 2 'Guardar cada simulación', criterion 1:" in text
    assert "links elements that do not exist: RULE-099" in text
    assert "these rules and screens are in no story: RULE-006" in text


def _spec() -> tuple[list[ScreenSpec], list[Rule], list[FeatureStory]]:
    result = parse_normalized(json.dumps(normalized()), INPUTS)
    stories = [FeatureStory(f"US-00{i}", d.title, d.criteria, d.links, "review")
               for i, d in enumerate(result.stories, start=1)]  # fmt: skip
    return result.screens, result.rules, stories


def test_the_gaps_of_7_3_are_found_by_code() -> None:
    screens, rules, stories = _spec()
    found = {g.key: g for g in gaps(screens, rules, stories, [(FIGMA_FILE, FIGMA)])}
    assert set(found) == {
        "gap-validation-SCR-SIMULADOR",  # monto and plazo have no validation
        "gap-states-SCR-SIMULADOR",  # an input screen without error and empty states
        f"gap-button-{FIGMA_FILE}-2-8",  # "Botón Descargar PDF" navigates nowhere
    }
    assert found[f"gap-button-{FIGMA_FILE}-2-8"].affects == ("SCR-RESULTADO",)
    assert found["gap-validation-SCR-SIMULADOR"].recommended.key == "validate"


def test_the_recommended_answers_are_applied() -> None:
    screens, rules, stories = _spec()
    found = gaps(screens, rules, stories, [(FIGMA_FILE, FIGMA)])
    answers = {g.key: Answer(g.recommended.key, g.recommended.label) for g in found}
    fixed, kept = apply_gaps(answers, found, screens, rules, [(FIGMA_FILE, FIGMA)])
    simulator, result = fixed
    assert all(f.required and f.validation for f in simulator.inputs())
    assert set(simulator.states) == {"error", "empty"}
    assert [a.key for a in result.actions] == ["nueva"]  # the dead button left the screen
    assert kept == rules
    assert gaps(fixed, kept, stories, []) == []


def test_a_person_may_keep_the_gap() -> None:
    screens, rules, stories = _spec()
    found = gaps(screens, rules, stories, [(FIGMA_FILE, FIGMA)])
    answers = {g.key: Answer(g.alternative.key, g.alternative.label) for g in found}
    fixed, _ = apply_gaps(answers, found, screens, rules, [(FIGMA_FILE, FIGMA)])
    assert fixed == screens


def test_a_contradiction_must_cite_both_sides_and_known_elements() -> None:
    known = {"RULE-001", "SCR-SIMULADOR"}
    sources = ["docs/requisitos.md:13", f"figma/{FIGMA_FILE}:13"]
    good = {"contradictions": [{"text": "El mensaje difiere", "sources": sources, "affects": ["RULE-001"],
                                "recommended": "El del documento", "alternative": "El de Figma"}]}  # fmt: skip
    (found,) = parse_contradictions(json.dumps(good), INPUTS, known)
    assert found.affects == ("RULE-001",)
    bad = {"contradictions": [{"text": "x", "sources": ["docs/nada.md:1"], "affects": ["RULE-404"],
                               "recommended": "y"}]}  # fmt: skip
    with pytest.raises(ReplyError, match="RULE-404"):
        parse_contradictions(json.dumps(bad), INPUTS, known)
    assert parse_contradictions('{"contradictions": []}', INPUTS, known) == []


# -- the analysis half as a pipeline, up to C1 ----------------------------------------------------------------------
class FeatureModel:
    """Answers like the agents would: the normalized example, and one contradiction about the amount message."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def complete(self, agent: str, phase: str, messages: list[dict[str, str]], *, iteration: int = 1,
                       judge: int = 0) -> ModelReply:  # fmt: skip
        self.calls.append((agent, phase))
        if phase == "normalization":
            content: dict[str, Any] = normalized()
        else:
            content = {"contradictions": [{
                "text": "Figma muestra el mensaje del monto sin el rango del plazo", "affects": ["RULE-001"],
                "sources": ["docs/requisitos.md:13", f"figma/{FIGMA_FILE}:14"],
                "recommended": "Usar el texto del documento", "alternative": "Usar el texto de Figma",
            }]}  # fmt: skip
        return ModelReply(json.dumps(content), Usage(model="stand-in", input_tokens=50, output_tokens=20))


class FeatureMemoryPort:
    def __init__(self) -> None:
        self.models = FeatureModel()
        self.artifacts: dict[str, str] = {}
        self.rules: list[Rule] = []
        self.screens: list[ScreenSpec] = []
        self.capabilities: list[Capability] = []
        self.stories: Stories | None = None

    async def documents(self) -> list[Document]:
        return [Document("docs/requisitos.md", INPUTS["docs/requisitos.md"]),
                Document("docs/historias.md", INPUTS["docs/historias.md"])]  # fmt: skip

    async def figma_files(self) -> list[tuple[str, dict[str, Any]]]:
        return [(FIGMA_FILE, FIGMA)]

    async def input_names(self, kind: str) -> list[str]:
        return []

    async def save_artifacts(self, files: dict[str, str], layers: dict[str, str], rules: dict[str, list[str]]) -> None:
        self.artifacts.update(files)

    async def load_inputs(self) -> dict[str, str]:
        return {p: t for p, t in self.artifacts.items() if p.startswith("inputs/")}

    async def save_rules(self, rules: Sequence[Rule]) -> None:
        self.rules = list(rules)

    async def load_rules(self) -> list[Rule]:
        return list(self.rules)

    async def save_screens(self, screens: Sequence[ScreenSpec]) -> None:
        self.screens = list(screens)

    async def load_screens(self) -> list[ScreenSpec]:
        return list(self.screens)

    async def save_capabilities(self, capabilities: Sequence[Capability]) -> None:
        self.capabilities = list(capabilities)

    async def save_stories(self, stories: Stories) -> None:
        self.stories = stories

    async def load_stories(self) -> list[FeatureStory]:
        assert self.stories is not None
        return [FeatureStory(k, d.title, d.criteria, d.links, "review")
                for k, d in zip(self.stories.keys(), self.stories.drafts, strict=True)]  # fmt: skip


def feature_run() -> RunContext:
    return RunContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pipeline", "newFeature", FEATURE_PHASES,
                      ("C1", "C2", "C3", "C4"), "balanced", 3, FEATURE_TEAM)  # fmt: skip


async def test_flow_2_reaches_c1_with_the_gaps_answered_and_every_element_traced() -> None:
    run, store, port = feature_run(), MemoryStore(), FeatureMemoryPort()
    graph = compile_graph(run, store, executors_for(run, OkProbe(), port), InMemorySaver())  # type: ignore[arg-type]

    (waiting,) = await run_until_wait(graph, run)
    assert waiting["type"] == "questions"
    asked = {q["question"].key: q["question"] for q in store.questions.values()}
    assert set(asked) == {"gap-validation-SCR-SIMULADOR", "gap-states-SCR-SIMULADOR",
                          f"gap-button-{FIGMA_FILE}-2-8", "contradiction-1"}  # fmt: skip
    assert asked["contradiction-1"].reason == "contradiction"
    assert set(port.artifacts) == {"inputs/docs/requisitos.md", "inputs/docs/historias.md",
                                   f"inputs/figma/{FIGMA_FILE}", f"inputs/figma/{FIGMA_FILE}.json"}  # fmt: skip
    before = len(port.models.calls)

    by_id = {str(qid): q["question"] for qid, q in store.questions.items()}
    answers = {qid: {"option": by_id[qid].recommended.key} for qid in waiting["question_ids"]}
    (waiting,) = await run_until_wait(graph, run, answers)
    assert waiting == {"type": "gate", "gate": "C1", "phase": "specReview"}
    assert len(port.models.calls) == before  # the journal replayed the reviewer, no new call
    simulator, result = port.screens
    assert all(f.required for f in simulator.inputs())
    assert [a.key for a in result.actions] == ["nueva"]
    rule = next(r for r in port.rules if r.id == "RULE-001")
    assert rule.sme_question == "Decided on a contradiction: Usar el texto del documento"
    assert port.stories is not None
    assert port.stories.origin == "document"
    assert [c.id for c in port.capabilities] == ["CAP-001"]
    assert "2 user stories with 6 acceptance criteria" in store.phases["specReview"]["detail"]
    assert untraced(port.rules, port.screens, await port.load_stories(), await port.load_inputs()) == []


def test_an_element_whose_citation_left_the_inputs_is_untraced() -> None:
    screens, rules, stories = _spec()
    inputs = {f"inputs/{p}": t for p, t in INPUTS.items() if p != "docs/requisitos.md"}
    lost = untraced(rules, screens, stories, inputs)
    assert lost[:6] == [f"RULE-00{i}" for i in range(1, 7)]
    assert "US-002" in lost  # it only links RULE-006
    assert "US-001" not in lost  # its screens still cite Figma


def test_every_operation_of_the_contract_needs_its_endpoint() -> None:
    design = Design.model_validate({
        "context": "loans", "base_package": "com.bank.loans",
        "use_cases": [{"name": "SimulateCredit", "rules": ["RULE-001"], "http_method": "POST", "path": "/simulations"},
                      {"name": "GetSimulation", "rules": ["RULE-006"], "http_method": "GET", "path": "/simulation"}],
    })  # fmt: skip
    controller = '@RestController\npublic class SimulateCreditController {\n  @PostMapping("/simulations")\n}'
    operations, missing = endpoint_missing(design, {"src/x/SimulateCreditController.java": controller})
    assert operations == ["POST /api/loans/simulations", "GET /api/loans/simulation"]
    assert missing == ["GET /api/loans/simulation"]
