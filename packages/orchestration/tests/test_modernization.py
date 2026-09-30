"""The analysis half of the modernization flow on the fictitious application (spec 6.1): a real pipeline goes from
the preflight through inventory, domains, classification, rule extraction with review and user stories to gate C1.
The model is a stand-in that answers from what it is asked (citing lines of the slice it received); the reviewers
disagree on one P0 rule, which becomes a question for a person."""

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from nexti_core.adapters import Inventory, SourceFile
from nexti_core.composition.loader import core_data, flows
from nexti_core.spec.model import Rule
from nexti_orchestration import AgentSpec, Check, PhaseSpec, RunContext, compile_graph, executors_for, thread_config
from nexti_orchestration.extraction import ModelReply
from nexti_orchestration.graph import pending_interrupts
from nexti_orchestration.memory import MemoryStore
from nexti_orchestration.modernization import domain_map
from nexti_orchestration.store import Usage
from nexti_orchestration.stories import Stories

ROOT = Path(__file__).resolve().parents[3]
SOURCE = (ROOT / "packages/adapters/source/sybase/tests/fixtures/pago_orden/sp_pago_orden.sp").read_text(
    encoding="utf-8"
)
PHASES = tuple(
    PhaseSpec(p.key, p.gate, p.agent_required) for f in flows(core_data()) if f.key == "modernization" for p in f.phases
)
TEAM = (
    AgentSpec("legacy-analyst", "Legacy analyst", ("inventory", "domains", "classification"), False),
    AgentSpec("rules-extractor", "Rules extractor", ("ruleExtraction",), False),
    AgentSpec("rules-verifier", "Rules verifier", ("ruleExtraction", "consolidation"), True),
)


