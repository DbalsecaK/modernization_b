"""Model-written reading aids of the deep inventory (ADR-0032, spec 4.1 and 5.2.1), only with the run option
`deep_inventory`: a description of every unit and block, the architect's observations on the inventory and the
business flows as scenarios over graph nodes and rules.

They help a person read the graph; they are not evidence (the verdict is still computed by code). Every answer is
checked by code (the ids it uses exist, the texts are not empty and not too long) and the concrete problems go back to
the model (do -> verify -> correct, 11.1). When the attempts run out the valid part is kept and the rest is dropped:
a missing description never stops a run. Every model call goes through a ModelCaller (CLAUDE.md rule 2).
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from nexti_agents import prompt
from nexti_core.adapters import Inventory, Node, SliceView
from nexti_core.spec.model import Rule
from nexti_orchestration.extraction import ModelCaller, ReplyError, cut_message, numbered, parse_json
from nexti_orchestration.store import Usage

OPTION = "deep_inventory"
DESCRIPTIONS = "inventory/descriptions.json"
OBSERVATIONS = "inventory/observations.json"
SCENARIOS = "inventory/scenarios.json"
DESCRIBE_PROMPT = "legacy-analyst-describe"
OBSERVE_PROMPT = "legacy-analyst-observations"
SCENARIO_PROMPT = "functional-analyst-scenarios"
UNIT_LABELS = ("StoredProcedure", "Program")
BLOCK_LABELS = ("Block", "Paragraph")  # COBOL paragraphs already are the blocks of a program (ADR-0032)
HIDDEN_LABELS = ("Statement", "Field", "Column")  # not drawn as nodes a scenario can point at
FLOW_EDGES = ("NEXT", "GOTO", "ON_ERROR", "PERFORMS")
MAX_DESCRIPTION = 900  # characters (the prompt asks for 600)
MAX_OBSERVATION = 400
MIN_OBSERVATIONS, MAX_OBSERVATIONS = 3, 8
MIN_SCENARIOS, MAX_SCENARIOS = 2, 6
MAX_BLOCKS_PER_CALL = 30
WHOLE_UNIT_LINES = 400  # a unit up to this size is shown whole; a longer one, block by block (each one capped)
MAX_EXCERPT_LINES = 600
MAX_LISTED = 15


def enabled(options: Mapping[str, Any]) -> bool:
    return options.get(OPTION) is True


@dataclass
class Answer:
    """What a model conversation left: the valid value, the problems of the last answer (empty when it passed) and
    the usage of every call."""

    value: Any
    problems: list[str] = field(default_factory=list)
    usage: list[Usage] = field(default_factory=list)


async def converse(
    caller: ModelCaller, agent: str, phase: str, messages: list[dict[str, str]],
    check: Callable[[str], tuple[Any, list[str]]], *, max_iterations: int,
) -> Answer:  # fmt: skip
    """Ask, check by code, send the problems back; after `max_iterations` answers the valid part of the last one."""
    messages = list(messages)
    answer = Answer(None)
    for iteration in range(1, max_iterations + 1):
        reply = await caller.complete(agent, phase, messages, iteration=iteration)
        answer.usage.append(reply.usage)
        if reply.cut_at:  # asking again gives the same cut answer: keep what there is and say why it stopped
            answer.problems = [cut_message(agent, reply.cut_at)]
            return answer
        try:
            value, problems = check(reply.content)
        except ReplyError as exc:
            value, problems = None, [str(exc)]
        if value is not None:
            answer.value = value
        answer.problems = problems
        if not problems:
            return answer
        messages += [
            {"role": "assistant", "content": reply.content},
            {"role": "user", "content": "Your answer has these problems; fix them and answer again:\n- "
                                        + "\n- ".join(problems)},
        ]  # fmt: skip
    return answer


# -- the inventory as the agents read it ----------------------------------------------------------------------------
def units_of(inventory: Inventory) -> list[tuple[Node, list[Node]]]:
    """The units of the inputs (external ones are only called) with their blocks, in source order."""
    nodes = {n.key: n for n in inventory.nodes}
    children: dict[str, list[Node]] = {}
    for edge in inventory.edges:
        child = nodes.get(edge.target)
        if str(edge.type) == "CONTAINS" and child is not None and str(child.label) in BLOCK_LABELS:
            children.setdefault(edge.source, []).append(child)
    units = [n for n in inventory.nodes if str(n.label) in UNIT_LABELS and not n.properties.get("external")]
    order = sorted(units, key=lambda n: (n.file or "", n.line_start or 0, n.key))
    return [(u, sorted(children.get(u.key, []), key=lambda b: (b.line_start or 0, b.key))) for u in order]


def _lines(node: Node) -> str:
    return f"lines {node.line_start}-{node.line_end}" if node.line_start else "no lines"


def connections(inventory: Inventory, key: str) -> str:
    """The node's outgoing relations in words: tables read and written, procedures called, flow between blocks."""
    found: dict[str, list[str]] = {}
    for edge in inventory.edges:
        if edge.source == key and str(edge.type) != "CONTAINS" and str(edge.type) != "DECLARES":
            found.setdefault(str(edge.type).lower(), []).append(edge.target)
    if not found:
        return "none"
    parts = []
    for kind, targets in sorted(found.items()):
        unique = sorted(set(targets))
        more = f" (+{len(unique) - MAX_LISTED} more)" if len(unique) > MAX_LISTED else ""
        parts.append(f"{kind}: {', '.join(unique[:MAX_LISTED])}{more}")
    return "; ".join(parts)


