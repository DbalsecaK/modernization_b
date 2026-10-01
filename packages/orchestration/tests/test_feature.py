"""Flow 2, analysis half (spec 7.2 phases 1-3, ADR-0018), on the fictitious "Simulador de crédito": code checks every
citation, the Gherkin and the coverage of what the analyst answers, and finds the gaps of 7.3; each gap becomes a
question whose recommended answer is applied when a person answers."""

import json
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from nexti_core.composition.loader import core_data, flows
from nexti_core.spec.design import Design
from nexti_core.spec.model import Capability, Rule
from nexti_core.spec.screens import ScreenSpec
from nexti_ingest import figma
from nexti_ingest.documents import Document
from nexti_orchestration import AgentSpec, Check, PhaseSpec, RunContext, compile_graph, executors_for, thread_config
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
from nexti_orchestration.graph import pending_interrupts
from nexti_orchestration.memory import MemoryStore
from nexti_orchestration.model import Answer
from nexti_orchestration.store import Usage
from nexti_orchestration.stories import Stories

# -- the fictitious example of Flow 2, "Simulador de crédito", as the inputs and as an analyst would normalize it --
ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "packages/ingest/tests/fixtures/simulador_credito"
FIGMA_FILE = "FicSimCred2026abc"
FIGMA: dict[str, Any] = json.loads((EXAMPLE / "figma" / f"{FIGMA_FILE}.json").read_text(encoding="utf-8"))
REQUIREMENTS = (EXAMPLE / "requisitos.md").read_text(encoding="utf-8")
STORIES = (EXAMPLE / "historias.md").read_text(encoding="utf-8")
INPUTS = {
    "docs/requisitos.md": REQUIREMENTS,
    "docs/historias.md": STORIES,
    f"figma/{FIGMA_FILE}": figma.render(FIGMA_FILE, FIGMA),
    f"figma/{FIGMA_FILE}.json": json.dumps(FIGMA, ensure_ascii=False),
}


def line(path: str, text: str) -> int:
    """The line of an input that contains a text (1-based)."""
    return next(n for n, value in enumerate(INPUTS[path].split("\n"), start=1) if text in value)


def cite(path: str, first: str, last: str | None = None) -> str:
    start = line(path, first)
    end = line(path, last) if last else start
    return f"{path}:{start}-{end}"


def criteria(story: str) -> list[str]:
    """The Gherkin scenarios of a story of historias.md, as written there."""
    block = STORIES.split(f"## {story}")[1].split("\n## ")[0]
    scenarios = block.split("Escenario:")[1:]
    return ["Escenario:" + s.rstrip().split("\n\n")[0] for s in scenarios]


REQ = "docs/requisitos.md"
FIG = f"figma/{FIGMA_FILE}"
DECIMAL = "decimal(12,2,signed)"


