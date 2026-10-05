"""Guided rule extraction (ADR-0033), only with the run option `guided_extraction`: what the extractor and the
reviewers get on top of the slices, so that a long program is not read as loose pieces.

- The extractor reads each slice with the map of its program (blocks, phases, the deep inventory's descriptions when
  there are any) and a small program whole instead of in slices.
- The prompt asks for one rule per business decision and rates P0 strictly; code warns when P0 rules are too many.
- The verifier sees lines around the citation and may correct it (the rule stays, with less confidence and a question
  for a person); the two judges of a P0 rule read it through different lenses (fidelity, criticality).
- Rules that describe the same behaviour from different places are grouped by a model and merged by code.
- Instruction-shaped text in the source (comments, strings) is found by code and reported: the code is data.

Without the option nothing changes: no prompt, no call (the recorded acceptances stay valid). Every model call goes
through a ModelCaller (CLAUDE.md rule 2).
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any

from nexti_agents import prompt
from nexti_core.adapters import Inventory, SliceView, SourceFile
from nexti_core.spec.model import Rule, SourceRef
from nexti_orchestration.extraction import ModelCaller, ReplyError, parse_json
from nexti_orchestration.insights import Answer, converse, units_of
from nexti_orchestration.store import Usage

OPTION = "guided_extraction"
EXTRACTOR_GUIDE = "rules-extractor-guided"  # added to the extractor's prompt
VERIFIER_GUIDE = "rules-verifier-guided"  # added to the verifier's prompt
CONSOLIDATOR = "rules-consolidator"
WHOLE_PROGRAM_LINES = 600  # a file up to this size is read whole, not in slices
MAP_BLOCKS = 60  # blocks listed in a program map
MAP_DESCRIPTION = 200  # characters of each description in the map
REVIEW_WINDOW = 15  # lines shown around a citation, where the verifier may move it
P0_SHARE = 0.25  # more P0 rules than this share is a warning before C1
P0_MIN_RULES = 4
CONSOLIDATE_MIN, CONSOLIDATE_CHUNK = 2, 150
CONFIDENCE_ORDER = ("low", "medium", "high")
PRIORITY_ORDER = ("P2", "P1", "P0")
LENSES = {
    0: "Lens: FIDELITY. Re-derive the behaviour from the code: values, conditions, rounding, ordering of the steps.",
    1: "Lens: CRITICALITY. Besides checking the rule, judge whether P0 is deserved: it moves money or balances, is "
    'regulatory, guards data integrity or security, or is the central decision. Add "critical": true|false.',
}
INJECTION = re.compile(
    r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above)\s+(instructions|rules)|disregard\s+(the\s+)?"
    r"(previous|prior|above)|you\s+are\s+(now\s+)?(an?|the)\s+(ai|assistant|language\s+model|llm)|system\s+prompt|"
    r"<\s*/?\s*(system|assistant)\s*>|do\s+not\s+report\s+(this|these)\s+rules?",
    re.IGNORECASE,
)


def enabled(options: Mapping[str, Any]) -> bool:
    return options.get(OPTION) is True


@dataclass(frozen=True)
class Guide:
    """What the extractor gets on top of the slice: the map of the program the slice belongs to."""

    program_map: str


# -- the extractor's context -----------------------------------------------------------------------------------------
def program_maps(inventory: Inventory, descriptions: Mapping[str, str]) -> dict[str, str]:
    """Per file, the map of its units: blocks in source order with lines, transactional phase and description. It
    tells the extractor where a slice's pieces sit in the program (a backward slice skips what the target does not
    depend on)."""
    maps: dict[str, list[str]] = {}
    for unit, blocks in units_of(inventory):
        if not unit.file:
            continue
        lines = [f"{unit.name} (lines {unit.line_start}-{unit.line_end}), {len(blocks)} block(s)"]
        if unit.key in descriptions:
            lines.append(f"  {descriptions[unit.key][:MAP_DESCRIPTION]}")
        for block in blocks[:MAP_BLOCKS]:
            phase = block.properties.get("phase") or "n/a"
            text = descriptions.get(block.key, "")[:MAP_DESCRIPTION]
            lines.append(f"- lines {block.line_start}-{block.line_end} '{block.name}' (phase {phase})"
                         + (f": {text}" if text else ""))  # fmt: skip
        if len(blocks) > MAP_BLOCKS:
            lines.append(f"- ... and {len(blocks) - MAP_BLOCKS} more block(s)")
        maps.setdefault(unit.file, []).append("\n".join(lines))
    return {file: "\n\n".join(units) for file, units in maps.items()}


def whole_programs(files: Sequence[SourceFile], views: Sequence[SliceView]) -> list[SliceView]:
    """The slices to extract with a small file read whole: one view of the whole file instead of its slices (the
    agent sees the program as it is; nothing to stitch together). Larger files keep their slices."""
    sizes = {f.path: len(f.text.splitlines()) for f in files}
    small = {path for path, n in sizes.items() if 0 < n <= WHOLE_PROGRAM_LINES}
    found: list[SliceView] = []
    done: set[str] = set()
    for view in views:
        if view.file not in small:
            found.append(view)
        elif view.file not in done:
            done.add(view.file)
            unit = view.unit.split("#")[0]
            mine = [v for v in views if v.file == view.file]
            found.append(SliceView(f"{unit}#whole", view.file, ((1, sizes[view.file]),),
                                   tuple(sorted({p for v in mine for p in v.parameters})),
                                   tuple(sorted({t for v in mine for t in v.tables}))))  # fmt: skip
    return found


def extractor_messages(base_prompt: str, request: str, guide: Guide | None) -> list[dict[str, str]]:
    if guide is None:
        return [{"role": "system", "content": base_prompt}, {"role": "user", "content": request}]
    context, _, slice_text = request.partition("\n\nSlice:\n")
    orientation = guide.program_map or "(no map for this file)"
    return [
        {"role": "system", "content": f"{base_prompt}\n{prompt(EXTRACTOR_GUIDE)}"},
        {"role": "user", "content": f"{context}\n\nProgram map (orientation only; cite only lines of the slice):\n"
                                    f"{orientation}\n\nSlice:\n{slice_text}"},
    ]  # fmt: skip


# -- warnings by code ------------------------------------------------------------------------------------------------
def p0_warning(rules: Sequence[Rule]) -> str | None:
    p0 = sum(1 for r in rules if r.priority == "P0")
    if len(rules) >= P0_MIN_RULES and p0 > P0_SHARE * len(rules):
        return (f"{p0} of {len(rules)} rules are P0 (more than {int(P0_SHARE * 100)}%): check that each one moves "
                "money, is regulatory, guards data integrity or is the central decision")  # fmt: skip
    return None


def injection_suspects(files: Sequence[SourceFile]) -> list[tuple[str, int]]:
    """Lines of the source with instruction-shaped text (a comment or string written to steer an agent). The code is
    data: it is reported for a person, never obeyed."""
    return [(f.path, n) for f in files for n, line in enumerate(f.text.splitlines(), start=1) if INJECTION.search(line)]


def injection_warning(found: Sequence[tuple[str, int]]) -> str | None:
    if not found:
        return None
    listed = ", ".join(f"{path.rsplit('/', 1)[-1]}:{n}" for path, n in found[:15])
    return (
        f"{len(found)} line(s) of the source read like instructions to an AI agent ({listed}"
        f"{'…' if len(found) > 15 else ''}): check them; the agents treat the code as data"
    )


# -- the verifier: lenses and corrected citations -------------------------------------------------------------------
def review_messages(base_prompt: str, request: str, source: str, rule: Rule, judge: int) -> list[dict[str, str]]:
    lines = source.splitlines()
    around = []
    for ref in rule.sources:
        start, end = max(1, ref.line_start - REVIEW_WINDOW), min(len(lines), ref.line_end + REVIEW_WINDOW)
        around.append(
            f"{ref.file}:{start}-{end}:\n" + "\n".join(f"{n:>5}  {lines[n - 1]}" for n in range(start, end + 1))
        )
    lens = LENSES[1] if judge == 1 and rule.priority == "P0" else LENSES[0]
    return [
        {"role": "system", "content": f"{base_prompt}\n{prompt(VERIFIER_GUIDE)}"},
        {"role": "user", "content": f"{lens}\n\n{request}\n\nSurrounding lines (where a corrected citation may "
                                    "point):\n" + "\n\n".join(around)},
    ]  # fmt: skip


def corrected_source(data: Mapping[str, Any], rule: Rule, source: str) -> SourceRef | None:
    """The verifier's corrected citation, when it is a valid range with code near the original one."""
    value = data.get("corrected_source")
    if not isinstance(value, dict):
        return None
    try:
        ref = SourceRef(file=rule.sources[0].file, line_start=int(value["line_start"]), line_end=int(value["line_end"]))
    except (KeyError, TypeError, ValueError):
        return None
    lines = source.splitlines()
    near = any(_near(ref, s) for s in rule.sources)
    has_code = ref.line_end <= len(lines) and "".join(lines[ref.line_start - 1 : ref.line_end]).strip()
    unchanged = ref in rule.sources
    return ref if near and has_code and not unchanged else None


