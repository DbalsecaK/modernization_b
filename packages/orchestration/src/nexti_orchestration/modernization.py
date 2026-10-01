"""Executors of the modernization flow, analysis half (spec 6.1 phases 2-7): inventory, domain map, classification,
rule extraction with independent review, user stories with the suggested plan, and UI (sources without screens).

Executors never touch the database, the graph or a provider: they work through a ProjectPort that the worker
implements. Everything a phase computes goes through `ctx.step`/`ctx.invoke`, so a question in the middle of the
phase never repeats a model call when the phase resumes.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from nexti_adapter_aspx import AspxAdapter
from nexti_adapter_cobol import CobolAdapter
from nexti_adapter_sybase import SybaseAdapter
from nexti_core.adapters import Inventory, SourceAdapter, SourceFile
from nexti_core.spec.model import Rule
from nexti_orchestration.context import Attempt, NeedsAnswer, PhaseContext
from nexti_orchestration.extraction import EXTRACTOR, VERIFIER, ModelCaller, ReplyError, consolidate, extract, review
from nexti_orchestration.model import Option, PhaseFailedError, PhaseResult, QuestionSpec
from nexti_orchestration.stories import FALLBACK_WRITER, STORY_WRITER, RuleData, Stories, derive
from nexti_orchestration.usage import total

ADAPTERS: tuple[SourceAdapter, ...] = (SybaseAdapter(), CobolAdapter(), AspxAdapter())
DETECT_THRESHOLD = 0.5


class ProjectPort(Protocol):
    models: ModelCaller

    async def source_files(self) -> list[SourceFile]: ...

    async def save_inventory(self, inventory: Inventory) -> None: ...

    async def save_domains(self, domains: dict[str, list[str]]) -> None: ...

    async def save_rules(self, rules: Sequence[Rule]) -> None: ...

    async def load_rules(self) -> list[Rule]: ...

    async def save_stories(self, stories: Stories) -> None: ...


def pick_adapter(files: list[SourceFile]) -> SourceAdapter:
    scored = sorted(((a.detect(files), a.name, a) for a in ADAPTERS), key=lambda t: (-t[0], t[1]))
    if not scored or scored[0][0] < DETECT_THRESHOLD:
        raise PhaseFailedError(
            "No source adapter recognises these inputs (supported in this version: Sybase ASE "
            "stored procedures, COBOL/CICS with BMS maps, ASP.NET WebForms)"
        )
    return scored[0][2]


def _agent(ctx: PhaseContext, preferred: str) -> str:
    keys = {a.key for a in ctx.run.agents}
    if preferred in keys or not keys:
        return preferred
    phase_agents = [a.key for a in ctx.run.agents_of(ctx.phase.key)]
    return phase_agents[0] if phase_agents else preferred


def ask_all(ctx: PhaseContext, questions: Sequence[QuestionSpec]) -> dict[str, Any]:
    """Answers to several questions at once; the unanswered ones are asked together."""
    answers: dict[str, Any] = {}
    waiting = []
    for question in questions:
        try:
            answers[question.key] = ctx.ask(question)
        except NeedsAnswer as missing:
            waiting += missing.questions
    if waiting:
        raise NeedsAnswer(waiting)
    return answers


@dataclass
class ModernizationPhases:
    port: ProjectPort

    async def files(self) -> list[SourceFile]:
        files = await self.port.source_files()
        if not files:
            raise PhaseFailedError("The project has no source code among its accepted inputs")
        return files

    # -- inventory, domains, classification (deterministic) -------------------------------------------------------
    async def inventory(self, ctx: PhaseContext) -> PhaseResult:
        async def work() -> Attempt:
            files = await self.files()
            adapter = pick_adapter(files)
            inventory = adapter.inventory(files)
            await self.port.save_inventory(inventory)
            for problem in inventory.problems[:50]:
                await ctx.store.event("info", "waiting", f"Inventory: {problem}"[:2000], phase=ctx.phase.key)
            metrics = inventory.metrics
            summary = f"{inventory_summary(metrics)}, {len(inventory.problems)} problem(s)"
            return Attempt({"adapter": adapter.name, **metrics, "problems": len(inventory.problems)}, summary)

        attempt = await ctx.invoke(_agent(ctx, "legacy-analyst"), work, what="Inventory of the legacy")
        return PhaseResult(summary=attempt.summary)

    async def domains(self, ctx: PhaseContext) -> PhaseResult:
        async def work() -> Attempt:
            files = await self.files()
            inventory = pick_adapter(files).inventory(files)
            groups = domain_map(inventory)
            await self.port.save_domains(groups)
            return Attempt({"domains": groups}, f"{len(groups)} domain(s) proposed from shared tables")

        attempt = await ctx.invoke(_agent(ctx, "legacy-analyst"), work, what="Domain map")
        return PhaseResult(summary=attempt.summary)

    async def classification(self, ctx: PhaseContext) -> PhaseResult:
        async def work() -> Attempt:
            files = await self.files()
            counts = pick_adapter(files).classification(files)
            summary = ", ".join(f"{n} {label.replace('_', ' ')}" for label, n in sorted(counts.items()))
            return Attempt(counts, f"statements: {summary}")

        attempt = await ctx.invoke(_agent(ctx, "legacy-analyst"), work, what="Classification of the statements")
        return PhaseResult(summary=attempt.summary)

    # -- rule extraction with review ------------------------------------------------------------------------------
    async def rule_extraction(self, ctx: PhaseContext) -> PhaseResult:
        files = await self.files()
        adapter = pick_adapter(files)
        views = adapter.slices(files)
        types = adapter.types(files)
        sources = {f.path: f.text for f in files}
        extractor = _agent(ctx, EXTRACTOR)

        async def one(shard_ctx: PhaseContext) -> list[dict[str, Any]]:
            view = next(v for v in views if v.unit == shard_ctx.shard)

            async def work() -> Attempt:
                try:
                    found = await extract(self.port.models, view, sources[view.file], types,
                                          max_iterations=ctx.run.max_iterations)  # fmt: skip
                except ReplyError as exc:
                    raise PhaseFailedError(str(exc)[:1500]) from exc
                return Attempt([r.model_dump(mode="json") for r in found.rules],
                               f"{len(found.rules)} candidate rule(s)", total(found.usage))  # fmt: skip

            attempt = await shard_ctx.invoke(extractor, work, what=f"Rules of {view.unit}")
            return list(attempt.artifact)

        found = await ctx.fan_out([v.unit for v in views], one)
        rules = consolidate([Rule.model_validate(r) for batch in found for r in batch])
        rules = await self._review(ctx, rules, sources)
        await self.port.save_rules(rules)
        p0 = sum(1 for r in rules if r.priority == "P0")
        return PhaseResult(summary=f"{len(rules)} rule(s), {p0} P0, from {len(views)} slice(s)")

    async def _review(self, ctx: PhaseContext, rules: list[Rule], sources: dict[str, str]) -> list[Rule]:
        verifier = _agent(ctx, VERIFIER)
        outcomes: dict[str, list[dict[str, Any]]] = {}
        for number, rule in enumerate(rules, start=1):
            judges = 2 if rule.priority == "P0" else 1
            outcomes[rule.id] = []
            for judge in range(judges):

                async def work(rule: Rule = rule, judge: int = judge) -> Attempt:
                    verdict = await review(self.port.models, rule, sources[rule.sources[0].file], judge=judge)
                    return Attempt({"supported": verdict.supported, "problems": list(verdict.problems),
                                    "corrected": verdict.corrected_statement},
                                   "supported" if verdict.supported else "not supported", verdict.usage)  # fmt: skip

                attempt = await ctx.invoke(verifier, work, what=f"Review of {rule.id}", iteration=number * 10 + judge)
                outcomes[rule.id].append(dict(attempt.artifact))
        questions: list[QuestionSpec] = []
        final: list[Rule] = []
        for rule in rules:
            verdicts = outcomes[rule.id]
            supported = [v["supported"] for v in verdicts]
            problems = [p for v in verdicts for p in v["problems"]]
            if all(supported):
                final.append(rule)
                continue
            corrected = next((v["corrected"] for v in verdicts if v["corrected"]), None)
            disagree = len(set(supported)) > 1
            if rule.priority != "P0" and corrected:
                final.append(rule.model_copy(update={"statement": corrected, "confidence": "low",
                                                     "sme_question": "; ".join(problems)[:1000] or None}))  # fmt: skip
                continue
            questions.append(QuestionSpec(
                key=f"review-{rule.id}", agent=verifier,
                text=f"{rule.id} '{rule.name}': the reviewers {'disagree' if disagree else 'do not confirm it'}. "
                     "Keep it?",
                context=(f"{rule.statement}\n\nProblems found:\n- " + "\n- ".join(problems))[:2000],
                reason="judgesDisagree" if disagree else "lowConfidence",
                impact="high" if rule.priority == "P0" else "low",
                recommended=Option("keep", "Keep the rule for review" + (" with the correction" if corrected else ""),
                                   "A person reviews it in C1 with the problems attached."),
                confidence=0.5,
                alternatives=(Option("discard", "Discard it", "The code does not support it."),),
                affects=(rule.id,),
            ))  # fmt: skip
            final.append(rule)
        answers = ask_all(ctx, questions)
        kept = []
        for rule in final:
            answer = answers.get(f"review-{rule.id}")
            if answer is not None and answer.option == "discard":
                continue
            if answer is not None:
                corrected = next((v["corrected"] for v in outcomes[rule.id] if v["corrected"]), None)
                rule = rule.model_copy(update={"confidence": "low", **({"statement": corrected} if corrected else {})})
            kept.append(rule)
        return kept

    # -- user stories and the plan --------------------------------------------------------------------------------
    async def rule_review(self, ctx: PhaseContext) -> PhaseResult:
        rules = await self.port.load_rules()
        if not rules:
            raise PhaseFailedError("There are no rules to group into user stories")
        files = await self.files()
        adapter = pick_adapter(files)
        data = {r.id: RuleData(*adapter.data_of(files, r.sources[0].file, [(s.line_start, s.line_end)
                                                                           for s in r.sources]),
                               r.sources[0].line_start) for r in rules}  # fmt: skip
        writer = STORY_WRITER if any(a.key == STORY_WRITER for a in ctx.run.agents) else FALLBACK_WRITER

        async def work() -> Attempt:
            try:
                stories = await derive(self.port.models, rules, data, writer=writer,
                                       max_iterations=ctx.run.max_iterations)  # fmt: skip
            except ReplyError as exc:
                raise PhaseFailedError(str(exc)[:1500]) from exc
            await self.port.save_stories(stories)
            summary = f"{len(stories.drafts)} user stories in {len(stories.waves)} wave(s) for {len(rules)} rules"
            return Attempt({"stories": len(stories.drafts), "waves": stories.waves}, summary, total(stories.usage))

        attempt = await ctx.invoke(writer, work, what="User stories and migration plan")
        return PhaseResult(summary=attempt.summary)

    async def ui(self, ctx: PhaseContext) -> PhaseResult:
        return PhaseResult(summary="The sources have no screens: nothing to design (stored procedures only)")


# The units of the code layer that can form a domain, whatever the language.
UNIT_LABELS = ("StoredProcedure", "Program")
_SUMMARY = (("procedures", "procedure(s)"), ("transactions", "transaction(s)"), ("programs", "program(s)"),
            ("paragraphs", "paragraph(s)"), ("statements", "statements"), ("tables", "tables"), ("files", "file(s)"),
            ("maps", "map(s)"), ("copybooks", "copybook(s)"), ("pages", "page(s)"), ("classes", "class(es)"),
            ("methods", "method(s)"))  # fmt: skip


def inventory_summary(metrics: dict[str, int]) -> str:
    """The inventory in words, with the metrics the adapter has (a procedure, a program, a transaction...)."""
    return ", ".join(f"{metrics[key]} {label}" for key, label in _SUMMARY if key in metrics) or "nothing inventoried"


def domain_map(inventory: Inventory) -> dict[str, list[str]]:
    """Units that write the same tables or files form a domain (communities by shared data, 6.1 phase 3), named
    after the data most of them write. External units (called, not in the inputs) are left out."""
    procs = [n.key for n in inventory.nodes if n.label in UNIT_LABELS and not n.properties.get("external")]
    parent = {p: p for p in procs}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    writers: dict[str, list[str]] = {}
    for edge in inventory.edges:
        if edge.type == "WRITES" and edge.source in parent:
            writers.setdefault(edge.target, []).append(edge.source)
    for group in writers.values():
        for other in group[1:]:
            parent[find(other)] = find(group[0])
    domains: dict[str, list[str]] = {}
    for proc in procs:
        domains.setdefault(find(proc), []).append(proc)
    named: dict[str, list[str]] = {}
    for members in domains.values():
        tables = sorted(t for t, ws in writers.items() if set(ws) & set(members))
        name = tables[0].split(":")[-1].split(".")[-1] if tables else members[0].split(":")[-1]
        named[name] = sorted(members)
    return dict(sorted(named.items()))
