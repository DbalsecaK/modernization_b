"""Executors of the modernization flow, analysis half (spec 6.1 phases 2-7): inventory, domain map, classification,
rule extraction with independent review, user stories with the suggested plan, and UI (sources without screens).

Executors never touch the database, the graph or a provider: they work through a ProjectPort that the worker
implements. Everything a phase computes goes through `ctx.step`/`ctx.invoke`, so a question in the middle of the
phase never repeats a model call when the phase resumes.
"""

import json
from collections.abc import Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Protocol

from nexti_adapter_aspx import AspxAdapter
from nexti_adapter_cobol import CobolAdapter
from nexti_adapter_sybase import SybaseAdapter
from nexti_core.adapters import Inventory, Node, SliceView, SourceAdapter, SourceFile
from nexti_core.spec.model import Rule, SourceRef
from nexti_orchestration import guided, insights
from nexti_orchestration.context import Attempt, NeedsAnswer, PhaseContext
from nexti_orchestration.extraction import EXTRACTOR, VERIFIER, ModelCaller, ReplyError, consolidate, extract, review
from nexti_orchestration.model import Option, PhaseFailedError, PhaseResult, QuestionSpec
from nexti_orchestration.stories import FALLBACK_WRITER, STORY_WRITER, RuleData, Stories, derive
from nexti_orchestration.usage import total

ADAPTERS: tuple[SourceAdapter, ...] = (SybaseAdapter(), CobolAdapter(), AspxAdapter())
# The adapters a tenant declared (ADR-0039), set by the worker for the run it executes (a context variable: runs of
# other tenants in the same process never see them).
EXTRA_ADAPTERS: ContextVar[tuple[SourceAdapter, ...]] = ContextVar("nexti_extra_adapters", default=())
DETECT_THRESHOLD = 0.5
CLASSIFICATION = "inventory/classification.json"  # the statements with their class, for the Inventory tab
MAX_CLASSIFIED = 20000
COVERAGE = "inventory/coverage.json"  # business statements in no slice, or cited by no rule
CITATIONS = "rules/citations.json"  # the code each rule cites, for the review at C1 (M27b, ADR-0047)
CITED_LINES_AT_MOST = 80  # lines kept per citation: the card shows the code, the program stays in the inputs
LARGE_SLICE = (200, 20)  # lines and pieces of a slice that may duplicate a larger one
CONTAINED = 0.9


def _line_set(view: SliceView) -> set[int]:
    return {n for start, end in view.lines for n in range(start, end + 1)}


def without_contained(views: Sequence[SliceView], business: set[tuple[str, int]] | None = None) -> list[SliceView]:
    """The slices to extract: a large, fragmented slice whose lines are almost all (90%) in a larger slice of the
    same file, with every business statement of it inside that larger slice too, gives the same rules again, so it is
    left out. Without the business lines (an adapter that does not classify statement by statement) nothing is left
    out. Small slices are always kept."""
    if business is None:
        return list(views)
    large = [v for v in views if len(_line_set(v)) >= LARGE_SLICE[0] and len(v.lines) >= LARGE_SLICE[1]]
    lines = {v.unit: _line_set(v) for v in large}

    def contains(o: SliceView, v: SliceView) -> bool:
        mine, theirs = lines[v.unit], lines[o.unit]
        own_business = {n for f, n in business if f == v.file and n in mine}
        return (o.unit != v.unit and o.file == v.file and len(theirs) > len(mine)
                and len(mine & theirs) >= CONTAINED * len(mine) and own_business <= theirs)  # fmt: skip

    dropped = {v.unit for v in large if any(contains(o, v) for o in large)}
    return [v for v in views if v.unit not in dropped]


def uncovered_slices(
    statements: Sequence[dict[str, Any]], views: Sequence[SliceView], context: int = 2
) -> list[SliceView]:
    """One extra slice per unit with the business statements no slice reached (a statement that feeds no business
    outcome is left out of every backward slice), each with a couple of lines around it: no business line goes
    unread."""
    sliced = {(v.file, n) for v in views for start, end in v.lines for n in range(start, end + 1)}
    by_unit: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for st in statements:
        if st.get("label") != "business":
            continue
        start, end = int(st["line_start"]), int(st["line_end"])
        if any((st["file"], n) in sliced for n in range(start, end + 1)):
            continue
        by_unit.setdefault((str(st.get("unit", "")), str(st["file"])), []).append(
            (max(1, start - context), end + context)
        )
    found = []
    for (unit, file), ranges in sorted(by_unit.items()):
        merged: list[tuple[int, int]] = []
        for start, end in sorted(ranges):
            if merged and start <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        found.append(SliceView(f"{unit}#uncovered", file, tuple(merged)))
    return found


