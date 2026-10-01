"""Executors of Flow 2, the analysis half (spec 7.2 phases 1-3; ADR-0018): ingestion, normalization and consolidation.

- Ingestion: every accepted input becomes citable text (documents converted in the sandbox, Figma read with the
  tenant's integration and rendered one node per line), kept as artifacts under `inputs/` with its version and hash.
- Normalization: the functional analyst turns the inputs into capabilities, rules, screens and stories with Gherkin;
  code validates every citation, the Gherkin, the ids and that every rule and screen is in a story, and sends the
  problems back (hacer-verificar-corregir).
- Consolidation: the gaps of 7.3 are found by code and become questions with a recommended answer, applied when a
  person answers; the rules verifier looks for contradictions between the inputs and the specification.

Executors never touch the database, the object store or a provider: they work through a FeaturePort.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from nexti_agents import prompt
from nexti_core.spec.model import Capability, Rule, SourceRef
from nexti_core.spec.plan import StoryInfo, suggest
from nexti_core.spec.screens import ScreenSpec
from nexti_ingest import figma
from nexti_ingest.documents import Document
from nexti_orchestration.context import Attempt, PhaseContext
from nexti_orchestration.extraction import ModelCaller, ReplyError, parse_json
from nexti_orchestration.model import Option, PhaseFailedError, PhaseResult, QuestionSpec
from nexti_orchestration.modernization import ask_all
from nexti_orchestration.store import Usage
from nexti_orchestration.stories import Stories, StoryDraft, check_criteria
from nexti_orchestration.usage import total

ANALYST = "functional-analyst"
REVIEWER = "rules-verifier"
INPUTS = "inputs/"


@dataclass(frozen=True)
class FeatureStory:
    """A story as consolidation and validation read it."""

    key: str
    title: str
    criteria: list[str]
    links: list[str]
    status: str


class FeaturePort(Protocol):
    models: ModelCaller

    async def documents(self) -> list[Document]:
        """The accepted documents of the project as text (Word, Excel and PDF converted in the sandbox)."""
        ...

    async def figma_files(self) -> list[tuple[str, dict[str, Any]]]:
        """(file key, file) of every Figma link of the project, read with the tenant's integration."""
        ...

    async def input_names(self, kind: str) -> list[str]:
        """Names (or URLs) of the accepted inputs of a kind: screenshot, prototype_link."""
        ...

    async def save_artifacts(
        self, files: dict[str, str], layers: dict[str, str], rules: dict[str, list[str]]
    ) -> None: ...

    async def load_inputs(self) -> dict[str, str]:
        """The citable text of every input, as ingestion kept it (path -> text)."""
        ...

    async def save_rules(self, rules: Sequence[Rule]) -> None: ...

    async def load_rules(self) -> list[Rule]: ...

    async def save_screens(self, screens: Sequence[ScreenSpec]) -> None: ...

    async def load_screens(self) -> list[ScreenSpec]: ...

    async def save_capabilities(self, capabilities: Sequence[Capability]) -> None: ...

    async def save_stories(self, stories: Stories) -> None: ...

    async def load_stories(self) -> list[FeatureStory]: ...


def _agent(ctx: PhaseContext, preferred: str) -> str:
    keys = {a.key for a in ctx.run.agents}
    if preferred in keys or not keys:
        return preferred
    phase_agents = [a.key for a in ctx.run.agents_of(ctx.phase.key)]
    return phase_agents[0] if phase_agents else preferred


def numbered(inputs: dict[str, str]) -> str:
    """The inputs as the agents read them: a header per input and every line with its number."""
    parts = []
    for path, text in sorted(inputs.items()):
        if path.endswith(".json"):
            continue
        lines = text.split("\n")
        width = len(str(len(lines)))
        body = "\n".join(f"{n:>{width}}| {line}" for n, line in enumerate(lines, start=1))
        parts.append(f"=== {path} ({len(lines)} lines) ===\n{body}")
    return "\n\n".join(parts)