def _excerpt(source: str, unit: Node, blocks: Sequence[Node]) -> str:
    start, end = unit.line_start or 1, unit.line_end or len(source.splitlines())
    if end - start + 1 <= WHOLE_UNIT_LINES or not blocks:
        ranges = [(start, min(end, start + MAX_EXCERPT_LINES - 1))]
    else:  # a long unit: its header and the first lines of each block
        cap = max(15, MAX_EXCERPT_LINES // (len(blocks) + 1))
        first = min(b.line_start or start for b in blocks)
        ranges = [(start, min(first - 1, start + cap - 1))] if first > start else []
        ranges += [((b.line_start or start), min(b.line_end or start, (b.line_start or start) + cap - 1))
                   for b in blocks]  # fmt: skip
    return numbered(source, SliceView(unit.key, unit.file or "", tuple(r for r in ranges if r[0] <= r[1])))


def check_descriptions(content: str, expected: Sequence[str]) -> tuple[dict[str, str], list[str]]:
    data = parse_json(content)
    if isinstance(data, dict) and isinstance(data.get("descriptions"), dict):
        data = data["descriptions"]
    if not isinstance(data, dict):
        raise ReplyError('the answer must be one JSON object {"<node id>": "<description>"}')
    valid: dict[str, str] = {}
    problems = []
    for key, text in data.items():
        if key not in expected:
            problems.append(f"{key} is not one of the node ids you were given")
        elif not isinstance(text, str) or not text.strip():
            problems.append(f"{key}: the description is empty")
        elif len(text) > MAX_DESCRIPTION:
            problems.append(f"{key}: the description has {len(text)} characters; keep it under 600")
        else:
            valid[key] = " ".join(text.split())
    missing = [k for k in expected if k not in data]
    if missing:
        problems.append(f"these nodes have no description: {', '.join(missing)}")
    return valid, problems


def _check_descriptions_of(expected: Sequence[str], content: str) -> tuple[dict[str, str], list[str]]:
    return check_descriptions(content, expected)


async def describe(
    caller: ModelCaller, agent: str, phase: str, inventory: Inventory, source: str, unit: Node,
    blocks: Sequence[Node], *, max_iterations: int,
) -> Answer:  # fmt: skip
    """The descriptions of one unit and its blocks: one call per unit (blocks in batches when there are many)."""
    batches = [list(blocks[i : i + MAX_BLOCKS_PER_CALL]) for i in range(0, len(blocks), MAX_BLOCKS_PER_CALL)] or [[]]
    result = Answer({})
    for number, batch in enumerate(batches):
        expected = ([unit.key] if number == 0 else []) + [b.key for b in batch]
        listed = [f"- {unit.key} (the whole {unit.label}, {_lines(unit)}); connections: "
                  f"{connections(inventory, unit.key)}"] if number == 0 else []  # fmt: skip
        listed += [f"- {b.key} (block '{b.name}', {_lines(b)}, phase {b.properties.get('phase') or 'n/a'}); "
                   f"connections: {connections(inventory, b.key)}" for b in batch]  # fmt: skip
        request = (
            f"File: {unit.file}\nUnit: {unit.name} ({unit.label}, {_lines(unit)}), {len(blocks)} block(s)\n\n"
            f"Describe these nodes (answer with exactly these ids):\n" + "\n".join(listed)
            + f"\n\nCode (numbered lines):\n{_excerpt(source, unit, batch)}"
        )  # fmt: skip
        messages = [{"role": "system", "content": prompt(DESCRIBE_PROMPT)}, {"role": "user", "content": request}]
        answer = await converse(caller, agent, phase, messages,
                                partial(_check_descriptions_of, expected),
                                max_iterations=max_iterations)  # fmt: skip
        result.value.update(answer.value or {})
        result.problems += answer.problems
        result.usage += answer.usage
    return result


def summary_of(inventory: Inventory, classification: Mapping[str, int], descriptions: Mapping[str, str]) -> str:
    """The inventory as the architect reads it: units and blocks, tables, external calls, entry points, counts."""
    units = units_of(inventory)
    nodes = {n.key: n for n in inventory.nodes}
    callers = {e.target for e in inventory.edges if str(e.type) == "CALLS"}
    lines = [f"Metrics: {json.dumps(inventory.metrics, sort_keys=True)}",
             f"Statement classification: {json.dumps(dict(classification), sort_keys=True)}", "", "Units:"]  # fmt: skip
    for unit, blocks in units:
        entry = " (entry point)" if unit.key not in callers else ""
        lines.append(f"- {unit.key}{entry}: {_lines(unit)}, {len(blocks)} block(s); {connections(inventory, unit.key)}")
        if unit.key in descriptions:
            lines.append(f"  {descriptions[unit.key]}")
        for block in blocks[:40]:
            phase = block.properties.get("phase") or "n/a"
            lines.append(f"  - {block.key} '{block.name}' {_lines(block)}, phase {phase}")
        if len(blocks) > 40:
            lines.append(f"  - ... {len(blocks) - 40} more block(s)")
    readers: dict[str, set[str]] = {}
    writers: dict[str, set[str]] = {}
    for edge in inventory.edges:
        if str(edge.type) in ("READS", "WRITES"):
            (readers if str(edge.type) == "READS" else writers).setdefault(edge.target, set()).add(edge.source)
    lines += ["", "Tables:"]
    for table in sorted((n for n in inventory.nodes if str(n.label) in ("Table", "File")), key=lambda n: n.key):
        known = table.properties.get("schemaKnown", table.properties.get("schema_known"))
        schema = "" if known is None else (", schema known" if known else ", schema unknown (only used by the code)")
        lines.append(f"- {table.key}: read by {len(readers.get(table.key, ()))}, written by "
                     f"{len(writers.get(table.key, ()))}{schema}")  # fmt: skip
    external = sorted(n.key for n in nodes.values() if str(n.label) in UNIT_LABELS and n.properties.get("external"))
    lines += ["", f"External units (called, not in the inputs): {', '.join(external) or 'none'}"]
    return "\n".join(lines)


def check_observations(content: str) -> tuple[list[str], list[str]]:
    data = parse_json(content)
    items = data.get("observations") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ReplyError('the answer must be one JSON object {"observations": ["...", ...]}')
    valid: list[str] = []
    problems = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, str) or not item.strip():
            problems.append(f"observation {index} is empty or not a text")
        elif len(item) > MAX_OBSERVATION:
            problems.append(f"observation {index} has {len(item)} characters; keep it under 300")
        else:
            valid.append(" ".join(item.split()))
    if not MIN_OBSERVATIONS <= len(items) <= MAX_OBSERVATIONS:
        problems.append(f"write between {MIN_OBSERVATIONS} and {MAX_OBSERVATIONS} observations, not {len(items)}")
    return valid[:MAX_OBSERVATIONS], problems


