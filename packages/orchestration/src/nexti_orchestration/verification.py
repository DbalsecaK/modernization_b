"""Independent verification (spec 6.1 phase 11, 11.3): the validator redoes the work instead of trusting the
builder's notes. For every module it builds the generated project again from the stored files, replays the golden
master and fresh inputs on it, runs the canary and checks the legacy is intact; `nexti_verification` computes the
verdict from that evidence with fixed rules. No model takes part. The proof pack is stored; a person signs off at C4.
"""

import io
import json
import zipfile
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from nexti_adapter_sybase.golden import parameter_defaults
from nexti_core.adapters import LegacyRunner, LegacyUnavailableError, SourceFile
from nexti_core.spec.characterization import GoldenMaster, Suite, source_digest
from nexti_core.spec.model import Rule
from nexti_core.spec.screens import ScreenSpec
from nexti_orchestration import frontend
from nexti_orchestration.context import Attempt, PhaseContext
from nexti_orchestration.model import PhaseFailedError, PhaseResult
from nexti_orchestration.scope import scope_files, split_rules
from nexti_pack_frontend import IMAGE as FRONTEND_IMAGE
from nexti_pack_frontend import contract_of
from nexti_pack_frontend.build import FrontendRun, build_and_test
from nexti_pack_spring_boot import IMAGE, Design, UseCase, service_path
from nexti_pack_spring_boot.canary import mutations
from nexti_pack_spring_boot.equivalence import EquivalenceRun, run_equivalence
from nexti_sandbox import Sandbox
from nexti_verification import Verdict, build_proof_pack, differences, fresh_suite
from nexti_verification import verdict as checks
from nexti_verification.proof_pack import verification_document
from nexti_verification.verdict import CaseOutcome

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


def _module(design: Design, master: GoldenMaster) -> UseCase:
    short = master.program.rsplit(".", 1)[-1].lower()
    matching = [u for u in design.use_cases if (u.legacy_program or "").rsplit(".", 1)[-1].lower() == short]
    if matching:
        return matching[0]
    if len(design.use_cases) == 1:
        return design.use_cases[0]
    raise PhaseFailedError(f"No use case of the design replaces {master.program}")


class VerificationPhases:
    def __init__(self, port: VerificationPort) -> None:
        self.port = port

    async def verification(self, ctx: PhaseContext) -> PhaseResult:
        async def work() -> Attempt:
            return Attempt(await self._verify(ctx), "verdict")

        attempt = await ctx.invoke(VALIDATOR, work, what="Independent verification")
        return PhaseResult(summary=attempt.artifact["summary"])

    async def _verify(self, ctx: PhaseContext) -> dict[str, Any]:
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
        sandbox = self.port.sandbox(IMAGE)
        defaults = parameter_defaults(source, master.program)
        case_rules = {r.case.name: r.case.rules for r in master.results}

        await ctx.store.event("started", "running", "Clean build, tests and golden master on the target",
                              phase=ctx.phase.key)  # fmt: skip
        golden_run = await run_equivalence(sandbox, files, design, use_case, master, defaults)
        golden = outcomes(golden_run, case_rules)
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

        fresh, unavailable = await self._fresh(ctx, source, master, design, use_case, files, sandbox, defaults)
        found.append(checks.fresh_inputs(fresh, unavailable))
        if behaviour.status == "passed":
            found.append(checks.canary(await self._canary(ctx, design, use_case, master, files, sandbox, defaults)))
        else:  # red before any change: a caught canary would prove nothing
            found.append(checks.Check("canary", "not_checked", "the unchanged code does not reproduce the golden "
                                      "master, so a deliberate change cannot be told apart"))  # fmt: skip
        found.append(checks.source_intact(master.source_sha256, source_digest(source)))

        not_proven = [f"Declared mask {m}" for m in masks] + optional
        not_proven += [f"{r.id} is outside {master.program} and its golden master: it is verified with the module "
                       "that runs its code" for r in outside]  # fmt: skip
        not_proven.append("External programs are replaced by stubs that answer as the case says; their own logic "
                          "is not verified here")  # fmt: skip
        if master.from_traces:
            not_proven.append(
                "The legacy did not run on the platform: its behaviour comes from recorded traces, so "
                "only the traced cases are compared and fresh inputs are not (PARTLY PROVEN at most)"
            )
        verdict = checks.compute(use_case.name, found, not_proven)
        pack = build_proof_pack(verdict, golden, fresh, traces, golden_run.build.junit_xml,
                                {"MASKS.json": masks, "SOURCE.json": {"sha256": source_digest(source),
                                                                     "engine": master.engine}})  # fmt: skip
        key = await self.port.save_verdict(verdict, pack)
        passed = sum(1 for c in verdict.checks if c.status == "passed")
        summary = f"{use_case.name}: {verdict.verdict} ({passed} of {len(verdict.checks)} checks passed)"
        front = await self._frontend(ctx)
        if front:
            summary += f"; {front}"
        return {"summary": summary, "verdict": verdict.verdict, "proof_pack": key}

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
        self, ctx: PhaseContext, source: list[SourceFile], master: GoldenMaster, design: Design, use_case: UseCase,
        files: dict[str, str], sandbox: Sandbox, defaults: dict[str, Any],
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
        run = await run_equivalence(sandbox, files, design, use_case, legacy, defaults)
        if run.problem:
            return None, f"the fresh inputs could not run on the target: {run.problem}"[:500]
        return outcomes(run, {r.case.name: r.case.rules for r in legacy.results}), ""

    async def _canary(
        self, ctx: PhaseContext, design: Design, use_case: UseCase, master: GoldenMaster, files: dict[str, str],
        sandbox: Sandbox, defaults: dict[str, Any],
    ) -> list[dict[str, Any]]:  # fmt: skip
        target = service_path(design, use_case)
        attempts: list[dict[str, Any]] = []
        for mutation in mutations(files.get(target, "")):
            run = await run_equivalence(sandbox, {**files, target: mutation.source}, design, use_case, master,
                                        defaults)  # fmt: skip
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