def citable(inputs: dict[str, str]) -> dict[str, int]:
    """Each citable input and its number of lines (the raw Figma JSON is evidence, not citable)."""
    return {p: len(t.split("\n")) for p, t in inputs.items() if not p.endswith(".json")}


def citation_problems(sources: Sequence[str | dict[str, Any] | SourceRef], files: dict[str, int], owner: str
                      ) -> tuple[list[SourceRef], list[str]]:  # fmt: skip
    refs: list[SourceRef] = []
    problems: list[str] = []
    for source in sources:
        try:
            ref = source if isinstance(source, SourceRef) else (
                SourceRef.parse(source) if isinstance(source, str) else SourceRef.model_validate(source))  # fmt: skip
        except (ValueError, ValidationError):
            problems.append(f"{owner}: {source!r} is not a file:line citation")
            continue
        if ref.file not in files:
            problems.append(f"{owner}: cites {ref.file}, which is not an input (inputs: {', '.join(sorted(files))})")
        elif ref.line_end > files[ref.file]:
            problems.append(f"{owner}: cites {ref}, but {ref.file} has {files[ref.file]} lines")
        else:
            refs.append(ref)
    return refs, problems


@dataclass
class Normalized:
    capabilities: list[Capability] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    screens: list[ScreenSpec] = field(default_factory=list)
    stories: list[StoryDraft] = field(default_factory=list)
    usage: list[Usage] = field(default_factory=list)


def _errors(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:6])


def parse_normalized(content: str, inputs: dict[str, str]) -> Normalized:
    """The analyst's answer, checked by code; a ReplyError lists every problem found."""
    data = parse_json(content)
    if not isinstance(data, dict):
        raise ReplyError('the answer must be one JSON object with "capabilities", "rules", "screens" and "stories"')
    files = citable(inputs)
    problems: list[str] = []
    result = Normalized()
    groups: list[tuple[str, type[Any], list[Any]]] = [
        ("rule", Rule, result.rules), ("screen", ScreenSpec, result.screens),
        ("capability", Capability, result.capabilities),
    ]  # fmt: skip
    for kind, model, target in groups:
        key = {"rule": "rules", "screen": "screens", "capability": "capabilities"}[kind]
        items = data.get(key) or []
        if not isinstance(items, list):
            problems.append(f'"{key}" must be a list')
            continue
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                problems.append(f"{kind} {index} is not an object")
                continue
            owner = str(item.get("id") or f"{kind} {index}")
            refs, found = citation_problems(item.get("sources") or [], files, owner)
            problems += found
            if not item.get("sources") and kind != "capability":
                problems.append(f"{owner}: has no source; cite the input lines it comes from")
            fields = item.get("fields")
            if kind == "screen" and isinstance(fields, list):
                item = {**item, "fields": [{"length": 0, **f} if isinstance(f, dict) else f for f in fields]}
            try:
                target.append(model.model_validate({**item, "sources": [r.model_dump() for r in refs]}))
            except ValidationError as exc:
                problems.append(f"{owner}: {_errors(exc)}")
    for kind, ids in (("rule", [r.id for r in result.rules]), ("screen", [s.id for s in result.screens]),
                      ("capability", [c.id for c in result.capabilities])):  # fmt: skip
        repeated = sorted({i for i in ids if ids.count(i) > 1})
        if repeated:
            problems.append(f"repeated {kind} ids: {', '.join(repeated)}")
    screen_ids = {s.id for s in result.screens}
    rule_ids = {r.id for r in result.rules}
    for screen in result.screens:
        loose = [a.target for a in screen.actions if a.target and a.target not in screen_ids]
        loose += [t for t in screen.navigation_out if t not in screen_ids]
        if loose:
            problems.append(f"{screen.id}: navigates to screens that do not exist: {', '.join(sorted(set(loose)))}")
    for capability in result.capabilities:
        unknown = [r for r in capability.rules if r not in rule_ids]
        if unknown:
            problems.append(f"{capability.id}: lists rules that do not exist: {', '.join(unknown)}")
    stories = data.get("stories") or []
    if not isinstance(stories, list) or not stories:
        problems.append('"stories" must list at least one story')
        stories = []
    for index, item in enumerate(stories, start=1):
        try:
            result.stories.append(StoryDraft.model_validate(item))
        except ValidationError as exc:
            problems.append(f"story {index}: {_errors(exc)}")
    known = rule_ids | screen_ids
    covered: set[str] = set()
    for index, draft in enumerate(result.stories, start=1):
        problems += check_criteria(index, draft)
        unknown = [link for link in draft.links if link not in known]
        if unknown:
            problems.append(f"story {index} '{draft.title}' links elements that do not exist: {', '.join(unknown)}")
        covered |= set(draft.links)
    missing = sorted(known - covered)
    if missing:
        problems.append(f"these rules and screens are in no story: {', '.join(missing)}")
    if not result.rules:
        problems.append("there are no rules: every behaviour the inputs ask for is a rule")
    if problems:
        raise ReplyError("\n".join(problems))
    return result


