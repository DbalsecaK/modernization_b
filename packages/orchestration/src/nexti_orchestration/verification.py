"""Independent verification (spec 6.1 phase 11, 11.3): the validator redoes the work instead of trusting the
builder's notes. For every module it builds the generated project again from the stored files, replays the golden
master and fresh inputs on it, runs the canary and checks the legacy is intact; `nexti_verification` computes the
verdict from that evidence with fixed rules. No model takes part. The proof pack is stored; a person signs off at C4.
"""

import io
import json
import zipfile
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast

from nexti_adapter_sybase.golden import parameter_defaults
from nexti_core.adapters import LegacyRunner, LegacyUnavailableError, SourceFile
from nexti_core.spec.characterization import (
    GoldenMaster,
    Suite,
    engine_not_proven,
    legacy_gaps,
    same_program,
    source_digest,
)
from nexti_core.spec.design import Design, UseCase
from nexti_core.spec.equivalence import EquivalenceRun
from nexti_core.spec.model import Rule
from nexti_core.spec.screens import ScreenSpec
from nexti_orchestration import frontend, infrastructure
from nexti_orchestration.context import Attempt, PhaseContext
from nexti_orchestration.correction import CorrectionPort, Round, correct, differing
from nexti_orchestration.guided import enabled as guided_enabled
from nexti_orchestration.model import Answer, Option, PhaseFailedError, PhaseResult, QuestionSpec
from nexti_orchestration.packs import BackendPack, backend_pack
from nexti_orchestration.scope import scope_files, split_rules
from nexti_orchestration.scope import unit_of_work as scope_unit_of_work
from nexti_pack_frontend import IMAGE as FRONTEND_IMAGE
from nexti_pack_frontend import contract_of
from nexti_pack_frontend.build import FrontendRun, build_and_test
from nexti_sandbox import Sandbox
from nexti_sandbox.coverage import TargetCoverage, target_coverage
from nexti_verification import Verdict, build_proof_pack, differences, fresh_suite
from nexti_verification import verdict as checks
from nexti_verification.proof_pack import verification_document
from nexti_verification.verdict import CaseOutcome


def stubbed_programs(master: GoldenMaster) -> list[str]:
    """The external programs the cases replaced by stubs: their logic and effects were not in the golden master."""
    return sorted({program for recorded in master.results for program in recorded.case.stubs})


def same_engine(design: Design, source: Sequence[SourceFile], master: GoldenMaster) -> Any:
    """The legacy's engine for the target to run against (ADR-0055), when the design keeps the data where it is and
    the legacy is Sybase: `async with same_engine(...) as engine` gives an EngineTarget, or None otherwise."""
    if design.data_strategy != "same_database" or master.from_traces:
        return _nothing()
    from nexti_orchestration.modernization import pick_adapter

    try:
        adapter = pick_adapter(list(source))
    except Exception:
        return _nothing()
    if not adapter.name.startswith("sybase"):
        return _nothing()
    from nexti_adapter_sybase.ase import SameEngine

    suite = Suite(program=master.program, schema_=master.schema_, cases=[r.case for r in master.results])
    return SameEngine(list(source), suite)


class _nothing:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: object) -> None:
        return None


def unit_of_work(files: Sequence[SourceFile], program: str) -> list[tuple[int, str]]:
    """The lines where the legacy program starts, saves, confirms or undoes its work (ADR-0055); the
    characterization uses the same (`nexti_orchestration.scope`)."""
    return scope_unit_of_work(files, program)


def rollbacks_without_case(work: Sequence[tuple[int, str]], master: GoldenMaster) -> list[int]:
    """Rollback points of the legacy no golden case entered (ADR-0055). Needs the coverage of ADR-0047: when it was
    not measured, every rollback counts as without a case, which is the truth the verdict must tell."""
    rollbacks = [line for line, kind in work if kind == "rollback"]
    if not rollbacks:
        return []
    if master.coverage is None:
        return rollbacks
    entered: set[tuple[int, int]] = set()
    reliable = set(master.coverage.executed) - set(master.coverage.unreliable)
    for branch in master.coverage.branches:
        if any(branch.id in master.coverage.executed[case] for case in reliable):
            entered.add((branch.line_start, branch.line_end))
    return [line for line in rollbacks if not any(start <= line <= end for start, end in entered)]


VALIDATOR = "equivalence-validator"