async def observe(caller: ModelCaller, agent: str, phase: str, summary: str, *, max_iterations: int) -> Answer:
    messages = [{"role": "system", "content": prompt(OBSERVE_PROMPT)},
                {"role": "user", "content": f"Inventory summary:\n{summary}"}]  # fmt: skip
    answer = await converse(caller, agent, phase, messages, check_observations, max_iterations=max_iterations)
    if answer.value is None:
        answer.value = []
    return answer


# -- business flows as scenarios (4.1) -------------------------------------------------------------------------------
def graph_nodes(inventory: Inventory) -> dict[str, Node]:
    """The nodes a scenario step may point at: units, blocks, tables, files... (not statements or fields)."""
    return {n.key: n for n in inventory.nodes if str(n.label) not in HIDDEN_LABELS}


def _text(item: Mapping[str, Any], key: str, limit: int) -> str | None:
    value = item.get(key)
    return " ".join(value.split())[:limit] if isinstance(value, str) and value.strip() else None


def check_scenarios(content: str, nodes: Mapping[str, Node], rules: Sequence[str]) -> tuple[list[dict[str, Any]],
                                                                                            list[str]]:  # fmt: skip
    data = parse_json(content)
    items = data.get("scenarios") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ReplyError('the answer must be one JSON object {"scenarios": [...]}')
    known = set(rules)
    valid: list[dict[str, Any]] = []
    problems: list[str] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            problems.append(f"scenario {index} is not an object")
            continue
        name = _text(item, "name", 160)
        label = f"scenario {index} '{name or 'no name'}'"
        found: list[str] = []
        persona, summary = _text(item, "persona", 120), _text(item, "summary", 800)
        found += [f"{label}: '{key}' is empty" for key, value in (("name", name), ("persona", persona),
                                                                   ("summary", summary)) if value is None]  # fmt: skip
        cited = item.get("rules") or []
        if not isinstance(cited, list):
            cited = []
            found.append(f"{label}: 'rules' must be a list of rule ids")
        unknown_rules = sorted({str(r) for r in cited} - known)
        if unknown_rules:
            found.append(f"{label}: unknown rules {', '.join(unknown_rules)}")
        steps = item.get("steps")
        if not isinstance(steps, list) or len(steps) < 2:
            found.append(f"{label}: it needs at least two steps, in the order they happen")
            steps = steps if isinstance(steps, list) else []
        clean_steps = []
        for number, step in enumerate(steps, start=1):
            where = f"{label}, step {number}"
            if not isinstance(step, dict):
                found.append(f"{where} is not an object")
                continue
            title = _text(step, "title", 200)
            if title is None:
                found.append(f"{where}: the title is empty")
            ids = step.get("nodes")
            if not isinstance(ids, list) or not ids:
                found.append(f"{where}: 'nodes' must list at least one graph node id")
                ids = []
            missing = [str(i) for i in ids if str(i) not in nodes]
            if missing:
                found.append(f"{where}: these node ids are not in the graph: {', '.join(missing)}")
            rule = step.get("rule")
            if rule is not None and str(rule) not in known:
                found.append(f"{where}: unknown rule {rule}")
            clean_steps.append({"title": title or "", "nodes": [str(i) for i in ids],
                                "rule": str(rule) if rule is not None else None})  # fmt: skip
        if found:
            problems += found
            continue
        step_rules = [s["rule"] for s in clean_steps if s["rule"]]
        valid.append({"id": f"scenario:{len(valid) + 1}", "name": name, "persona": persona, "summary": summary,
                      "rules": sorted({str(r) for r in cited} | set(step_rules)), "steps": clean_steps})  # fmt: skip
    if not MIN_SCENARIOS <= len(items) <= MAX_SCENARIOS:
        problems.append(f"propose between {MIN_SCENARIOS} and {MAX_SCENARIOS} scenarios, not {len(items)}")
    return valid[:MAX_SCENARIOS], problems