async def normalize(caller: ModelCaller, inputs: dict[str, str], *, agent: str = ANALYST, max_iterations: int = 3
                    ) -> Normalized:  # fmt: skip
    messages = [
        {"role": "system", "content": prompt("functional-analyst-feature")},
        {"role": "user", "content": f"Inputs:\n\n{numbered(inputs)}"},
    ]
    usage: list[Usage] = []
    last = ""
    for iteration in range(1, max_iterations + 1):
        reply = await caller.complete(agent, "normalization", messages, iteration=iteration)
        usage.append(reply.usage)
        try:
            result = parse_normalized(reply.content, inputs)
        except ReplyError as exc:
            last = str(exc)
            messages += [
                {"role": "assistant", "content": reply.content},
                {"role": "user", "content": f"Your answer has these problems; fix them and answer again:\n{exc}"},
            ]
            continue
        result.usage = usage
        return result
    raise ReplyError(f"no valid specification after {max_iterations} attempts: {last[:3000]}")


def stories_of(drafts: Sequence[StoryDraft]) -> Stories:
    """The stories of Flow 2 with their suggested plan. Dependencies are added by people in the plan (7.7): the
    inputs do not say which story needs another one built first."""
    infos = [StoryInfo(f"US-{i:03d}", d.priority, d.estimate) for i, d in enumerate(drafts, start=1)]
    return Stories(list(drafts), [], suggest(infos, []), origin="document")


# -- consolidation: the gaps of 7.3, found by code ---------------------------------------------------------------
@dataclass(frozen=True)
class Gap:
    key: str
    text: str
    context: str
    affects: tuple[str, ...]
    recommended: Option
    alternative: Option
    impact: str = "low"