def lower(a: str, b: str) -> str:
    return min(a, b, key=CONFIDENCE_ORDER.index)


def _near(ref: SourceRef, other: SourceRef) -> bool:
    return ref.line_start >= other.line_start - REVIEW_WINDOW and ref.line_end <= other.line_end + REVIEW_WINDOW


def with_citation(rule: Rule, ref: SourceRef) -> Rule:
    """The rule with the citation near `ref` moved there (a merged rule keeps its other citations)."""
    old = next((s for s in rule.sources if _near(ref, s)), rule.sources[0])
    note = f"The verifier moved the citation from {old} to {ref}; confirm it is where the rule lives."
    question = f"{rule.sme_question} {note}" if rule.sme_question else note
    sources = tuple(dict.fromkeys(ref if s == old else s for s in rule.sources))
    return rule.model_copy(update={"sources": sources, "confidence": lower(rule.confidence, "medium"),
                                   "sme_question": question[:1000]})  # fmt: skip


def demoted(rule: Rule) -> Rule:
    note = "The criticality judge does not see P0 here (no money, regulation, integrity or central decision)."
    question = f"{rule.sme_question} {note}" if rule.sme_question else note
    return rule.model_copy(update={"priority": "P1", "sme_question": question[:1000]})


# -- consolidation by meaning ----------------------------------------------------------------------------------------
def merge(group: Sequence[Rule]) -> Rule:
    """One rule out of several that describe the same behaviour: the fullest wording, every citation, the highest
    priority, the lowest confidence, every defect and question (the most cautious state)."""
    base = max(group, key=lambda r: len(r.statement))
    sources = tuple(dict.fromkeys(s for r in group for s in r.sources))
    defects = "; ".join(dict.fromkeys(r.suspected_defect for r in group if r.suspected_defect)) or None
    questions = " ".join(dict.fromkeys(r.sme_question for r in group if r.sme_question)) or None
    return base.model_copy(update={
        "sources": sources,
        "priority": max((r.priority for r in group), key=PRIORITY_ORDER.index),
        "confidence": min((r.confidence for r in group), key=CONFIDENCE_ORDER.index),
        "suspected_defect": defects[:1000] if defects else None,
        "sme_question": questions[:1000] if questions else None,
        "scenarios": tuple(dict.fromkeys(s for r in group for s in r.scenarios)),
        "hardcoded": tuple(dict.fromkeys(h for r in group for h in r.hardcoded)),
    })  # fmt: skip