def frontend_proof_pack(verdict: Verdict, run: FrontendRun) -> bytes:
    """The frontend verdict and, screen by screen, what the harness found."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("VERIFICATION.json", json.dumps(verification_document(verdict), indent=2))
        archive.writestr("FRONTEND.json", json.dumps({
            "flavour": run.flavour, "compiled": run.compiled, "bundled": run.app, "errors": run.errors,
            "screens": [{"id": s.id, "checks": [vars(c) for c in s.checks]} for s in run.screens],
        }, indent=2))  # fmt: skip
    return buffer.getvalue()


class VerificationPort(Protocol):
    async def load_rules(self) -> list[Rule]: ...

    async def source_files(self) -> list[SourceFile]: ...

    async def load_design(self) -> Design | None: ...

    async def load_golden_master(self) -> GoldenMaster | None: ...

    async def load_generated(self) -> tuple[dict[str, str], dict[str, list[str]]]:
        """The generated files of the project (path -> content) and the rules each one implements."""
        ...

    def legacy_runner(self) -> LegacyRunner | None: ...

    def sandbox(self, image: str) -> Sandbox: ...

    async def load_frontend(self) -> dict[str, str]:
        """The generated frontend files, paths relative to the frontend project (M6b)."""
        ...

    async def load_screens(self) -> list[ScreenSpec]: ...

    async def save_verdict(self, verdict: Verdict, proof_pack: bytes) -> str:
        """Stores the verdict and its proof pack; returns the key of the proof pack."""
        ...


def outcomes(run: EquivalenceRun, rules: Mapping[str, Sequence[str]]) -> list[CaseOutcome]:
    return [CaseOutcome(c.name, rules.get(c.name, ()), () if c.failure else differences(c.expected, c.actual),
                        c.failure) for c in run.cases]  # fmt: skip


TARGET_REGIONS_AT_MOST = 30
GAPS_SHOWN = 40


def gap_question(gaps: Sequence[str]) -> QuestionSpec:
    """The decision card of the gaps of the legacy (ADR-0050): signed unreachable, or kept as not proven."""
    shown = "\n".join(f"- {g}" for g in gaps[:GAPS_SHOWN])
    more = len(gaps) - GAPS_SHOWN
    return QuestionSpec(
        key="legacy-gaps",
        agent=VALIDATOR,
        text=f"{len(gaps)} part(s) of the legacy have no case in the golden master. Are they unreachable?",
        context=("The golden master proves only what its cases run. These branches were entered by no case and "
                 "these engine quirks reached by none, after the test engineer was asked for them:\n" + shown
                 + (f"\n... and {more} more" if more > 0 else "")
                 + "\n\nSigned as unreachable (no input can reach them), the verdict can be PROVEN; kept as gaps, "
                 "it stays PARTLY PROVEN and lists them."),
        reason="missingInformation",
        impact="high",
        recommended=Option("accept", "Keep them as not proven", "Nobody has shown that no input reaches them: the "
                           "verdict stays PARTLY PROVEN and lists each one"),
        confidence=0.6,
        alternatives=(Option("unreachable", "Sign them as unreachable", "I checked the code: no input of the "
                             "program can reach these branches or lines (say why in the comment)"),),
        affects=("verification",),
    )  # fmt: skip


def target_not_run(measured: TargetCoverage) -> list[str]:
    """The target coverage as findings of the verdict (M29): the code no golden case runs."""
    lines = [f"Target coverage: {measured.note()}"]
    lines += [
        f"Target code no golden case runs (logic the legacy may not have, or a case the suite misses): "
        f"{r.file} lines {r.line_start}-{r.line_end}"
        for r in measured.uncovered[:TARGET_REGIONS_AT_MOST]
    ]
    more = len(measured.uncovered) - TARGET_REGIONS_AT_MOST
    if more > 0:
        lines.append(f"... and {more} more target region(s) no case runs (TARGET_COVERAGE.json)")
    return lines


def _module(design: Design, master: GoldenMaster) -> UseCase:
    matching = [u for u in design.use_cases if same_program(u.legacy_program, master.program)]
    if matching:
        return matching[0]
    if len(design.use_cases) == 1:
        return design.use_cases[0]
    named = ", ".join(f"{u.name} ({u.legacy_program or 'no legacy program'})" for u in design.use_cases)
    raise PhaseFailedError(f"No use case of the design replaces {master.program}: the use cases are {named}")


VERDICT_DOC = "docs/verification/VERDICT.json"  # ADR-0056: the verdict travels with the delivery


class VerificationPhases:
    def __init__(self, port: VerificationPort) -> None:
        self.port = port

    async def verification(self, ctx: PhaseContext) -> PhaseResult:
        # ADR-0050: the gaps of the legacy (branches without a case, quirks no case reaches) need a signed decision
        # before PROVEN; asked first, so waiting for it repeats no work.
        master = await self.port.load_golden_master()
        gaps = legacy_gaps(master) if master is not None else []
        decision = ctx.ask(gap_question(gaps)) if gaps else None

        async def work() -> Attempt:
            return Attempt(await self._verify(ctx, gaps, decision), "verdict")

        attempt = await ctx.invoke(VALIDATOR, work, what="Independent verification")
        return PhaseResult(summary=attempt.artifact["summary"])

    async def _verify(self, ctx: PhaseContext, gaps: Sequence[str] = (), decision: Answer | None = None
                      ) -> dict[str, Any]:  # fmt: skip
        design = await self.port.load_design()
        master = await self.port.load_golden_master()
        if design is None or master is None:
            raise PhaseFailedError("Verification needs the approved design and the golden master")
        files, traced = await self.port.load_generated()
        if not files:
            raise PhaseFailedError("There is no generated code to verify")
        rules = await self.port.load_rules()
        source = await self.port.source_files()
        use_case = _module(design, master)
        backend = backend_pack(ctx.run.target)
        if backend is None:
            raise PhaseFailedError(f"The {ctx.run.target.get('backend')} pack is not available to verify with")
        sandbox = self.port.sandbox(backend.image)
        defaults = parameter_defaults(source, master.program)
        case_rules = {r.case.name: r.case.rules for r in master.results}

        await ctx.store.event("started", "running", "Clean build, tests and golden master on the target",
                              phase=ctx.phase.key)  # fmt: skip
        # ADR-0055 (point 10): with the data kept where it is, the target runs its golden master against the
        # legacy's engine (tables, transactional substitutes, call log), on a network of the run.
        async with same_engine(design, source, master) as engine:
            return await self._verify_with(ctx, gaps, decision, design, master, files, traced, rules, source,
                                           use_case, backend, sandbox, defaults, case_rules, engine)  # fmt: skip

    async def _verify_with(
        self, ctx: PhaseContext, gaps: Sequence[str], decision: Any, design: Design, master: GoldenMaster,
        files: dict[str, str], traced: Any, rules: Sequence[Rule], source: list[SourceFile], use_case: UseCase,
        backend: BackendPack, sandbox: Sandbox, defaults: dict[str, Any], case_rules: dict[str, list[str]],
        engine: Any | None,
    ) -> dict[str, Any]:  # fmt: skip
        if engine is not None:
            await ctx.store.event("info", "running", f"The target runs against the legacy's engine ({engine.name}): "
                                  "its tables, the substitutes of the called programs and the call log",
                                  phase=ctx.phase.key)  # fmt: skip
        golden_run = await backend.run_equivalence(sandbox, files, design, use_case, master, defaults, engine=engine)
        golden = outcomes(golden_run, case_rules)
        rounds: list[Round] = []
        if (
            guided_enabled(ctx.run.options)
            and not golden_run.problem
            and differing(golden)
            and hasattr(self.port, "models")
        ):
            # The developer sees the differences and corrects, at most twice, before the verdict (ADR-0041).
            files, golden_run, golden, rounds = await correct(
                ctx, cast(CorrectionPort, self.port), backend, sandbox, design, use_case, master, defaults, files,
                traced, lambda run: outcomes(run, case_rules), golden_run, golden, source, rules, engine=engine,
            )  # fmt: skip
        found: list[Any] = [
            checks.tests_ran(golden_run.build.passed, golden_run.build.failed, bool(golden_run.build.junit_xml)),
        ]
        target_files: dict[str, list[str]] = {}
        for path, implemented in traced.items():
            for rule in implemented:
                target_files.setdefault(rule, []).append(path)
        # The module answers for the rules its program exercises; the others are said, not counted.
        inside, outside = split_rules(rules, scope_files(source, master.program))
        traces = checks.trace_rules(inside, golden, target_files)
        traced_check, optional = checks.rules_traced(traces)
        found.append(traced_check)
        masks = [f"{m.path} ({m.when}): {m.reason}" for m in golden_run.masks]
        behaviour = (
            checks.Check("same_behaviour", "failed", f"the harness did not run: {golden_run.problem}")
            if golden_run.problem
            else checks.same_behaviour(golden, masks)
        )
        found.append(behaviour)

        fresh, unavailable = await self._fresh(ctx, backend, source, master, design, use_case, files, sandbox,
                                               defaults, engine)  # fmt: skip
        found.append(checks.fresh_inputs(fresh, unavailable))
        if behaviour.status == "passed":
            found.append(checks.canary(await self._canary(ctx, backend, design, use_case, master, files, sandbox,
                                                          defaults, engine)))  # fmt: skip
        else:  # red before any change: a caught canary would prove nothing
            found.append(checks.Check("canary", "not_checked", "the unchanged code does not reproduce the golden "
                                      "master, so a deliberate change cannot be told apart"))  # fmt: skip
        found.append(checks.source_intact(master.source_sha256, source_digest(source)))
        # ADR-0055: where the equivalence was measured. Until the comparison runs on the final state of the database
        # with the called programs real, the verdict says so and stays PARTLY PROVEN.
        work = unit_of_work(source, master.program)
        # The unit of work stays a gap until the final state is compared on the legacy's engine (phase E):
        # a design that declares it and a pack that generates its boundary do not prove the target keeps it.
        found.append(checks.behaviour_boundary(
            stubbed_programs(master), [line for line, _ in work],
            rollbacks_without_case(work, master), state_compared=engine is not None,
        ))  # fmt: skip
        if master.coverage is not None:  # ADR-0050: the legacy covered, or each gap with a signed decision
            found.append(checks.legacy_covered(gaps, decision.option if decision else None,
                                               decision.by if decision else None,
                                               decision.comment if decision else ""))  # fmt: skip

        not_proven = [f"Declared mask {m}" for m in masks] + optional
        not_proven += [f"Correction round {r.number} ({', '.join(r.changed) or 'no file'}): {r.note}" for r in rounds]
        not_proven += [f"{r.id} is outside {master.program} and its golden master: it is verified with the module "
                       "that runs its code" for r in outside]  # fmt: skip
        if stubbed_programs(master):
            not_proven.append("External programs are replaced by stubs that answer as the case says; their own logic "
                              "and their effects on the database are not verified here (ADR-0055)")  # fmt: skip
        not_proven += [f"{rule}: declared unreachable by the test engineer, no case enters it ({why})"
                       for rule, why in sorted(master.unreachable.items())]  # fmt: skip
        if master.coverage is not None:  # ADR-0047: the branches of the legacy no case exercised are not proven
            missed = master.coverage.not_exercised
            not_proven.append(f"Legacy coverage: {master.coverage.note()}")
            not_proven += [f"Branch not exercised by any case: lines {b.line_start}-{b.line_end} ({b.kind})"
                           for b in missed[:50]]  # fmt: skip
        not_proven += engine_not_proven(master)  # M28: engine quirks no case reaches, combinations without a case
        if master.from_traces:
            not_proven.append(
                "The legacy did not run on the platform: its behaviour comes from recorded traces, so "
                "only the traced cases are compared and fresh inputs are not (PARTLY PROVEN at most)"
            )
        # M29 (ADR-0049): the target code no golden case runs may be logic the legacy does not have; listed, never
        # blocking. Measured only when the sandbox image carries the coverage tool of the stack.
        measured = target_coverage(golden_run.build.after_output)
        extra: dict[str, Any] = {"MASKS.json": masks, "SOURCE.json": {"sha256": source_digest(source),
                                                                      "engine": master.engine}}  # fmt: skip
        if measured is not None:
            not_proven += target_not_run(measured)
            extra["TARGET_COVERAGE.json"] = measured.as_json()
        verdict = checks.compute(use_case.name, found, not_proven)
        pack = build_proof_pack(verdict, golden, fresh, traces, golden_run.build.junit_xml, extra)
        key = await self.port.save_verdict(verdict, pack)
        await self._ship_golden_master(backend, design, use_case, golden_run, master, defaults, engine, verdict)
        passed = sum(1 for c in verdict.checks if c.status == "passed")
        summary = f"{use_case.name}: {verdict.verdict} ({passed} of {len(verdict.checks)} checks passed)"
        front = await self._frontend(ctx)
        if front:
            summary += f"; {front}"
        iac = await infrastructure.verify(ctx, self.port)
        if iac:
            summary += f"; {iac}"
        return {"summary": summary, "verdict": verdict.verdict, "proof_pack": key}

    async def _ship_golden_master(
        self, backend: BackendPack, design: Design, use_case: UseCase, golden_run: EquivalenceRun,
        master: GoldenMaster, defaults: dict[str, Any], engine: Any | None, verdict: Verdict,
    ) -> None:  # fmt: skip
        """ADR-0056 (phase E): the delivery carries the evidence. The verdict as a document and, when the pack
        knows how, the golden master as an integration test of the project (the harness, the cases, what the
        platform observed), so the customer runs it on a test engine of the legacy and sees the same."""
        if not hasattr(self.port, "save_artifacts"):
            return
        shipped: dict[str, str] = {}
        ship = getattr(backend, "delivery_files", None)
        if callable(ship):
            shipped.update(ship(design, use_case, golden_run, master, defaults, engine))
        shipped[VERDICT_DOC] = json.dumps(verification_document(verdict), ensure_ascii=False, indent=1, default=str)
        layers = {p: "docs" if p.startswith("docs/") else backend.layer_of(p, design) for p in shipped}
        await self.port.save_artifacts(shipped, layers, {})

    async def _frontend(self, ctx: PhaseContext) -> str:
        """The frontend's own verdict (ADR-0016): rebuilt from the stored files and checked screen by screen."""
        if not hasattr(self.port, "load_frontend"):
            return ""
        flavour = frontend.flavour_of(ctx.run.target)
        files = await self.port.load_frontend()
        if flavour is None or not files:
            return ""
        screens = [contract_of(s) for s in await self.port.load_screens()]
        await ctx.store.event("started", "running", f"The {flavour} frontend: build and harness", phase=ctx.phase.key)
        run = await build_and_test(self.port.sandbox(FRONTEND_IMAGE), flavour, files, screens)
        not_proven = [
            "Screens are tested in jsdom: colour contrast and real-browser rendering are not measured",
            "The backend is simulated in the harness: the pages' calls are recorded, not executed",
        ]
        verdict = checks.compute(f"frontend-{flavour}", frontend.frontend_checks(run), not_proven,
                                 required=checks.FRONTEND_CHECKS)  # fmt: skip
        await self.port.save_verdict(verdict, frontend_proof_pack(verdict, run))
        passed = sum(1 for c in verdict.checks if c.status == "passed")
        return f"frontend-{flavour}: {verdict.verdict} ({passed} of {len(verdict.checks)} checks passed)"

    async def _fresh(
        self, ctx: PhaseContext, pack: BackendPack, source: list[SourceFile], master: GoldenMaster, design: Design,
        use_case: UseCase, files: dict[str, str], sandbox: Sandbox, defaults: dict[str, Any],
        engine: Any | None = None,
    ) -> tuple[list[CaseOutcome] | None, str]:  # fmt: skip
        if master.from_traces:
            return None, ("the golden master comes from recorded traces and the legacy does not run here, so fresh "
                          "inputs cannot be observed on it (ADR-0015)")  # fmt: skip
        runner = self.port.legacy_runner()
        if runner is None:
            return None, "there is no engine to run the legacy with fresh inputs"
        suite = Suite(program=master.program, schema_=master.schema_, cases=[r.case for r in master.results])
        fresh = fresh_suite(suite)
        try:
            legacy = await runner.run(source, fresh)
        except LegacyUnavailableError as exc:
            return None, f"the legacy could not run fresh inputs: {exc}"[:500]
        await ctx.store.event("info", "running", f"{len(fresh.cases)} fresh inputs ran on the legacy",
                              phase=ctx.phase.key)  # fmt: skip
        run = await pack.run_equivalence(sandbox, files, design, use_case, legacy, defaults, engine=engine)
        if run.problem:
            return None, f"the fresh inputs could not run on the target: {run.problem}"[:500]
        return outcomes(run, {r.case.name: r.case.rules for r in legacy.results}), ""

    async def _canary(
        self, ctx: PhaseContext, pack: BackendPack, design: Design, use_case: UseCase, master: GoldenMaster,
        files: dict[str, str], sandbox: Sandbox, defaults: dict[str, Any], engine: Any | None = None,
    ) -> list[dict[str, Any]]:  # fmt: skip
        target = pack.service_path(design, use_case)
        attempts: list[dict[str, Any]] = []
        for mutation in pack.mutations(files.get(target, "")):
            run = await pack.run_equivalence(sandbox, {**files, target: mutation.source}, design, use_case, master,
                                             defaults, engine=engine)  # fmt: skip
            failing = [f"test {t.name}" for t in run.build.tests if t.status == "failed"]
            if not run.build.compiled:
                failing = ["the compiler"]
            failing += [f"case {c.name}" for c in run.cases if c.failure or c.expected != c.actual]
            attempts.append({"file": target, "line": mutation.line, "before": mutation.before,
                             "after": mutation.after, "caught_by": failing[0] if failing else ""})  # fmt: skip
            outcome = f"caught by {failing[0]}" if failing else "not caught"
            await ctx.store.event("info", "running", f"Canary line {mutation.line}: {outcome}", phase=ctx.phase.key)
            if failing:
                break
        return attempts
