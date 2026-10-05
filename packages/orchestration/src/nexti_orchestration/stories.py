"""User stories from the extracted rules (spec 7.7, Flow 1): an agent groups rules into stories with Gherkin
criteria; the criteria are validated by code (D-26) and invalid ones go back with the exact problems; every rule
must end up in a story. Dependencies between stories come from the data, not from the model: a story that reads a
table another story writes depends on it (hard when the writer comes first in the legacy, soft otherwise)."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nexti_agents import prompt
from nexti_core.spec import gherkin
from nexti_core.spec.model import Priority, Rule
from nexti_core.spec.plan import Dependency, StoryInfo, suggest
from nexti_orchestration.extraction import ModelCaller, ReplyError, parse_json, raise_if_cut
from nexti_orchestration.store import Usage

STORY_WRITER = "functional-analyst"
FALLBACK_WRITER = "rules-extractor"


class StoryDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    feature: str = Field(default="", max_length=200)
    title: str = Field(min_length=3, max_length=200)
    narrative: str = Field(default="", max_length=2000)
    criteria: list[str] = Field(min_length=1)
    links: list[str] = Field(min_length=1)
    priority: Priority = "P1"
    estimate: int = Field(default=3, ge=1, le=100)


@dataclass(frozen=True)
class RuleData:
    """What the data layer says about a rule: the tables its cited lines read and write, and where it starts."""

    reads: frozenset[str]
    writes: frozenset[str]
    first_line: int


@dataclass
class Stories:
    drafts: list[StoryDraft]
    dependencies: list[Dependency] = field(default_factory=list)
    waves: list[list[str]] = field(default_factory=list)
    usage: list[Usage] = field(default_factory=list)
    origin: str = "extracted"  # where the stories come from (7.7): extracted from the legacy, or from documents

    def keys(self) -> list[str]:
        return [f"US-{i:03d}" for i in range(1, len(self.drafts) + 1)]


def check_criteria(index: int, draft: StoryDraft) -> list[str]:
    """The Gherkin problems of a story's criteria (D-26), one line per criterion."""
    problems = []
    for criterion, found in gherkin.validate_criteria(draft.criteria).items():
        codes = ", ".join(f"{p.message} (line {p.line})" if p.line else p.message for p in found)
        problems.append(f"story {index} '{draft.title}', criterion {criterion + 1}: {codes}")
    return problems


def check(drafts: Sequence[StoryDraft], rules: Sequence[Rule]) -> list[str]:
    """Deterministic checks of the stories: valid Gherkin, known rules, every rule covered."""
    problems: list[str] = []
    known = {r.id for r in rules}
    covered: set[str] = set()
    for index, draft in enumerate(drafts, start=1):
        problems += check_criteria(index, draft)
        unknown = [link for link in draft.links if link not in known]
        if unknown:
            problems.append(f"story {index} '{draft.title}' links unknown rules: {', '.join(unknown)}")
        covered |= set(draft.links) & known
    missing = sorted(known - covered)
    if missing:
        problems.append(f"these rules are in no story: {', '.join(missing)}")
    return problems


def parse(content: str, rules: Sequence[Rule]) -> list[StoryDraft]:
    data = parse_json(content)
    items = data.get("stories") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise ReplyError('the answer must be an object {"stories": [...]} with at least one story')
    drafts: list[StoryDraft] = []
    problems: list[str] = []
    for index, item in enumerate(items, start=1):
        try:
            drafts.append(StoryDraft.model_validate(item))
        except ValidationError as exc:
            detail = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:6])
            problems.append(f"story {index}: {detail}")
    problems += check(drafts, rules)
    if problems:
        raise ReplyError("\n".join(problems))
    return drafts


def dependencies(drafts: Sequence[StoryDraft], data: Mapping[str, RuleData]) -> list[Dependency]:
    """B depends on A when B reads a table A writes: hard if A's writing rule comes before B's reading rule in the
    legacy (the table must exist and hold A's data first), soft otherwise (a stub or ACL can stand in, 6.3)."""
    keys = [f"US-{i:03d}" for i in range(1, len(drafts) + 1)]
    found: dict[tuple[str, str], Dependency] = {}
    for a_key, a in zip(keys, drafts, strict=True):
        for b_key, b in zip(keys, drafts, strict=True):
            if a_key == b_key:
                continue
            for wr in (data[r] for r in a.links if r in data):
                for rd in (data[r] for r in b.links if r in data):
                    shared = sorted(wr.writes & rd.reads)
                    if not shared:
                        continue
                    strength = "hard" if wr.first_line < rd.first_line else "soft"
                    reason = f"reads {shared[0]}, written by {a_key}"
                    current = found.get((b_key, a_key))
                    if current is None or (current.strength == "soft" and strength == "hard"):
                        found[(b_key, a_key)] = Dependency(b_key, a_key, strength, reason)  # type: ignore[arg-type]
    # Two stories writing each other's tables: the later story keeps its hard dependency on the earlier one; the
    # reverse becomes soft, so the plan has no cycle.
    for (b_key, a_key), dep in sorted(found.items()):
        reverse = found.get((a_key, b_key))
        if reverse and dep.strength == reverse.strength == "hard" and b_key < a_key:
            found[(b_key, a_key)] = Dependency(b_key, a_key, "soft", dep.reason)
    return sorted(found.values(), key=lambda d: (d.story, d.on))


def rules_digest(rules: Sequence[Rule]) -> str:
    return json.dumps(
        [r.model_dump(include={"id", "name", "category", "priority", "statement", "condition", "action",
                                "scenarios"}) for r in rules],
        ensure_ascii=False, indent=1,
    )  # fmt: skip


async def derive(
    caller: ModelCaller,
    rules: Sequence[Rule],
    data: Mapping[str, RuleData],
    *,
    writer: str = STORY_WRITER,
    max_iterations: int = 3,
) -> Stories:
    """Stories, their dependencies and the suggested plan. Raises ReplyError after `max_iterations` invalid answers."""
    messages = [
        {"role": "system", "content": prompt(STORY_WRITER)},
        {"role": "user", "content": f"Business rules:\n{rules_digest(rules)}"},
    ]
    usage: list[Usage] = []
    last = ""
    for iteration in range(1, max_iterations + 1):
        reply = await caller.complete(writer, "ruleReview", messages, iteration=iteration)
        usage.append(reply.usage)
        try:
            drafts = parse(reply.content, rules)
        except ReplyError as exc:
            raise_if_cut(reply, "User stories", exc)
            last = str(exc)
            messages += [
                {"role": "assistant", "content": reply.content},
                {"role": "user", "content": f"Your answer has these problems; fix them and answer again:\n{exc}"},
            ]
            continue
        deps = dependencies(drafts, data)
        infos = [StoryInfo(f"US-{i:03d}", d.priority, d.estimate) for i, d in enumerate(drafts, start=1)]
        return Stories(drafts, deps, suggest(infos, deps), usage)
    raise ReplyError(f"no valid user stories after {max_iterations} attempts: {last}")