def gaps(screens: Sequence[ScreenSpec], rules: Sequence[Rule], stories: Sequence[FeatureStory],
         figma_files: Sequence[tuple[str, dict[str, Any]]]) -> list[Gap]:  # fmt: skip
    """The gaps 7.3 lists, checked on the specification and the Figma files."""
    found: list[Gap] = []
    with_rules = {link for s in stories for link in s.links if any(x.startswith("RULE-") for x in s.links)}
    for screen in screens:
        loose = [f for f in screen.inputs() if not f.required and not f.validation]
        if loose:
            names = ", ".join(f.name for f in loose)
            found.append(Gap(
                f"gap-validation-{screen.id}",
                f"{screen.id} '{screen.name}': these input fields have no validation: {names}.",
                "An input field without validation is a gap (7.3): the built screen would accept anything.",
                (screen.id,), Option("validate", "Make them required and validate them by their type",
                                     "Each field becomes required and is checked against its type and length."),
                Option("leave", "Leave them optional without validation", "The screen accepts any value."),
            ))  # fmt: skip
        missing = [s for s in ("error", "empty") if s not in screen.states]
        if screen.inputs() and missing:
            found.append(Gap(
                f"gap-states-{screen.id}", f"{screen.id} '{screen.name}' has no {' and no '.join(missing)} state.",
                "A screen without an error state or an empty state is a gap (7.3).", (screen.id,),
                Option("add", f"Add the {' and '.join(missing)} state(s)",
                       "The prototype and the page show them; the harness checks them."),
                Option("leave", "Leave the screen as it is", "Errors and empty data are not shown."),
            ))  # fmt: skip
        if screen.id not in with_rules:
            for action in screen.actions:
                if not action.target:
                    found.append(Gap(
                        f"gap-action-{screen.id}-{action.key}",
                        f"{screen.id}: the action '{action.label or action.key}' neither navigates nor has a rule "
                        "behind it.", "A screen action without a contract is a gap (7.3).", (screen.id,),
                        Option("remove", "Remove the action", "No input asks for what it would do."),
                        Option("keep", "Keep it, to be defined", "It stays without behaviour until a rule covers it."),
                    ))  # fmt: skip
    for key, data in figma_files:
        for node in figma.dead_buttons(data):
            found.append(Gap(
                f"gap-button-{key}-{node.id}".replace(":", "-"),
                f"The button '{node.name}' of the Figma frame '{node.frame}' navigates nowhere.",
                f"figma/{key}:{node.line}. A prototype button that navigates nowhere is a gap (7.3).",
                _screens_at(screens, f"figma/{key}", node.line, node.frame),
                Option("drop", "Leave it out of the screen", "No requirement asks for it; it is not built."),
                Option("keep", "Keep it, to be defined", "It is built without behaviour and stays as a gap."),
            ))  # fmt: skip
    for rule in rules:
        if not any(re.search(r"\d", s) for s in rule.scenarios):
            found.append(Gap(
                f"gap-values-{rule.id}", f"{rule.id} '{rule.name}' has no scenario with concrete values.",
                "A rule without concrete values is a gap (7.3): the tests need them.", (rule.id,),
                Option("keep", "Keep it; a person adds the values in C1", "The rule is marked for review."),
                Option("drop", "Drop the rule", "No input gives its values."),
                "high" if rule.priority == "P0" else "low",
            ))  # fmt: skip
    return found


def _screens_at(screens: Sequence[ScreenSpec], file: str, line: int, frame: str) -> tuple[str, ...]:
    """The screens a Figma node belongs to: the ones whose citation covers its line, else the one named as its frame."""
    cited = tuple(s.id for s in screens if any(r.file == file and r.line_start <= line <= r.line_end
                                               for r in s.sources))  # fmt: skip
    return cited or tuple(s.id for s in screens if s.name.lower() == frame.lower())