def check_groups(content: str, ids: Sequence[str]) -> tuple[list[list[str]], list[str]]:
    data = parse_json(content)
    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(groups, list):
        raise ReplyError('the answer must be an object {"groups": [["RULE-001", "RULE-007"], ...]}')
    valid: list[list[str]] = []
    seen: set[str] = set()
    problems = []
    for group in groups:
        if not isinstance(group, list) or len(group) < 2:
            problems.append(f"{group}: a group lists two or more rule ids")
            continue
        unknown = [g for g in group if g not in ids]
        twice = [g for g in group if g in seen]
        if unknown or twice:
            problems += [f"{g} is not one of the rule ids you were given" for g in unknown]
            problems += [f"{g} is in more than one group" for g in twice]
            continue
        seen.update(group)
        valid.append([str(g) for g in group])
    return valid, problems


def _check_groups_of(ids: Sequence[str], content: str) -> tuple[list[list[str]], list[str]]:
    return check_groups(content, ids)


async def consolidate_meaning(
    caller: ModelCaller, agent: str, phase: str, rules: Sequence[Rule], *, max_iterations: int
) -> tuple[list[Rule], list[Usage]]:
    """Rules found in different places that state the same business behaviour, grouped by a model (in chunks) and
    merged by code; numbered again RULE-001... by position."""
    if len(rules) < CONSOLIDATE_MIN:
        return list(rules), []
    usage: list[Usage] = []
    merged: list[Rule] = []
    for start in range(0, len(rules), CONSOLIDATE_CHUNK):
        chunk = list(rules[start : start + CONSOLIDATE_CHUNK])
        ids = [r.id for r in chunk]
        listed = "\n".join(json.dumps({"id": r.id, "name": r.name, "category": r.category, "statement": r.statement,
                                       "sources": [str(s) for s in r.sources]}) for r in chunk)  # fmt: skip
        messages = [
            {"role": "system", "content": prompt(CONSOLIDATOR)},
            {"role": "user", "content": f"Rules:\n{listed}"},
        ]
        answer: Answer = await converse(caller, agent, phase, messages, partial(_check_groups_of, ids),
                                        max_iterations=max_iterations)  # fmt: skip
        usage += answer.usage
        groups = answer.value or []
        grouped = {g for group in groups for g in group}
        by_id = {r.id: r for r in chunk}
        merged += [merge([by_id[g] for g in group]) for group in groups]
        merged += [r for r in chunk if r.id not in grouped]
    merged.sort(key=lambda r: (r.sources[0].file, r.sources[0].line_start, r.name))
    return [r.model_copy(update={"id": f"RULE-{i:03d}"}) for i, r in enumerate(merged, start=1)], usage


