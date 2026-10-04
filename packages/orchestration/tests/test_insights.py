"""The deep inventory (ADR-0032) with scripted models: descriptions of units and blocks, the architect's observations
and business flows by scenario are asked only with the run option `deep_inventory`, checked by code (ids that exist,
texts not empty nor too long) and corrected with the concrete problems; without the option no prompt changes."""

import json
import re
import uuid
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from nexti_agents import prompt
from nexti_core.adapters import Edge, Inventory, Node
from nexti_orchestration import AgentSpec, RunContext, compile_graph, executors_for, insights
from nexti_orchestration.extraction import ModelReply
from nexti_orchestration.memory import MemoryStore
from nexti_orchestration.modernization import pick_adapter
from nexti_orchestration.store import Usage

from .test_modernization import PHASES, TEAM, AnsweringModel, MemoryPort, OkProbe, run_until_wait

DESCRIBE, OBSERVE, SCENARIOS = (prompt(p) for p in (insights.DESCRIBE_PROMPT, insights.OBSERVE_PROMPT,
                                                     insights.SCENARIO_PROMPT))  # fmt: skip


class InsightModel(AnsweringModel):
    """The stand-in of test_modernization plus the deep inventory's answers. The first scenario answer points at a
    node that does not exist, so the code must send it back."""

    def __init__(self) -> None:
        super().__init__()
        self.insight_calls: list[tuple[str, str, list[dict[str, str]]]] = []

    async def complete(
        self, agent: str, phase: str, messages: list[dict[str, str]], *, iteration: int = 1, judge: int = 0
    ) -> ModelReply:
        system = messages[0]["content"]
        if system not in (DESCRIBE, OBSERVE, SCENARIOS):
            return await super().complete(agent, phase, messages, iteration=iteration, judge=judge)
        self.insight_calls.append((agent, phase, messages))
        request = messages[1]["content"]
        content: Any
        if system == DESCRIBE:
            ids = re.findall(r"^- (\S+) \(", request.split("Describe these nodes")[1].split("Code (numbered")[0], re.M)
            content = {i: f"Node {i} checks the order and goes on. It reads the tables it needs." for i in ids}
        elif system == OBSERVE:
            content = {"observations": ["The procedure is the only entry point.", "It calls two external units.",
                                        "pg_orden is the only table written."]}  # fmt: skip
        else:
            corrected = len(messages) > 2
            rules = sorted(set(re.findall(r"RULE-\d{3}", request)))
            unit = re.search(r"^- (proc:\S+) \(StoredProcedure", request, re.M)
            node = unit.group(1) if unit else "?"
            content = {"scenarios": [
                {"name": "A company pays an order", "persona": "Company treasurer", "summary": "The order is paid.",
                 "rules": rules[:1], "steps": [{"title": "Check the order", "nodes": [node], "rule": rules[0]},
                                              {"title": "Debit the account",
                                               "nodes": ["table:db_pagos..pg_orden" if corrected else "block:ghost"],
                                               "rule": None}]},
                {"name": "The order does not exist", "persona": "Company treasurer", "summary": "It is rejected.",
                 "rules": [], "steps": [{"title": "Look for the order", "nodes": [node], "rule": None},
                                        {"title": "Reject it", "nodes": [node], "rule": None}]},
            ]}  # fmt: skip
        return ModelReply(json.dumps(content), Usage(model="stand-in", input_tokens=40, output_tokens=30))


class ArtifactPort(MemoryPort):
    def __init__(self) -> None:
        super().__init__()
        self.scripted = InsightModel()
        self.models = self.scripted
        self.artifacts: dict[str, str] = {}

    async def save_artifacts(self, files: dict[str, str], layers: dict[str, str], rules: dict[str, list[str]]) -> None:
        self.artifacts.update(files)

    async def load_artifact(self, path: str) -> str | None:
        return self.artifacts.get(path)


def context(options: dict[str, Any]) -> RunContext:
    team = (*TEAM, AgentSpec("functional-analyst", "Functional analyst", ("ruleReview",), False))
    return RunContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pipeline", "modernization", PHASES, ("C1", "C4"),
                      "balanced", 3, team, options=options)  # fmt: skip


async def to_c1(options: dict[str, Any]) -> ArtifactPort:
    run, store, port = context(options), MemoryStore(), ArtifactPort()
    graph = compile_graph(run, store, executors_for(run, OkProbe(), port), InMemorySaver())  # type: ignore[arg-type]
    waiting = (await run_until_wait(graph, run))[0]
    if waiting["type"] == "questions":
        waiting = (await run_until_wait(graph, run, {q: {"option": "keep"} for q in waiting["question_ids"]}))[0]
    assert waiting == {"type": "gate", "gate": "C1", "phase": "ruleReview"}
    return port


