"""Executors of Flow 2, the building half (spec 7.2 phases 4, 8 and 9; 7.5, 11.4; ADR-0018): the specification review
before C1, the validation that computes the verdict by code, and the delivery. UI, design and generation are the
executors of Flow 1, which read the specification of Flow 2 when the run is a newFeature run.

Validation redoes the work instead of trusting the builder: it builds the stored project again in the pack's sandbox,
checks every acceptance criterion has a passing test that carries its id, every operation of the contract has its
endpoint, a deliberate one-line change turns a test red, no question is open and every element is traced to the
lines of an accepted input. No model takes part; a person signs off at C4.
"""

import io
import json
import re
import zipfile
from collections.abc import Sequence
from typing import Any, Protocol

from nexti_core.spec.coverage import StoryLinks, compute
from nexti_core.spec.design import Design
from nexti_core.spec.model import Rule
from nexti_core.spec.screens import ScreenSpec
from nexti_orchestration.context import Attempt, PhaseContext
from nexti_orchestration.feature import INPUTS, FeatureStory, citable, citation_problems
from nexti_orchestration.model import PhaseFailedError, PhaseResult
from nexti_orchestration.packs import BackendPack, backend_pack
from nexti_sandbox import Sandbox
from nexti_verification import Verdict
from nexti_verification import verdict as checks
from nexti_verification.proof_pack import verification_document

VALIDATOR = "acceptance-judge"
ACTIVE = ("draft", "review", "question", "approved")


class FeatureBuildPort(Protocol):
    async def load_rules(self) -> list[Rule]: ...

    async def load_screens(self) -> list[ScreenSpec]: ...

    async def load_stories(self) -> list[FeatureStory]: ...

    async def load_inputs(self) -> dict[str, str]: ...

    async def load_design(self) -> Design | None: ...

    async def load_generated(self) -> tuple[dict[str, str], dict[str, list[str]]]: ...

    async def open_questions(self) -> list[str]:
        """The text of the questions of the project still open."""
        ...

    async def save_verdict(self, verdict: Verdict, proof_pack: bytes) -> str: ...

    def sandbox(self, image: str) -> Sandbox: ...


def untraced(rules: Sequence[Rule], screens: Sequence[ScreenSpec], stories: Sequence[FeatureStory],
             inputs: dict[str, str]) -> list[str]:  # fmt: skip
    """Elements that do not reach the lines of an accepted input: rules and screens by their citations, stories by
    the elements they link."""
    files = citable({p.removeprefix(INPUTS): t for p, t in inputs.items()})
    missing: list[str] = []
    traced: set[str] = set()
    cited: list[tuple[str, Sequence[Any]]] = [(r.id, list(r.sources)) for r in rules]
    cited += [(s.id, list(s.sources)) for s in screens]
    for element, sources in cited:
        refs, problems = citation_problems(sources, files, element)
        if refs and not problems:
            traced.add(element)
        else:
            missing.append(element)
    for story in stories:
        if story.status in ACTIVE and not (set(story.links) & traced):
            missing.append(story.key)
    return missing


def endpoint_missing(design: Design, files: dict[str, str]) -> tuple[list[str], list[str]]:
    """The operations of the contract and the ones without their endpoint in the generated controllers."""
    operations: list[str] = []
    missing: list[str] = []
    controllers = {p: c for p, c in files.items() if re.search(r"Controller\.(java|cs|kt|ts)$", p)}
    for use_case in design.use_cases:
        path = use_case.path or "/" + re.sub(r"(?<!^)(?=[A-Z])", "-", use_case.name).lower()
        operation = f"{use_case.http_method} /api/{design.context}{path}"
        operations.append(operation)
        found = any(f"{use_case.name}Controller" in c and (f'"{path}"' in c or f'"{path.lstrip("/")}"' in c)
                    and use_case.http_method.lower() in c.lower() for c in controllers.values())  # fmt: skip
        if not found:
            missing.append(operation)
    return operations, missing