class AnsweringModel:
    """Answers like the agents would, from the request: rules citing the first lines of the slice, reviews, stories."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int, int]] = []

    async def complete(
        self, agent: str, phase: str, messages: list[dict[str, str]], *, iteration: int = 1, judge: int = 0
    ) -> ModelReply:
        self.calls.append((agent, phase, iteration, judge))
        user = messages[-1]["content"] if messages[-1]["role"] == "user" else messages[1]["content"]
        request = messages[1]["content"]
        content: dict[str, Any]
        if agent == "rules-extractor" and "Slice:" in request:
            unit = re.search(r"Unit: (\S+)", request)
            lines = [int(n) for n in re.findall(r"^\s*(\d+)  ", request.split("Slice:")[1], re.M)]
            first = lines[0]
            content = {"rules": [{
                "name": f"Behaviour at line {first} of {unit.group(1) if unit else 'the slice'}",
                "category": "validation", "priority": "P0" if first < 40 else "P1",
                "statement": f"The procedure checks the condition written at line {first} before going on.",
                "sources": [{"file": "sp_pago_orden.sp", "line_start": first, "line_end": first}],
            }]}  # fmt: skip
        elif agent == "rules-verifier":
            disagree = "P0" in user and judge == 1
            content = {"supported": not disagree, "problems": ["the value differs"] if disagree else [],
                       "corrected_statement": None}  # fmt: skip
        else:  # stories
            ids = sorted(set(re.findall(r"RULE-\d{3}", request)))
            content = {"stories": [{
                "feature": "Pay an order", "title": "Pay a company order", "narrative": "As a company, I want to pay.",
                "criteria": ["Scenario: Pay\n  Given a pending order\n  When it is paid\n  Then it is marked A"],
                "links": ids, "priority": "P0", "estimate": 5,
            }]}  # fmt: skip
        return ModelReply(json.dumps(content), Usage(model="stand-in", input_tokens=50, output_tokens=20))


class MemoryPort:
    def __init__(self) -> None:
        self.models = AnsweringModel()
        self.inventory: Inventory | None = None
        self.domains: dict[str, list[str]] = {}
        self.rules: list[Rule] = []
        self.stories: Stories | None = None

    async def source_files(self) -> list[SourceFile]:
        return [SourceFile("sp_pago_orden.sp", SOURCE)]

    async def save_inventory(self, inventory: Inventory) -> None:
        self.inventory = inventory

    async def save_domains(self, domains: dict[str, list[str]]) -> None:
        self.domains = domains

    async def save_rules(self, rules: Sequence[Rule]) -> None:
        self.rules = list(rules)

    async def load_rules(self) -> list[Rule]:
        return list(self.rules)

    async def save_stories(self, stories: Stories) -> None:
        self.stories = stories


class OkProbe:
    async def _ok(self) -> Check:
        return Check("x", True, "ok")

    inputs = secrets = repository = models = budget = _ok

    async def archives(self) -> Mapping[str, bytes]:
        return {}


def context() -> RunContext:
    return RunContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pipeline", "modernization", PHASES, ("C1", "C4"),
                      "balanced", 3, TEAM)  # fmt: skip


async def run_until_wait(graph: Any, run: RunContext, value: Any = None) -> list[dict[str, Any]]:
    await graph.ainvoke(Command(resume=value) if value is not None else {}, thread_config(run))
    return await pending_interrupts(graph, run)


async def test_a_real_pipeline_reaches_c1_with_rules_stories_and_a_plan() -> None:
    run, store, port = context(), MemoryStore(), MemoryPort()
    graph = compile_graph(run, store, executors_for(run, OkProbe(), port), InMemorySaver())  # type: ignore[arg-type]

    (waiting,) = await run_until_wait(graph, run)
    # P0 rules: the second judge disagrees -> one question each, asked together, before the rules are saved.
    assert waiting["type"] == "questions"
    questions = list(store.questions.values())
    assert questions
    assert len(waiting["question_ids"]) == len(questions)
    assert {q["question"].reason for q in questions} == {"judgesDisagree"}
    assert {q["phase"] for q in questions} == {"ruleExtraction"}
    assert port.rules == []  # nothing saved while the question is open
    before = len(port.models.calls)

    (waiting,) = await run_until_wait(graph, run, {qid: {"option": "keep"} for qid in waiting["question_ids"]})
    assert waiting == {"type": "gate", "gate": "C1", "phase": "ruleReview"}
    # Resuming after the answer did not call the extractor again (the journal replayed it).
    again = [c for c in port.models.calls[before:] if c[1] == "ruleExtraction"]
    assert again == []

    assert port.inventory is not None
    assert port.inventory.metrics["procedures"] == 1
    assert port.domains == {"pg_orden": ["proc:dbo.sp_pago_orden"]}
    assert port.rules
    assert [r.id for r in port.rules] == [f"RULE-{i:03d}" for i in range(1, len(port.rules) + 1)]
    kept_p0 = [r for r in port.rules if r.priority == "P0"]
    assert kept_p0
    assert all(r.confidence == "low" for r in kept_p0)
    assert port.stories is not None
    assert port.stories.waves == [["US-001"]]
    assert {s["status"] for s in store.phases.values() if s} >= {"succeeded"}
    assert store.phases["classification"]["detail"].startswith("statements:")
    # The rules extractor writes the stories when the team has no functional analyst.
    assert ("rules-extractor", "ruleReview", 1, 0) in port.models.calls

    # After C1 the flow goes on to the UI phase (no screens) and waits in design, available from the next steps.
    (waiting,) = await run_until_wait(graph, run, {"decision": "approved"})
    assert waiting == {"type": "phaseUnavailable", "phase": "design"}
    assert store.phases["ui"]["status"] == "succeeded"


def test_procedures_writing_the_same_table_form_one_domain() -> None:
    from nexti_core.adapters import Edge, Node

    inventory = Inventory("t", nodes=[
        Node("proc:alta", "StoredProcedure", "alta"), Node("proc:pago", "StoredProcedure", "pago"),
        Node("proc:reporte", "StoredProcedure", "reporte"),
        Node("proc:ext", "StoredProcedure", "ext", properties={"external": True}),
    ], edges=[
        Edge("proc:alta", "WRITES", "table:db..orden"), Edge("proc:pago", "WRITES", "table:db..orden"),
        Edge("proc:reporte", "WRITES", "table:db..reporte"),
    ])  # fmt: skip
    assert domain_map(inventory) == {"orden": ["proc:alta", "proc:pago"], "reporte": ["proc:reporte"]}