async def test_a_deep_inventory_stores_descriptions_observations_and_checked_scenarios() -> None:
    port = await to_c1({"deep_inventory": True})
    files = await port.source_files()
    inventory = pick_adapter(files).inventory(files)
    expected = {key for unit, blocks in insights.units_of(inventory) for key in [unit.key, *(b.key for b in blocks)]}

    descriptions = json.loads(port.artifacts[insights.DESCRIPTIONS])
    assert descriptions["origin"] == "model"
    assert set(descriptions["descriptions"]) == expected
    assert len(json.loads(port.artifacts[insights.OBSERVATIONS])["observations"]) == 3

    scenarios = json.loads(port.artifacts[insights.SCENARIOS])["scenarios"]
    assert [s["id"] for s in scenarios] == ["scenario:1", "scenario:2"]
    nodes = insights.graph_nodes(inventory)
    assert all(n in nodes for s in scenarios for step in s["steps"] for n in step["nodes"])
    assert scenarios[0]["steps"][1]["nodes"] == ["table:db_pagos..pg_orden"]  # corrected after the feedback
    asked = [c for c in port.scripted.insight_calls if c[2][0]["content"] == SCENARIOS]
    assert len(asked) == 2
    assert "block:ghost" in asked[1][2][-1]["content"]  # the concrete problem went back to the model
    # Who answers what: the legacy analyst describes and observes in classification; the functional analyst, scenarios.
    assert {(a, p) for a, p, m in port.scripted.insight_calls if m[0]["content"] != SCENARIOS} == {
        ("legacy-analyst", "classification")
    }
    assert {(a, p) for a, p, _ in asked} == {("functional-analyst", "ruleReview")}
    # The scenario request carries the descriptions written in classification.
    assert next(iter(descriptions["descriptions"].values())) in asked[0][2][1]["content"]


async def test_without_the_option_no_prompt_or_call_changes() -> None:
    deep, plain = await to_c1({"deep_inventory": True}), await to_c1({})
    assert plain.scripted.insight_calls == []
    assert set(plain.artifacts) == {"inventory/classification.json"}
    # Every other call is the same as with the option: the deep inventory only adds calls.
    assert plain.models.calls == deep.models.calls


INVENTORY = Inventory(
    "sybase-ase",
    nodes=[
        Node("proc:dbo.sp_x", "StoredProcedure", "dbo.sp_x", "sp_x.sp", 1, 12),
        Node("block:dbo.sp_x#1", "Block", "validate", "sp_x.sp", 2, 5, {"phase": "pre"}),
        Node("block:dbo.sp_x#2", "Block", "pay", "sp_x.sp", 6, 10, {"phase": "transaction"}),
        Node("block:dbo.sp_x#3", "Block", "error", "sp_x.sp", 11, 12, {"phase": "error"}),
        Node("table:db..orden", "Table", "orden"),
        Node("stmt:dbo.sp_x#3", "Statement", "select", "sp_x.sp", 3, 3),
    ],
    edges=[
        Edge("proc:dbo.sp_x", "CONTAINS", "block:dbo.sp_x#1"),
        Edge("proc:dbo.sp_x", "CONTAINS", "block:dbo.sp_x#2"),
        Edge("proc:dbo.sp_x", "CONTAINS", "block:dbo.sp_x#3"),
        Edge("block:dbo.sp_x#1", "READS", "table:db..orden"),
        Edge("block:dbo.sp_x#2", "WRITES", "table:db..orden"),
        Edge("block:dbo.sp_x#1", "NEXT", "block:dbo.sp_x#2"),
        Edge("block:dbo.sp_x#2", "ON_ERROR", "block:dbo.sp_x#3"),
    ],
)
SOURCE = "\n".join(f"-- line {n}" for n in range(1, 13))


class Scripted:
    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.requests: list[list[dict[str, str]]] = []

    async def complete(
        self, agent: str, phase: str, messages: list[dict[str, str]], *, iteration: int = 1, judge: int = 0
    ) -> ModelReply:
        self.requests.append(list(messages))
        return ModelReply(json.dumps(self.answers.pop(0)), Usage(model="scripted"))