def coverage(statements: Sequence[dict[str, Any]], views: Sequence[SliceView], rules: Sequence[Rule]) -> dict[str, Any]:
    """Which business statements reached no slice (no agent read them) and which no rule cites (read, but no rule
    came out): the check against leaving business logic out of the specification."""
    sliced = {(v.file, n) for v in views for start, end in v.lines for n in range(start, end + 1)}
    cited = {(s.file, n) for r in rules for s in r.sources for n in range(s.line_start, s.line_end + 1)}

    def name(path: str) -> str:
        return path.rsplit("/", 1)[-1].lower()

    sliced_by_name = {(name(f), n) for f, n in sliced}
    cited_by_name = {(name(f), n) for f, n in cited}
    business = [s for s in statements if s.get("label") == "business"]
    out: list[dict[str, Any]] = []
    for s in business:
        lines = range(int(s["line_start"]), int(s["line_end"]) + 1)
        in_slice = any((name(s["file"]), n) in sliced_by_name for n in lines)
        is_cited = any((name(s["file"]), n) in cited_by_name for n in lines)
        out.append({"file": s["file"], "line_start": s["line_start"], "line_end": s["line_end"],
                    "unit": s.get("unit", ""), "in_slice": in_slice, "cited": is_cited})  # fmt: skip
    return {
        "business": len(business),
        "not_sliced": sum(1 for s in out if not s["in_slice"]),
        "not_cited": sum(1 for s in out if s["in_slice"] and not s["cited"]),
        "statements": out,
    }


class ProjectPort(Protocol):
    models: ModelCaller

    async def source_files(self) -> list[SourceFile]: ...

    async def save_inventory(self, inventory: Inventory) -> None: ...

    async def save_domains(self, domains: dict[str, list[str]]) -> None: ...

    async def save_rules(self, rules: Sequence[Rule]) -> None: ...

    async def load_rules(self) -> list[Rule]: ...

    async def save_stories(self, stories: Stories) -> None: ...


