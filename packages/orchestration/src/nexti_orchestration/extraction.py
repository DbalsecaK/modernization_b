"""Rule extraction and review (spec 6.1 phase 5, 11.2). Per slice: the extractor writes rules; deterministic checks
come first (valid structure, neutral types, a citation inside the slice and the file); the verifier, another agent
with another context, reviews each rule against its cited lines; P0 rules get a second, independent verdict and a
disagreement becomes a question for a person. Rules from overlapping slices are merged by citation.

Every model call goes through a ModelCaller, which the worker implements on the model gateway (CLAUDE.md rule 2).
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from nexti_agents import prompt
from nexti_core.adapters import SliceView
from nexti_core.spec.model import Rule, SourceRef
from nexti_orchestration.store import Usage

EXTRACTOR = "rules-extractor"
VERIFIER = "rules-verifier"
CITATION_SLACK = 2  # lines a citation may extend past the slice (a closing END, a comment above)


@dataclass(frozen=True)
class ModelReply:
    content: str
    usage: Usage
    cut_at: int | None = None  # the output limit the reply reached: it was cut before its end


class ModelCaller(Protocol):
    async def complete(
        self, agent: str, phase: str, messages: list[dict[str, str]], *, iteration: int = 1, judge: int = 0
    ) -> ModelReply:
        """Call the model assigned to (project, phase, agent) through the gateway. `judge` selects an independent
        verdict (a second judge uses another profile when one is assigned, 11.2)."""
        ...


class ReplyError(ValueError):
    """The model's answer is not what the prompt asked for: the concrete reason goes back to it (11.1)."""


def parse_json(content: str) -> Any:
    """The first JSON value in a reply (models sometimes wrap it in ``` fences or add a sentence)."""
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise ReplyError("the answer has no JSON object")
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise ReplyError(f"the JSON is not valid: {exc.msg} at character {exc.pos}") from exc
    return value


def numbered(source: str, view: SliceView) -> str:
    """The slice as the agent reads it: only its lines, each with its number (5.4)."""
    lines = source.splitlines()
    chunks = []
    for start, end in view.lines:
        chunks.append("\n".join(f"{n:>5}  {lines[n - 1]}" for n in range(start, min(end, len(lines)) + 1)))
    return "\n   ...\n".join(chunks)


def cited_text(source: str, ref: SourceRef) -> str:
    lines = source.splitlines()
    return "\n".join(f"{n:>5}  {lines[n - 1]}" for n in range(ref.line_start, min(ref.line_end, len(lines)) + 1))


def check_citations(rule: Rule, view: SliceView, source: str) -> list[str]:
    """Deterministic: the cited file is the slice's, the lines exist and fall inside the slice."""
    problems = []
    total = len(source.splitlines())
    for ref in rule.sources:
        if ref.file != view.file:
            problems.append(f"{rule.name}: cites {ref.file}, but the slice is of {view.file}")
            continue
        if ref.line_end > total:
            problems.append(f"{rule.name}: cites line {ref.line_end}, the file has {total} lines")
            continue
        inside = any(
            ref.line_start >= start - CITATION_SLACK and ref.line_end <= end + CITATION_SLACK
            for start, end in view.lines
        )
        if not inside:
            problems.append(f"{rule.name}: {ref} is outside the slice you were given")
        if not "".join(source.splitlines()[ref.line_start - 1 : ref.line_end]).strip():
            problems.append(f"{rule.name}: {ref} has no code")
    return problems


@dataclass
class Extraction:
    rules: list[Rule]
    usage: list[Usage] = field(default_factory=list)


def _context(view: SliceView, types: dict[str, str]) -> str:
    declared = "\n".join(f"- {name}: {neutral}" for name, neutral in sorted(types.items()) if neutral)
    return (
        f"File: {view.file}\nUnit: {view.unit}\nParameters this slice depends on: "
        f"{', '.join(view.parameters) or 'none'}\nTables: {', '.join(view.tables) or 'none'}\n"
        f"Declared types (source -> neutral):\n{declared or '- none'}"
    )


def parse_rules(content: str, view: SliceView, source: str) -> list[Rule]:
    """Validate a reply of the extractor; raise ReplyError with every problem found."""
    data = parse_json(content)
    items = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ReplyError('the answer must be an object {"rules": [...]}')
    rules: list[Rule] = []
    problems: list[str] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            problems.append(f"rule {index} is not an object")
            continue
        try:
            rule = Rule.model_validate({**item, "id": f"RULE-{index:03d}"})
        except ValidationError as exc:
            detail = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:6])
            problems.append(f"rule {index} ({item.get('name', 'no name')}): {detail}")
            continue
        problems += check_citations(rule, view, source)
        rules.append(rule)
    if problems:
        raise ReplyError("\n".join(problems))
    return rules