def scenario_request(inventory: Inventory, rules: Sequence[Rule], descriptions: Mapping[str, str]) -> str:
    lines = ["Business rules:"]
    for rule in rules:
        cited = ", ".join(f"{s.file}:{s.line_start}-{s.line_end}" for s in rule.sources)
        lines.append(f"- {rule.id} [{rule.priority}] {rule.name}: {rule.statement} (cites {cited})")
    lines += ["", "Graph nodes (id, kind, lines):"]
    for unit, blocks in units_of(inventory):
        lines.append(f"- {unit.key} ({unit.label}, {unit.file}, {_lines(unit)})")
        if unit.key in descriptions:
            lines.append(f"  {descriptions[unit.key]}")
        for block in blocks:
            lines.append(f"  - {block.key} (block '{block.name}', {_lines(block)}, phase "
                         f"{block.properties.get('phase') or 'n/a'})")  # fmt: skip
            if block.key in descriptions:
                lines.append(f"    {descriptions[block.key]}")
    others = sorted(k for k, n in graph_nodes(inventory).items()
                    if str(n.label) not in UNIT_LABELS + BLOCK_LABELS or n.properties.get("external"))  # fmt: skip
    lines += [f"- {key}" for key in others]
    flow = [f"- {e.source} {e.type} {e.target}" for e in inventory.edges if str(e.type) in FLOW_EDGES]
    lines += ["", "How the blocks follow each other:", *(flow or ["- (no blocks: the units run top to bottom)"])]
    return "\n".join(lines)


async def propose_scenarios(
    caller: ModelCaller, agent: str, phase: str, inventory: Inventory, rules: Sequence[Rule],
    descriptions: Mapping[str, str], *, max_iterations: int,
) -> Answer:  # fmt: skip
    nodes = graph_nodes(inventory)
    ids = [r.id for r in rules]
    messages = [{"role": "system", "content": prompt(SCENARIO_PROMPT)},
                {"role": "user", "content": scenario_request(inventory, rules, descriptions)}]  # fmt: skip
    answer = await converse(caller, agent, phase, messages, lambda content: check_scenarios(content, nodes, ids),
                            max_iterations=max_iterations)  # fmt: skip
    if answer.value is None:
        answer.value = []
    return answer


def document(key: str, agent: str, value: Any) -> str:
    """A stored insight: marked as written by a model (ADR-0032)."""
    return json.dumps({"origin": "model", "agent": agent, key: value}, indent=1, ensure_ascii=False)