def pick_adapter(files: list[SourceFile]) -> SourceAdapter:
    candidates = (*ADAPTERS, *EXTRA_ADAPTERS.get())
    scored = sorted(((a.detect(files), a.name, a) for a in candidates), key=lambda t: (-t[0], t[1]))
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
            adapter = pick_adapter(files)
            counts = adapter.classification(files)
            summary = ", ".join(f"{n} {label.replace('_', ' ')}" for label, n in sorted(counts.items()))
            # The detail, statement by statement, for the Inventory tab (when the adapter gives it and the port keeps
            # artifacts): what is business logic, control flow or infrastructure, and why.
            detail = adapter.classified(files) if hasattr(adapter, "classified") else []
            if hasattr(self.port, "save_artifacts"):
                document = json.dumps({"counts": counts, "statements": detail[:MAX_CLASSIFIED]}, indent=1)
                await self.port.save_artifacts({CLASSIFICATION: document}, {CLASSIFICATION: "docs"}, {})
            return Attempt(counts, f"statements: {summary}")

        attempt = await ctx.invoke(_agent(ctx, "legacy-analyst"), work, what="Classification of the statements")
        if insights.enabled(ctx.run.options) and hasattr(self.port, "save_artifacts"):
            await self._describe(ctx, dict(attempt.artifact))
        return PhaseResult(summary=attempt.summary)

    async def _describe(self, ctx: PhaseContext, classification: dict[str, int]) -> None:
        """Deep inventory (ADR-0032): the legacy analyst describes every unit and block (one call per unit), then
        writes the architect's observations on the inventory. Reading aids, stored as generated artifacts."""
        files = await self.files()
        inventory = pick_adapter(files).inventory(files)
        sources = {f.path: f.text for f in files}
        agent = _agent(ctx, "legacy-analyst")
        descriptions: dict[str, str] = {}
        for unit, blocks in insights.units_of(inventory):
            if unit.file not in sources:
                continue
            unit_ctx = ctx.for_shard(f"describe:{unit.key}")

            async def describe(unit: Node = unit, blocks: list[Node] = blocks) -> Attempt:
                found = await insights.describe(self.port.models, agent, ctx.phase.key, inventory,
                                                sources[unit.file or ""], unit, blocks,
                                                max_iterations=ctx.run.max_iterations)  # fmt: skip
                left = f", {len(found.problems)} problem(s) left" if found.problems else ""
                return Attempt(found.value, f"{len(found.value)} description(s){left}", total(found.usage))

            attempt = await unit_ctx.invoke(agent, describe, what=f"Descriptions of {unit.name}")
            descriptions.update(attempt.artifact)
        observations_ctx = ctx.for_shard("observations")

        async def observe() -> Attempt:
            summary = insights.summary_of(inventory, classification, descriptions)
            found = await insights.observe(self.port.models, agent, ctx.phase.key, summary,
                                           max_iterations=ctx.run.max_iterations)  # fmt: skip
            return Attempt(found.value, f"{len(found.value)} observation(s)", total(found.usage))

        observed = await observations_ctx.invoke(agent, observe, what="Observations on the inventory")
        await self.port.save_artifacts(  # type: ignore[attr-defined]
            {insights.DESCRIPTIONS: insights.document("descriptions", agent, descriptions),
             insights.OBSERVATIONS: insights.document("observations", agent, list(observed.artifact))},
            {insights.DESCRIPTIONS: "docs", insights.OBSERVATIONS: "docs"}, {},
        )  # fmt: skip

    # -- rule extraction with review ------------------------------------------------------------------------------
    async def rule_extraction(self, ctx: PhaseContext) -> PhaseResult:
        files = await self.files()
        adapter = pick_adapter(files)
        statements = adapter.classified(files) if hasattr(adapter, "classified") else None
        business = None if statements is None else {
            (str(st["file"]), n) for st in statements if st["label"] == "business"
            for n in range(int(st["line_start"]), int(st["line_end"]) + 1)
        }  # fmt: skip
        views = without_contained(adapter.slices(files), business)
        if statements is not None:
            views += uncovered_slices(statements, views)
        guided_on = guided.enabled(ctx.run.options)
        maps: dict[str, str] = {}
        if guided_on:  # ADR-0033: small programs whole, every slice with the map of its program
            views = guided.whole_programs(files, views)
            maps = guided.program_maps(adapter.inventory(files), await self._descriptions())
        types = adapter.types(files)
        sources = {f.path: f.text for f in files}
        extractor = _agent(ctx, EXTRACTOR)

        async def one(shard_ctx: PhaseContext) -> list[dict[str, Any]]:
            view = next(v for v in views if v.unit == shard_ctx.shard)

            async def work() -> Attempt:
                try:
                    guide = guided.Guide(maps.get(view.file, "")) if guided_on else None
                    found = await extract(self.port.models, view, sources[view.file], types,
                                          max_iterations=ctx.run.max_iterations, guide=guide)  # fmt: skip
                except ReplyError as exc:
                    raise PhaseFailedError(str(exc)[:1500]) from exc
                return Attempt([r.model_dump(mode="json") for r in found.rules],
                               f"{len(found.rules)} candidate rule(s)", total(found.usage))  # fmt: skip

            try:
                attempt = await shard_ctx.invoke(extractor, work, what=f"Rules of {view.unit}")
            except PhaseFailedError as exc:
                # One slice that keeps failing does not throw away the rules of the others: it is reported, and the
                # review before C1 shows the code that has no rule.
                await shard_ctx.store.event("info", "running", f"{view.unit}: no rules ({str(exc)[:300]})",
                                            phase=ctx.phase.key)  # fmt: skip
                return [{"failed": view.unit}]
            return list(attempt.artifact)

        found = await ctx.fan_out([v.unit for v in views], one)
        failed = [r["failed"] for batch in found for r in batch if "failed" in r]
        if failed and len(failed) == len(views):
            raise PhaseFailedError(f"No slice gave valid rules ({len(failed)} failed); see the activity for why")
        rules = consolidate([Rule.model_validate(r) for batch in found for r in batch if "failed" not in r])
        if guided_on:
            rules = await self._consolidate_meaning(ctx, rules)
        rules = await self._review(ctx, rules, sources, guided_on=guided_on)
        await self.port.save_rules(rules)
        warnings: list[str] = []
        if guided_on:  # by code, for the review before C1
            found_warnings = (guided.p0_warning(rules), guided.injection_warning(guided.injection_suspects(files)))
            warnings = [w for w in found_warnings if w]
            for warning in warnings:
                await ctx.store.event("info", "running", warning[:2000], phase=ctx.phase.key)
        if (statements is not None or warnings) and hasattr(self.port, "save_artifacts"):
            report = coverage(statements or [], views, rules)
            if warnings:
                report["warnings"] = warnings
            await self.port.save_artifacts({COVERAGE: json.dumps(report, indent=1)}, {COVERAGE: "docs"}, {})
        if guided_on and hasattr(self.port, "save_artifacts"):
            # The reviewer at C1 reads each rule against the lines it cites (M27b): prose is checked with the code.
            cited = json.dumps(cited_code(rules, files), ensure_ascii=False, indent=1)
            await self.port.save_artifacts({CITATIONS: cited}, {CITATIONS: "docs"}, {})
        p0 = sum(1 for r in rules if r.priority == "P0")
        summary = f"{len(rules)} rule(s), {p0} P0, from {len(views)} slice(s)"
        if failed:
            summary += f"; {len(failed)} slice(s) gave no valid rules: {', '.join(failed[:5])}"
        return PhaseResult(summary=summary)

    async def _descriptions(self) -> dict[str, str]:
        """The deep inventory's descriptions of units and blocks, when the run wrote them (ADR-0032)."""
        if not hasattr(self.port, "load_artifact"):
            return {}
        stored = await self.port.load_artifact(insights.DESCRIPTIONS)
        return dict(json.loads(stored).get("descriptions") or {}) if stored else {}

    async def _consolidate_meaning(self, ctx: PhaseContext, rules: list[Rule]) -> list[Rule]:
        """Guided extraction (ADR-0033): rules stating the same behaviour from different places, merged."""
        verifier = _agent(ctx, VERIFIER)

        async def work() -> Attempt:
            merged, usage = await guided.consolidate_meaning(self.port.models, verifier, ctx.phase.key, rules,
                                                             max_iterations=ctx.run.max_iterations)  # fmt: skip
            return Attempt([r.model_dump(mode="json") for r in merged],
                           f"{len(rules)} rule(s) consolidated into {len(merged)}", total(usage))  # fmt: skip

        attempt = await ctx.for_shard("consolidate").invoke(verifier, work, what="Rules consolidated by meaning")
        return [Rule.model_validate(r) for r in attempt.artifact]

    async def _review(
        self, ctx: PhaseContext, rules: list[Rule], sources: dict[str, str], *, guided_on: bool = False
    ) -> list[Rule]:
        verifier = _agent(ctx, VERIFIER)
        outcomes: dict[str, list[dict[str, Any]]] = {}
        for number, rule in enumerate(rules, start=1):
            judges = 2 if rule.priority == "P0" else 1
            outcomes[rule.id] = []
            for judge in range(judges):

                async def work(rule: Rule = rule, judge: int = judge) -> Attempt:
                    verdict = await review(self.port.models, rule, sources[rule.sources[0].file], judge=judge,
                                           guided=guided_on)  # fmt: skip
                    found: dict[str, Any] = {"supported": verdict.supported, "problems": list(verdict.problems),
                                             "corrected": verdict.corrected_statement}  # fmt: skip
                    if guided_on:
                        moved = verdict.corrected_source
                        found |= {"source": moved.model_dump() if moved else None, "critical": verdict.critical}
                    return Attempt(found, "supported" if verdict.supported else "not supported", verdict.usage)

                attempt = await ctx.invoke(verifier, work, what=f"Review of {rule.id}", iteration=number * 10 + judge)
                outcomes[rule.id].append(dict(attempt.artifact))
        questions: list[QuestionSpec] = []
        final: list[Rule] = []
        for rule in rules:
            verdicts = outcomes[rule.id]
            supported = [v["supported"] for v in verdicts]
            problems = [p for v in verdicts for p in v["problems"]]
            moved = next((v["source"] for v in verdicts if v.get("source")), None)
            if moved:  # guided extraction: the rule stays where the verifier found it, with less confidence
                rule = guided.with_citation(rule, SourceRef.model_validate(moved))
            if all(supported):
                not_critical = rule.priority == "P0" and any(v.get("critical") is False for v in verdicts)
                final.append(guided.demoted(rule) if not_critical else rule)
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
            guidance = guided.preference_guidance(ctx.run.target) if guided.enabled(ctx.run.options) else ""
            try:
                stories = await derive(self.port.models, rules, data, writer=writer,
                                       max_iterations=ctx.run.max_iterations, guidance=guidance)  # fmt: skip
            except ReplyError as exc:
                raise PhaseFailedError(str(exc)[:1500]) from exc
            await self.port.save_stories(stories)
            summary = f"{len(stories.drafts)} user stories in {len(stories.waves)} wave(s) for {len(rules)} rules"
            return Attempt({"stories": len(stories.drafts), "waves": stories.waves}, summary, total(stories.usage))

        attempt = await ctx.invoke(writer, work, what="User stories and migration plan")
        if insights.enabled(ctx.run.options) and hasattr(self.port, "save_artifacts"):
            await self._scenarios(ctx, files, rules)
        return PhaseResult(summary=attempt.summary)

    async def _scenarios(self, ctx: PhaseContext, files: list[SourceFile], rules: list[Rule]) -> None:
        """Deep inventory (ADR-0032, spec 4.1): with the rules consolidated and before C1, the functional analyst
        (the legacy analyst when the team has none) proposes the business flows as scenarios over graph nodes and
        rules; code checks every node and rule exists. Business reviews them in C1."""
        inventory = pick_adapter(files).inventory(files)
        keys = {a.key for a in ctx.run.agents}
        agent = STORY_WRITER if STORY_WRITER in keys else _agent(ctx, "legacy-analyst")
        descriptions: dict[str, str] = {}
        if hasattr(self.port, "load_artifact"):
            stored = await self.port.load_artifact(insights.DESCRIPTIONS)
            descriptions = dict(json.loads(stored).get("descriptions") or {}) if stored else {}

        async def work() -> Attempt:
            found = await insights.propose_scenarios(self.port.models, agent, ctx.phase.key, inventory, rules,
                                                     descriptions, max_iterations=ctx.run.max_iterations)  # fmt: skip
            left = f", {len(found.problems)} problem(s) left" if found.problems else ""
            return Attempt(found.value, f"{len(found.value)} scenario(s){left}", total(found.usage))

        attempt = await ctx.for_shard("scenarios").invoke(agent, work, what="Business flows by scenario")
        scenarios = list(attempt.artifact)
        cited = sorted({r for s in scenarios for r in s["rules"]})
        await self.port.save_artifacts(  # type: ignore[attr-defined]
            {insights.SCENARIOS: insights.document("scenarios", agent, scenarios)}, {insights.SCENARIOS: "docs"},
            {insights.SCENARIOS: cited},
        )  # fmt: skip

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


def cited_code(rules: Sequence[Rule], files: Sequence[SourceFile]) -> dict[str, list[dict[str, Any]]]:
    """Per rule, each citation with its numbered lines of code (at most CITED_LINES_AT_MOST)."""
    texts = {f.path: f.text.splitlines() for f in files}
    by_base = {f.path.rsplit("/", 1)[-1].lower(): f.path for f in files}
    out: dict[str, list[dict[str, Any]]] = {}
    for rule in rules:
        items = []
        for ref in rule.sources:
            path = ref.file if ref.file in texts else by_base.get(ref.file.rsplit("/", 1)[-1].lower(), "")
            lines = texts.get(path, [])
            start, end = max(ref.line_start, 1), min(ref.line_end, len(lines))
            shown = list(range(start, min(end, start + CITED_LINES_AT_MOST - 1) + 1))
            items.append({"file": ref.file, "lineStart": ref.line_start, "lineEnd": ref.line_end,
                          "lines": [{"n": n, "text": lines[n - 1]} for n in shown if 0 < n <= len(lines)],
                          "truncated": end - start + 1 > CITED_LINES_AT_MOST})  # fmt: skip
        out[rule.id] = items
    return out