def apply_gaps(answers: dict[str, Any], found: Sequence[Gap], screens: list[ScreenSpec], rules: list[Rule],
               figma_files: Sequence[tuple[str, dict[str, Any]]]) -> tuple[list[ScreenSpec], list[Rule]]:  # fmt: skip
    """The specification with the answered gaps applied (the recommended option unless a person chose another)."""
    by_id = {s.id: s for s in screens}
    kept_rules = list(rules)
    labels = {f"gap-button-{k}-{n.id}".replace(":", "-"): n.name for k, d in figma_files for n in figma.dead_buttons(d)}
    for gap in found:
        answer = answers.get(gap.key)
        option = answer.option if answer is not None and answer.option else gap.recommended.key
        screen = by_id.get(gap.affects[0]) if gap.affects else None
        if gap.key.startswith("gap-validation-") and option == "validate" and screen is not None:
            fields = tuple(
                f.model_copy(update={"required": True, "validation": f.validation or f"required; {f.type or 'text'}"})
                if f.kind == "input" and not f.required and not f.validation else f for f in screen.fields
            )  # fmt: skip
            by_id[screen.id] = screen.model_copy(update={"fields": fields})
        elif gap.key.startswith("gap-states-") and option == "add" and screen is not None:
            states = tuple(dict.fromkeys([*screen.states, "error", "empty"]))
            by_id[screen.id] = screen.model_copy(update={"states": states})
        elif gap.key.startswith("gap-action-") and option == "remove" and screen is not None:
            action = gap.key.removeprefix(f"gap-action-{screen.id}-")
            remaining = tuple(a for a in screen.actions if a.key != action)
            by_id[screen.id] = screen.model_copy(update={"actions": remaining})
        elif gap.key.startswith("gap-button-") and option == "drop" and screen is not None:
            name = _plain(labels.get(gap.key, ""))
            actions = tuple(a for a in screen.actions if not name or (_plain(a.label) not in name
                                                                      and _plain(a.key) not in name))  # fmt: skip
            by_id[screen.id] = screen.model_copy(update={"actions": actions})
        elif gap.key.startswith("gap-values-"):
            rule_id = gap.key.removeprefix("gap-values-")
            if option == "drop":
                kept_rules = [r for r in kept_rules if r.id != rule_id]
            else:
                kept_rules = [r.model_copy(update={"confidence": "low", "sme_question": "Add concrete values"})
                              if r.id == rule_id else r for r in kept_rules]  # fmt: skip
    return [by_id[s.id] for s in screens], kept_rules


def _plain(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower().replace("ó", "o").replace("á", "a").replace("é", "e")
                  .replace("í", "i").replace("ú", "u"))  # fmt: skip


def _question(gap: Gap, agent: str) -> QuestionSpec:
    return QuestionSpec(
        key=gap.key, agent=agent, text=gap.text, context=gap.context[:2000], reason="missingInformation",
        impact="high" if gap.impact == "high" else "low", recommended=gap.recommended, confidence=0.7,
        alternatives=(gap.alternative,), affects=gap.affects,
    )  # fmt: skip


@dataclass(frozen=True)
class Contradiction:
    text: str
    sources: tuple[str, ...]
    affects: tuple[str, ...]
    recommended: str
    alternative: str


def parse_contradictions(content: str, inputs: dict[str, str], known: set[str]) -> list[Contradiction]:
    data = parse_json(content)
    items = data.get("contradictions") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ReplyError('the answer must be an object {"contradictions": [...]}')
    files = citable(inputs)
    problems: list[str] = []
    found: list[Contradiction] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict) or not item.get("text") or not item.get("recommended"):
            problems.append(f"contradiction {index}: needs text, sources, affects, recommended and alternative")
            continue
        refs, cited = citation_problems(item.get("sources") or [], files, f"contradiction {index}")
        problems += cited
        if len(refs) < 1:
            problems.append(f"contradiction {index}: cite the lines on both sides")
        affects = [str(a) for a in item.get("affects") or []]
        unknown = [a for a in affects if a not in known]
        if unknown:
            problems.append(f"contradiction {index}: affects elements that do not exist: {', '.join(unknown)}")
        found.append(Contradiction(str(item["text"])[:1000], tuple(str(r) for r in refs), tuple(affects),
                                   str(item["recommended"])[:200], str(item.get("alternative") or "Keep it as "
                                                                       "the specification says")[:200]))  # fmt: skip
    if problems:
        raise ReplyError("\n".join(problems))
    return found