async def test_one_call_describes_a_unit_and_its_blocks_with_their_connections() -> None:
    good = {"proc:dbo.sp_x": "Pays an order.", "block:dbo.sp_x#1": "Validates the order.",
            "block:dbo.sp_x#2": "Debits the account.", "block:dbo.sp_x#3": "Returns the error."}  # fmt: skip
    model = Scripted({**good, "block:dbo.sp_x#9": "Invented.", "block:dbo.sp_x#3": ""}, good)
    unit, blocks = insights.units_of(INVENTORY)[0]
    assert [b.key for b in blocks] == ["block:dbo.sp_x#1", "block:dbo.sp_x#2", "block:dbo.sp_x#3"]
    found = await insights.describe(model, "legacy-analyst", "classification", INVENTORY, SOURCE, unit, blocks,
                                    max_iterations=3)  # fmt: skip
    assert found.value == good
    assert found.problems == []
    request = model.requests[0][1]["content"]
    assert "next: block:dbo.sp_x#2; reads: table:db..orden" in request
    assert "on_error: block:dbo.sp_x#3" in request
    assert "    6  -- line 6" in request  # numbered lines
    feedback = model.requests[1][-1]["content"]
    assert "block:dbo.sp_x#9 is not one of the node ids" in feedback
    assert "block:dbo.sp_x#3: the description is empty" in feedback


async def test_when_the_attempts_run_out_the_valid_part_is_kept() -> None:
    unit, blocks = insights.units_of(INVENTORY)[0]
    answer = {"proc:dbo.sp_x": "Pays an order.", "block:dbo.sp_x#1": "x" * 2000}
    model = Scripted(answer, answer)
    found = await insights.describe(model, "legacy-analyst", "classification", INVENTORY, SOURCE, unit, blocks,
                                    max_iterations=2)  # fmt: skip
    assert found.value == {"proc:dbo.sp_x": "Pays an order."}
    assert any("2000 characters" in p for p in found.problems)
    assert len(model.requests) == 2


async def test_observations_are_between_three_and_eight_short_texts() -> None:
    model = Scripted({"observations": ["Only one."]}, {"observations": ["One.", "Two.", "Three."]})
    found = await insights.observe(model, "legacy-analyst", "classification",
                                   insights.summary_of(INVENTORY, {"business": 3}, {}), max_iterations=3)  # fmt: skip
    assert found.value == ["One.", "Two.", "Three."]
    assert "between 3 and 8 observations, not 1" in model.requests[1][-1]["content"]
    summary = model.requests[0][1]["content"]
    assert "proc:dbo.sp_x (entry point)" in summary
    assert "block:dbo.sp_x#2 'pay' lines 6-10, phase transaction" in summary


def test_scenarios_must_use_known_nodes_and_rules_in_order() -> None:
    nodes = insights.graph_nodes(INVENTORY)
    assert "stmt:dbo.sp_x#3" not in nodes  # statements are not drawn
    step = {"title": "Validate", "nodes": ["block:dbo.sp_x#1"], "rule": "RULE-001"}
    paying = {"title": "Pay", "nodes": ["block:dbo.sp_x#2", "table:db..orden"], "rule": None}
    good = {"name": "Pay", "persona": "Clerk", "summary": "Paid.", "rules": [], "steps": [step, paying]}
    bad = {"name": "Bad", "persona": "", "summary": "x", "rules": ["RULE-404"],
           "steps": [{"title": "Only", "nodes": ["stmt:dbo.sp_x#3"], "rule": "RULE-009"}]}  # fmt: skip
    valid, problems = insights.check_scenarios(json.dumps({"scenarios": [good, bad]}), nodes, ["RULE-001"])
    assert [s["name"] for s in valid] == ["Pay"]
    assert valid[0]["rules"] == ["RULE-001"]  # the rules of its steps are the scenario's too
    assert [s["title"] for s in valid[0]["steps"]] == ["Validate", "Pay"]
    assert set(problems) == {
        "scenario 2 'Bad': 'persona' is empty",
        "scenario 2 'Bad': unknown rules RULE-404",
        "scenario 2 'Bad': it needs at least two steps, in the order they happen",
        "scenario 2 'Bad', step 1: these node ids are not in the graph: stmt:dbo.sp_x#3",
        "scenario 2 'Bad', step 1: unknown rule RULE-009",
    }
    _, few = insights.check_scenarios(json.dumps({"scenarios": [good]}), nodes, ["RULE-001"])
    assert few == ["propose between 2 and 6 scenarios, not 1"]