# -- the target stack and the preferences, as guidance (ADR-0038) ----------------------------------------------------
ARCHITECTURE_NOTES = {
    "preserve-topology": "one service per legacy program, entities mirroring the legacy tables; do not merge programs "
    "into aggregates",
    "modular-monolith": "one deployable with hexagonal modules per bounded context",
    "microservices-hexagonal": "one service per bounded context, hexagonal inside",
    "serverless": "stateless functions; long-running work goes to batch or workflow services",
    "event-driven": "commands and events between contexts; idempotent handlers",
    "bff-microservices": "a backend-for-frontend in front of the domain services",
}
STRATEGY_NOTES = {
    "strangler-fig": "the legacy and the target coexist: every wave leaves a working system, with a façade that routes "
    "each capability to the old or the new side; name those façade stories",
    "anti-corruption-layer": "every call to a legacy program goes through a port that translates models; nothing "
    "of the legacy's shape leaks into the domain",
    "big-bang": "the target replaces the legacy at once",
}
ARTIFACT_NOTES = {
    "container": "packaged as a container image",
    "serverless-function": "packaged as serverless functions (cold start and statelessness matter)",
    "service-package": "packaged as a service package (JAR, assembly or binary) run by a process manager",
}
PRACTICE_NOTES = {
    "clean-code": "small functions, intention-revealing names, no duplication",
    "solid": "single responsibility per class, dependencies on abstractions (the ports)",
    "dependency-injection": "collaborators injected through constructors, never located or instantiated inside",
    "tdd": "the tests from the scenarios exist before the code and the code makes them pass without changing them",
}


def stack_guidance(target: Mapping[str, Any]) -> str:
    """The target stack and the project's preferences in words, for the architect, the developer and the planner.
    Empty when the run has no target: the recorded runs ask nothing more."""
    lines = []
    axes = [(axis, target.get(axis)) for axis in ("architecture", "backend", "frontend", "database", "cloud")]
    stack = ", ".join(
        f"{axis} {value}" + (f" {target[f'{axis}_version']}" if target.get(f"{axis}_version") else "")
        for axis, value in axes
        if value and value != "none"
    )
    if stack:
        lines.append(f"Target stack: {stack}.")
    architecture = str(target.get("architecture") or "")
    if architecture in ARCHITECTURE_NOTES:
        lines.append(f"Architecture {architecture}: {ARCHITECTURE_NOTES[architecture]}.")
    strategy = str(target.get("strategy") or "")
    if strategy in STRATEGY_NOTES:
        lines.append(f"Migration strategy {strategy}: {STRATEGY_NOTES[strategy]}.")
    artifact = str(target.get("artifact") or "")
    if artifact in ARTIFACT_NOTES:
        lines.append(f"Deployment artifact: {ARTIFACT_NOTES[artifact]}.")
    practices = [p for p in str(target.get("practices") or "").split(",") if p in PRACTICE_NOTES]
    if practices:
        lines.append("Coding practices: " + "; ".join(f"{p}: {PRACTICE_NOTES[p]}" for p in practices) + ".")
    return "\n".join(lines)