def normalized() -> dict[str, Any]:
    """What the functional analyst answers for the example (every citation points to real lines)."""
    return {
        "capabilities": [{"id": "CAP-001", "name": "Simular un crédito de consumo", "actor": "Cliente",
                          "goal": "Conocer la cuota antes de solicitar", "priority": "P0",
                          "rules": ["RULE-001", "RULE-002", "RULE-003", "RULE-004", "RULE-005", "RULE-006"],
                          "sources": [cite(REQ, "## 1. Objetivo", "mensual y el total a pagar.")]}],
        "rules": [
            {"id": "RULE-001", "name": "Monto dentro del rango", "category": "validation", "priority": "P0",
             "statement": "El monto debe estar entre 1000.00 y 50000.00 USD, ambos incluidos.",
             "inputs": [{"name": "monto", "type": DECIMAL}],
             "scenarios": ["Given un monto de 500.00 When simulo Then se rechaza con 'El monto debe estar entre "
                           "1.000 y 50.000'"], "sources": [cite(REQ, "RN-1.", "rechaza con el mensaje \"El monto")]},
            {"id": "RULE-002", "name": "Plazo dentro del rango", "category": "validation", "priority": "P0",
             "statement": "El plazo es un número entero de meses entre 6 y 60, ambos incluidos.",
             "inputs": [{"name": "plazo", "type": "integer(32,signed)"}],
             "scenarios": ["Given un plazo de 72 When simulo Then se rechaza"],
             "sources": [cite(REQ, "RN-2.", "mensaje \"El plazo debe")]},
            {"id": "RULE-003", "name": "Tasa según el plazo", "category": "calculation", "priority": "P0",
             "statement": "La tasa nominal anual depende del plazo: 12.00, 14.50 o 16.00 %.",
             "scenarios": ["Given un plazo de 24 When simulo Then la tasa es 14.50"],
             "sources": [cite(REQ, "RN-3.", "meses, 16.00 %.")]},
            {"id": "RULE-004", "name": "Cuota por sistema francés", "category": "calculation", "priority": "P0",
             "statement": "La cuota mensual se calcula con el sistema francés y se redondea a 2 decimales.",
             "scenarios": ["Given 10000.00 a 12 meses When simulo Then la cuota es 888.49"],
             "sources": [cite(REQ, "RN-4.", "mitad hacia arriba.")]},
            {"id": "RULE-005", "name": "Total a pagar", "category": "calculation", "priority": "P1",
             "statement": "El total a pagar es la cuota redondeada por el plazo, con 2 decimales.",
             "scenarios": ["Given cuota 888.49 a 12 meses Then el total es 10661.88"],
             "sources": [cite(REQ, "RN-5.")]},
            {"id": "RULE-006", "name": "Guardar la simulación", "category": "lifecycle", "priority": "P1",
             "statement": "Cada simulación aceptada se guarda con un número correlativo para auditoría.",
             "scenarios": ["Given una simulación aceptada When se guarda Then tiene el número 1"],
             "sources": [cite(REQ, "RN-6.", "Una simulación rechazada no se guarda.")]},
        ],
        "screens": [
            {"id": "SCR-SIMULADOR", "name": "Simulador",
             "fields": [{"name": "monto", "kind": "input", "label": "Monto (USD)", "type": DECIMAL, "length": 12},
                        {"name": "plazo", "kind": "input", "label": "Plazo (meses)", "type": "integer(32,signed)",
                         "length": 2}],
             "actions": [{"key": "calcular", "label": "Calcular", "target": "SCR-RESULTADO"}],
             "navigation_out": ["SCR-RESULTADO"], "sources": [cite(FIG, 'FRAME "Simulador"', 'Calcular texto')]},
            {"id": "SCR-RESULTADO", "name": "Resultado",
             "fields": [{"name": "tasa", "kind": "output", "label": "Tasa anual", "type": "decimal(5,2,signed)",
                         "length": 6},
                        {"name": "cuota", "kind": "output", "label": "Cuota mensual", "type": DECIMAL, "length": 12},
                        {"name": "total", "kind": "output", "label": "Total a pagar", "type": DECIMAL, "length": 12}],
             "actions": [{"key": "nueva", "label": "Nueva simulación", "target": "SCR-SIMULADOR"},
                         {"key": "descargar", "label": "Descargar PDF"}],
             "navigation_out": ["SCR-SIMULADOR"], "sources": [cite(FIG, 'FRAME "Resultado"', "Descargar PDF texto")]},
        ],
        "stories": [
            {"feature": "Simulación", "title": "Simular la cuota de un crédito",
             "narrative": "Como cliente del banco quiero ingresar el monto y el plazo para conocer la cuota mensual.",
             "criteria": criteria("HU-1"),
             "links": ["RULE-001", "RULE-002", "RULE-003", "RULE-004", "RULE-005", "SCR-SIMULADOR", "SCR-RESULTADO"],
             "priority": "P0", "estimate": 5},
            {"feature": "Auditoría", "title": "Guardar cada simulación",
             "narrative": "Como oficial de cumplimiento quiero que cada simulación aceptada quede guardada.",
             "criteria": criteria("HU-2"), "links": ["RULE-006"], "priority": "P1", "estimate": 3},
        ],
    }  # fmt: skip


class OkProbe:
    async def _ok(self) -> Check:
        return Check("x", True, "ok")

    inputs = secrets = repository = models = budget = _ok

    async def archives(self) -> Mapping[str, bytes]:
        return {}


async def run_until_wait(graph: Any, run: RunContext, value: Any = None) -> list[dict[str, Any]]:
    await graph.ainvoke(Command(resume=value) if value is not None else {}, thread_config(run))
    return await pending_interrupts(graph, run)


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