async def contradictions(
    caller: ModelCaller, inputs: dict[str, str], spec: dict[str, Any], known: set[str], *, agent: str = REVIEWER,
    max_iterations: int = 3,
) -> tuple[list[Contradiction], list[Usage]]:  # fmt: skip
    messages = [
        {"role": "system", "content": prompt("rules-verifier-feature")},
        {"role": "user", "content": f"Inputs:\n\n{numbered(inputs)}\n\nSpecification:\n"
                                    f"{json.dumps(spec, ensure_ascii=False, indent=1)}"},
    ]  # fmt: skip
    usage: list[Usage] = []
    last = ""
    for iteration in range(1, max_iterations + 1):
        reply = await caller.complete(agent, "consolidation", messages, iteration=iteration)
        usage.append(reply.usage)
        try:
            return parse_contradictions(reply.content, inputs, known), usage
        except ReplyError as exc:
            last = str(exc)
            messages += [
                {"role": "assistant", "content": reply.content},
                {"role": "user", "content": f"Your answer has these problems; fix them and answer again:\n{exc}"},
            ]
    raise ReplyError(f"no valid review after {max_iterations} attempts: {last[:2000]}")


class FeaturePhases:
    def __init__(self, port: FeaturePort) -> None:
        self.port = port

    # -- ingestion (deterministic) --------------------------------------------------------------------------------
    async def ingestion(self, ctx: PhaseContext) -> PhaseResult:
        async def work() -> Attempt:
            documents = await self.port.documents()
            try:
                designs = await self.port.figma_files()
            except figma.FigmaError as exc:
                raise PhaseFailedError(str(exc)) from exc
            files: dict[str, str] = {}
            for document in documents:
                for warning in document.warnings:
                    await ctx.store.event("info", "running", f"{document.path}: {warning}"[:2000], phase=ctx.phase.key)
                if document.text.strip():
                    files[f"{INPUTS}{document.path}"] = document.text
            for key, data in designs:
                files[f"{INPUTS}{figma.citable_path(key)}"] = figma.render(key, data)
                files[f"{INPUTS}{figma.citable_path(key)}.json"] = json.dumps(data, ensure_ascii=False)
            if not files:
                raise PhaseFailedError("The project has no documents or Figma files that can be read: upload the "
                                       "requirements or the user stories, or add a Figma link")  # fmt: skip
            await self.port.save_artifacts(files, dict.fromkeys(files, "docs"), {})
            screenshots = await self.port.input_names("screenshot")
            links = await self.port.input_names("prototype_link")
            lines = sum(len(t.split("\n")) for p, t in files.items() if p.startswith(f"{INPUTS}docs/"))
            nodes = sum(len(figma.nodes(d)) for _, d in designs)
            summary = (f"{len(documents)} document(s) with {lines} lines, {len(designs)} Figma file(s) with {nodes} "
                       f"nodes, {len(screenshots)} screenshot(s), {len(links)} prototype link(s)")  # fmt: skip
            return Attempt({"files": sorted(files), "screenshots": screenshots, "links": links}, summary)

        attempt = await ctx.invoke(_agent(ctx, ANALYST), work, what="Ingestion of the inputs")
        return PhaseResult(summary=attempt.summary)

    async def _inputs(self) -> dict[str, str]:
        inputs = {p.removeprefix(INPUTS): t for p, t in (await self.port.load_inputs()).items()}
        if not inputs:
            raise PhaseFailedError("There are no ingested inputs to work from")
        return inputs

    # -- normalization (agent, validated by code) -----------------------------------------------------------------
    async def normalization(self, ctx: PhaseContext) -> PhaseResult:
        inputs = await self._inputs()
        agent = _agent(ctx, ANALYST)

        async def work() -> Attempt:
            try:
                result = await normalize(self.port.models, inputs, agent=agent, max_iterations=ctx.run.max_iterations)
            except ReplyError as exc:
                raise PhaseFailedError(str(exc)[:1500]) from exc
            await self.port.save_rules(result.rules)
            await self.port.save_screens(result.screens)
            await self.port.save_capabilities(result.capabilities)
            await self.port.save_stories(stories_of(result.stories))
            summary = (f"{len(result.capabilities)} capabilities, {len(result.rules)} rules, {len(result.screens)} "
                       f"screens and {len(result.stories)} user stories, every element cited")  # fmt: skip
            return Attempt({"rules": [r.id for r in result.rules], "screens": [s.id for s in result.screens],
                            "stories": len(result.stories)}, summary, total(result.usage))  # fmt: skip

        attempt = await ctx.invoke(agent, work, what="Normalization of the inputs into the specification")
        return PhaseResult(summary=attempt.summary)

    # -- consolidation (code + the reviewer) ----------------------------------------------------------------------
    async def consolidation(self, ctx: PhaseContext) -> PhaseResult:
        inputs = await self._inputs()
        rules = await self.port.load_rules()
        screens = await self.port.load_screens()
        stories = await self.port.load_stories()
        designs = [(p.removeprefix("figma/").removesuffix(".json"), json.loads(t)) for p, t in inputs.items()
                   if p.startswith("figma/") and p.endswith(".json")]  # fmt: skip
        reviewer = _agent(ctx, REVIEWER)
        known = {r.id for r in rules} | {s.id for s in screens}
        spec = {"rules": [r.model_dump(mode="json", exclude_none=True) for r in rules],
                "screens": [s.model_dump(mode="json", exclude_none=True) for s in screens],
                "stories": [{"key": s.key, "title": s.title, "criteria": s.criteria, "links": s.links}
                            for s in stories]}  # fmt: skip

        async def review() -> Attempt:
            try:
                found, usage = await contradictions(self.port.models, inputs, spec, known, agent=reviewer,
                                                    max_iterations=ctx.run.max_iterations)  # fmt: skip
            except ReplyError as exc:
                raise PhaseFailedError(str(exc)[:1500]) from exc
            return Attempt([vars(c) | {"sources": list(c.sources), "affects": list(c.affects)} for c in found],
                           f"{len(found)} contradiction(s)", total(usage))  # fmt: skip

        reviewed = await ctx.invoke(reviewer, review, what="Contradictions between the inputs and the specification")
        found_contradictions = [Contradiction(c["text"], tuple(c["sources"]), tuple(c["affects"]), c["recommended"],
                                              c["alternative"]) for c in reviewed.artifact]  # fmt: skip
        found_gaps = gaps(screens, rules, stories, designs)
        questions = [_question(g, reviewer) for g in found_gaps]
        questions += [QuestionSpec(
            key=f"contradiction-{n}", agent=reviewer, text=c.text, context="Sources: " + ", ".join(c.sources),
            reason="contradiction", impact="high", recommended=Option("recommended", c.recommended, ""),
            confidence=0.6, alternatives=(Option("alternative", c.alternative, ""),), affects=c.affects,
        ) for n, c in enumerate(found_contradictions, start=1)]  # fmt: skip
        answers = ask_all(ctx, questions)
        screens, rules = apply_gaps(answers, found_gaps, screens, rules, designs)
        for n, contradiction in enumerate(found_contradictions, start=1):
            answer = answers.get(f"contradiction-{n}")
            chosen = contradiction.alternative if answer is not None and answer.option == "alternative" else (
                answer.text if answer is not None and not answer.option else contradiction.recommended)  # fmt: skip
            rules = [r.model_copy(update={"sme_question": f"Decided on a contradiction: {chosen}"[:1000]})
                     if r.id in contradiction.affects else r for r in rules]  # fmt: skip
        await ctx.step("apply", lambda: self._save(screens, rules))
        return PhaseResult(summary=f"{len(found_gaps)} gap(s) and {len(found_contradictions)} contradiction(s) "
                                   f"resolved through {len(questions)} question(s)")  # fmt: skip

    async def _save(self, screens: list[ScreenSpec], rules: list[Rule]) -> dict[str, Any]:
        await self.port.save_screens(screens)
        await self.port.save_rules(rules)
        return {"screens": len(screens), "rules": len(rules)}