def proof_pack(verdict: Verdict, junit: str | None, extra: dict[str, Any]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("VERIFICATION.json", json.dumps(verification_document(verdict), indent=2))
        if junit:
            archive.writestr("junit.xml", junit)
        for name, value in extra.items():
            archive.writestr(name, json.dumps(value, indent=2, ensure_ascii=False))
    return buffer.getvalue()


class FeatureBuildPhases:
    def __init__(self, port: FeatureBuildPort) -> None:
        self.port = port

    # -- specification review (before C1) ------------------------------------------------------------------------
    async def spec_review(self, ctx: PhaseContext) -> PhaseResult:
        rules = await self.port.load_rules()
        screens = await self.port.load_screens()
        stories = await self.port.load_stories()
        coverage = compute([r.id for r in rules] + [s.id for s in screens],
                           [StoryLinks(s.key, s.status, frozenset(s.links)) for s in stories])  # type: ignore[arg-type]  # fmt: skip
        for gap in coverage.gaps:
            await ctx.store.event("info", "waiting", f"{gap} is in no active user story", phase=ctx.phase.key)
        active = [s for s in stories if s.status in ACTIVE]
        criteria = sum(len(s.criteria) for s in active)
        return PhaseResult(summary=f"{len(active)} user stories with {criteria} acceptance criteria cover "
                                   f"{len(coverage.covered)} of {len(rules) + len(screens)} rules and screens; "
                                   "ready for the product owner (C1)")  # fmt: skip

    # -- validation (C4) -----------------------------------------------------------------------------------------
    async def validation(self, ctx: PhaseContext) -> PhaseResult:
        async def work() -> Attempt:
            return Attempt(await self._validate(ctx), "verdict")

        attempt = await ctx.invoke(VALIDATOR, work, what="Validation of the functionality (Flow 2)")
        return PhaseResult(summary=attempt.artifact["summary"])

    async def _validate(self, ctx: PhaseContext) -> dict[str, Any]:
        design = await self.port.load_design()
        files, _ = await self.port.load_generated()
        if design is None or not files:
            raise PhaseFailedError("Validation needs the approved design and the generated code")
        pack = backend_pack(ctx.run.target)
        if pack is None:
            raise PhaseFailedError(f"The {ctx.run.target.get('backend')} pack is not available to validate with")
        rules, screens = await self.port.load_rules(), await self.port.load_screens()
        stories = [s for s in await self.port.load_stories() if s.status in ACTIVE]
        sandbox = self.port.sandbox(pack.image)
        await ctx.store.event("started", "running", "Clean build and tests on the target", phase=ctx.phase.key)
        build = await pack.compile_and_test(sandbox, files)
        found = [checks.tests_ran(build.passed, build.failed, bool(build.junit_xml))]
        passed = [t.name for t in build.tests if t.status == "passed"]
        rule_ids = {r.id for r in rules}
        by_tests = [(s.key, n, _name(c)) for s in stories if set(s.links) & rule_ids
                    for n, c in enumerate(s.criteria, start=1)]  # fmt: skip
        screen_only = [s.key for s in stories if not set(s.links) & rule_ids]
        found.append(checks.criteria_covered(by_tests, passed))
        operations, missing = endpoint_missing(design, files)
        found.append(checks.contracts(operations, missing))
        if build.ok and build.passed:
            found.append(checks.canary(await self._canary(ctx, pack, design, files, sandbox)))
        else:
            found.append(checks.Check("canary", "not_checked", "the unchanged code does not pass its tests, so a "
                                      "deliberate change cannot be told apart"))  # fmt: skip
        found.append(checks.questions_closed(await self.port.open_questions()))
        lost = untraced(rules, screens, stories, await self.port.load_inputs())
        found.append(checks.traced_to_inputs(len(rules) + len(screens) + len(stories), lost))
        not_proven = [
            "Acceptance criteria are checked through the service's tests; the running application (HTTP, database "
            "engine) is checked by the build, not end to end",
            "Visual fidelity against Figma is not measured pixel by pixel: the frontend verdict checks every screen "
            "and field of the specification",
        ]
        not_proven += [f"{key} only links screens: its criteria are covered by the frontend verdict" for key in
                       screen_only]  # fmt: skip
        module = design.context
        verdict = checks.compute(module, found, not_proven, required=checks.FEATURE_CHECKS)
        key = await self.port.save_verdict(verdict, proof_pack(verdict, build.junit_xml, {
            "CRITERIA.json": [{"story": s, "criterion": n, "scenario": name} for s, n, name in by_tests],
            "CONTRACT.json": {"operations": operations, "missing": missing},
        }))  # fmt: skip
        ok = sum(1 for c in verdict.checks if c.status == "passed")
        summary = f"{module}: {verdict.verdict} ({ok} of {len(verdict.checks)} checks passed)"
        if hasattr(self.port, "load_frontend"):
            from nexti_orchestration.verification import VerificationPhases

            front = await VerificationPhases(self.port)._frontend(ctx)  # type: ignore[arg-type]
            if front:
                summary += f"; {front}"
        return {"summary": summary, "verdict": verdict.verdict, "proof_pack": key}

    async def _canary(self, ctx: PhaseContext, pack: BackendPack, design: Design, files: dict[str, str],
                      sandbox: Sandbox) -> list[dict[str, Any]]:  # fmt: skip
        attempts: list[dict[str, Any]] = []
        for use_case in design.use_cases:
            target = pack.service_path(design, use_case)
            for mutation in pack.mutations(files.get(target, "")):
                build = await pack.compile_and_test(sandbox, {**files, target: mutation.source})
                failing = ["the compiler"] if not build.compiled else [
                    f"test {t.name}" for t in build.tests if t.status == "failed"]  # fmt: skip
                attempts.append({"file": target, "line": mutation.line, "before": mutation.before,
                                 "after": mutation.after, "caught_by": failing[0] if failing else ""})  # fmt: skip
                outcome = f"caught by {failing[0]}" if failing else "not caught"
                await ctx.store.event("info", "running", f"Canary line {mutation.line}: {outcome}", phase=ctx.phase.key)
                if failing:
                    return attempts
        return attempts

    # -- delivery -------------------------------------------------------------------------------------------------
    async def delivery(self, ctx: PhaseContext) -> PhaseResult:
        files, _ = await self.port.load_generated()
        if not files:
            raise PhaseFailedError("There is no generated code to deliver")
        return PhaseResult(summary=f"{len(files)} files ready to download from Code (ZIP); pushing to the customer "
                                   "repository is available with the delivery milestone")  # fmt: skip


def _name(criterion: str) -> str:
    first = criterion.strip().split("\n", 1)[0]
    return first.split(":", 1)[1].strip() if ":" in first else first