def cut_message(what: str, limit: int) -> str:
    return (
        f"{what}: the model's answer was cut at the output limit of its profile ({limit} tokens) before it ended; "
        "raise the maximum output tokens of the model profile (AI configuration -> Profiles) and run again"
    )


async def extract(
    caller: ModelCaller, view: SliceView, source: str, types: dict[str, str], *, max_iterations: int = 3
) -> Extraction:
    """Extract the rules of one slice, correcting with the concrete errors up to `max_iterations` times."""
    messages = [
        {"role": "system", "content": prompt(EXTRACTOR)},
        {"role": "user", "content": f"{_context(view, types)}\n\nSlice:\n{numbered(source, view)}"},
    ]
    result = Extraction([])
    last_error = ""
    for iteration in range(1, max_iterations + 1):
        reply = await caller.complete(EXTRACTOR, "ruleExtraction", messages, iteration=iteration)
        result.usage.append(reply.usage)
        try:
            result.rules = parse_rules(reply.content, view, source)
            return result
        except ReplyError as exc:
            if reply.cut_at:  # asking again gives the same cut answer: the profile must allow longer replies
                raise ReplyError(cut_message(view.unit, reply.cut_at)) from exc
            last_error = str(exc)
            messages += [
                {"role": "assistant", "content": reply.content},
                {"role": "user", "content": f"Your answer has these problems; fix them and answer again:\n{exc}"},
            ]
    raise ReplyError(f"{view.unit}: no valid rules after {max_iterations} attempts: {last_error}")


@dataclass(frozen=True)
class Review:
    supported: bool
    problems: tuple[str, ...]
    corrected_statement: str | None
    usage: Usage


async def review(caller: ModelCaller, rule: Rule, source: str, *, judge: int = 0) -> Review:
    cited = "\n\n".join(f"{ref}:\n{cited_text(source, ref)}" for ref in rule.sources)
    rule_json = rule.model_dump_json(include={"name", "category", "priority", "statement", "condition", "action"})
    messages = [
        {"role": "system", "content": prompt(VERIFIER)},
        {"role": "user", "content": f"Rule:\n{rule_json}\n\nCited lines:\n{cited}"},
    ]
    reply = await caller.complete(VERIFIER, "ruleExtraction", messages, judge=judge)
    data = parse_json(reply.content)
    if not isinstance(data, dict) or not isinstance(data.get("supported"), bool):
        raise ReplyError('the verifier must answer {"supported": true|false, ...}')
    problems = tuple(str(p) for p in data.get("problems") or [])
    corrected = data.get("corrected_statement")
    return Review(data["supported"], problems, str(corrected) if corrected else None, reply.usage)


def _overlap(a: SourceRef, b: SourceRef) -> float:
    if a.file != b.file:
        return 0.0
    common = min(a.line_end, b.line_end) - max(a.line_start, b.line_start) + 1
    if common <= 0:
        return 0.0
    return common / min(a.line_end - a.line_start + 1, b.line_end - b.line_start + 1)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def same_rule(a: Rule, b: Rule) -> bool:
    """Two candidates describe the same rule: their citations overlap mostly and their names share most words."""
    cited = max((_overlap(x, y) for x in a.sources for y in b.sources), default=0.0)
    wa, wb = _words(a.name + " " + a.statement), _words(b.name + " " + b.statement)
    similar = len(wa & wb) / max(1, min(len(wa), len(wb)))
    return cited >= 0.8 and similar >= 0.5


def consolidate(candidates: Sequence[Rule]) -> list[Rule]:
    """Merge duplicates found in overlapping slices and number the result RULE-001... by position in the source."""
    kept: list[Rule] = []
    for rule in candidates:
        twin = next((k for k in kept if same_rule(k, rule)), None)
        if twin is None:
            kept.append(rule)
        elif len(rule.statement) > len(twin.statement):  # keep the more complete wording
            kept[kept.index(twin)] = rule
    kept.sort(key=lambda r: (r.sources[0].file, r.sources[0].line_start, r.name))
    return [r.model_copy(update={"id": f"RULE-{i:03d}"}) for i, r in enumerate(kept, start=1)]
