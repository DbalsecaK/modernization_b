"""Flow 4, independent validation of a third party's migration (spec 3.3, ADR-0025). The legacy goes through
inventory, rule extraction with review (C1) and characterization as in Flow 1; then:

- targetIntake: the target is read by code (endpoints, tables, slices); its vendor's mapping is taken, or one is
  proposed from names with the gaps a person must complete;
- mapping: the mapping is checked against the golden master and the target; a person approves it at C2;
- targetRules: the rule extractors read the target's services; the rules are compared with the approved ones of the
  legacy (complementary evidence for the report);
- validation: the golden master, and fresh inputs when the legacy runs, are played on the target in the sandbox; the
  verdict is computed by code (IVV_CHECKS) and a person signs off at C4;
- report: the IV&V report for the customer and the vendor.
"""

import io
import json
import re
import zipfile
from collections.abc import Sequence
from dataclasses import asdict
from typing import Any, Protocol

from nexti_core.adapters import LegacyRunner, LegacyUnavailableError, SliceView, SourceFile
from nexti_core.spec.characterization import GoldenMaster, Suite, source_digest
from nexti_core.spec.model import Rule
from nexti_ivv import mapping as ivv_mapping
from nexti_ivv.runner import IMAGE, IvvRun, run
from nexti_ivv.target import TargetInventory, inventory
from nexti_orchestration.context import Attempt, PhaseContext
from nexti_orchestration.extraction import EXTRACTOR, ModelCaller, ReplyError, consolidate, extract
from nexti_orchestration.model import PhaseFailedError, PhaseResult
from nexti_orchestration.usage import total
from nexti_sandbox import Sandbox
from nexti_verification import Verdict, fresh_suite
from nexti_verification import verdict as checks
from nexti_verification.proof_pack import verification_document
from nexti_verification.verdict import CaseOutcome

INVENTORY = "ivv/target-inventory.json"
MAPPING = "ivv/mapping.yaml"
GAPS = "ivv/mapping-gaps.json"
TARGET_RULES = "ivv/target-rules.json"
COMPARISON = "ivv/rules-comparison.json"
REPORT = "ivv/REPORT.md"
VALIDATOR = "equivalence-validator"


class IvvPort(Protocol):
    models: ModelCaller

    async def source_files(self) -> list[SourceFile]: ...

    async def target_archive(self) -> dict[str, bytes]:
        """Every file of the newest target archive (sources and the runnable artifact), by path."""
        ...

    async def load_rules(self) -> list[Rule]: ...

    async def load_golden_master(self) -> GoldenMaster | None: ...

    def legacy_runner(self) -> LegacyRunner | None: ...

    def sandbox(self, image: str) -> Sandbox: ...

    async def save_artifacts(
        self, files: dict[str, str], layers: dict[str, str], rules: dict[str, list[str]]
    ) -> None: ...

    async def load_artifact(self, path: str) -> str | None:
        """The newest version of a file the pipeline stored (generated_artifact), or None."""
        ...

    async def save_verdict(self, verdict: Verdict, proof_pack: bytes) -> str: ...


def _texts(archive: dict[str, bytes]) -> list[SourceFile]:
    found = []
    for path, data in archive.items():
        if path.endswith((".jar", ".class", ".war", ".zip", ".png", ".jpg")):
            continue
        try:
            found.append(SourceFile(path, data.decode("utf-8")))
        except UnicodeDecodeError:
            continue
    return found


def _inventory(archive: dict[str, bytes]) -> TargetInventory:
    return inventory(_texts(archive), [p for p in archive if p.endswith(".jar")])


def _words(rule: dict[str, Any] | Rule) -> set[str]:
    data = rule.model_dump() if isinstance(rule, Rule) else rule
    text = " ".join(str(data.get(k) or "") for k in ("name", "statement", "condition", "action"))
    return {w for w in re.findall(r"[a-z0-9.]+", text.lower()) if len(w) > 2}


def compare_rules(legacy: Sequence[Rule], target: Sequence[Rule]) -> dict[str, Any]:
    """Each legacy rule and the target rule most like it (shared words and literals); the target rules left over are
    behaviour the legacy did not have. Evidence for the report: the execution decides the verdict."""
    pairs, used = [], set()
    for rule in legacy:
        words = _words(rule)
        best, score = None, 0.0
        for index, other in enumerate(target):
            theirs = _words(other)
            shared = len(words & theirs) / max(1, min(len(words), len(theirs)))
            if shared > score:
                best, score = index, shared
        matched = best is not None and score >= 0.4
        if matched and best is not None:
            used.add(best)
        pairs.append({"legacy": rule.id, "name": rule.name, "target": target[best].name if matched and best is not None
                      else None, "similarity": round(score, 2)})  # fmt: skip
    extra = [r.name for i, r in enumerate(target) if i not in used]
    return {"present": [p for p in pairs if p["target"]], "missing": [p for p in pairs if not p["target"]],
            "extra": extra}  # fmt: skip


def proof_pack(verdict: Verdict, run_: IvvRun, fresh: IvvRun | None, mapping_text: str,
               comparison: dict[str, Any] | None) -> bytes:  # fmt: skip
    def cases(found: IvvRun | None) -> list[dict[str, Any]] | None:
        if found is None:
            return None
        return [{"case": c.name, "rules": list(c.rules), "matched": c.matched, "error": c.error,
                 "differences": [asdict(d) for d in c.differences],
                 "expected": c.expected.model_dump(mode="json"),
                 "actual": c.actual.model_dump(mode="json") if c.actual else None} for c in found.cases]  # fmt: skip

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("VERIFICATION.json", json.dumps(verification_document(verdict), indent=2))
        archive.writestr("EQUIVALENCE.json", json.dumps({"golden_master": cases(run_), "fresh_inputs": cases(fresh),
                                                         "target": run_.diagnostic}, indent=2))  # fmt: skip
        archive.writestr("TRACE.json", json.dumps([], indent=2))
        archive.writestr("MAPPING.yaml", mapping_text)
        if comparison is not None:
            archive.writestr("RULES-COMPARED.json", json.dumps(comparison, indent=2))
    return buffer.getvalue()


def report(verdict: Verdict, run_: IvvRun, comparison: dict[str, Any] | None, target: TargetInventory) -> str:
    lines = [
        f"# Independent validation report: {verdict.module.removeprefix('ivv-')}",
        "",
        f"Verdict computed by code: **{verdict.verdict}** (ADR-0025). PROVEN is evidence, not approval.",
        "",
        f"Target: {target.stack}, {len(target.endpoints)} endpoint(s), {len(target.tables)} table(s).",
        "",
        "## Checks",
        "",
        "| Check | Status | Detail |",
        "|---|---|---|",
    ]
    lines += [f"| {c.key} | {c.status} | {c.detail} |" for c in verdict.checks]
    lines += ["", "## Golden cases on the target", "", "| Case | Result | First difference |", "|---|---|---|"]
    for c in run_.cases:
        first = c.error or (f"{c.differences[0].path}: {c.differences[0].expected} != {c.differences[0].actual}"
                            if c.differences else "")  # fmt: skip
        lines.append(f"| {c.name} | {'reproduced' if c.matched else 'differs'} | {first} |")
    if comparison is not None:
        lines += ["", "## Rules of the two codes", "",
                  f"{len(comparison['present'])} legacy rule(s) found in the target, "
                  f"{len(comparison['missing'])} not found, {len(comparison['extra'])} target rule(s) without a "
                  "legacy counterpart (compared by their words; the execution above decides).", ""]  # fmt: skip
        lines += [f"- Not found: {m['legacy']} {m['name']}" for m in comparison["missing"]]
        lines += [f"- Extra in the target: {name}" for name in comparison["extra"]]
    if verdict.not_proven:
        lines += ["", "## Not proven", ""] + [f"- {note}" for note in verdict.not_proven]
    return "\n".join(lines) + "\n"


class IvvPhases:
    def __init__(self, port: IvvPort) -> None:
        self.port = port

    async def _target(self) -> tuple[dict[str, bytes], TargetInventory]:
        archive = await self.port.target_archive()
        if not archive:
            raise PhaseFailedError("There is no target archive: upload the third party's code (target_archive)")
        return archive, _inventory(archive)

    async def target_intake(self, ctx: PhaseContext) -> PhaseResult:
        archive, found = await self._target()
        if found.stack == "unknown":
            raise PhaseFailedError("The target's stack is not recognized (Spring Boot or ASP.NET Core)")
        master = await self.port.load_golden_master()
        if master is None:
            raise PhaseFailedError("The golden master of the legacy is needed before the target is mapped")
        files = {INVENTORY: json.dumps(asdict(found), indent=2, default=list)}
        if ivv_mapping.FILE in archive:
            mapping = ivv_mapping.load(archive[ivv_mapping.FILE].decode("utf-8"))
            gaps: list[str] = []
            origin = "the vendor's ivv-mapping.yaml"
        else:
            mapping, gaps = ivv_mapping.propose(master, found)
            origin = "a proposal from equal names"
        files[MAPPING] = ivv_mapping.dump(mapping)
        files[GAPS] = json.dumps(gaps, indent=2)
        await self.port.save_artifacts(files, dict.fromkeys(files, "docs"), {})
        return PhaseResult(summary=f"{found.stack}: {len(found.endpoints)} endpoint(s), {len(found.tables)} table(s), "
                                   f"{len(found.slices)} slice(s); mapping from {origin}"
                                   + (f", {len(gaps)} gap(s) to complete" if gaps else ""))  # fmt: skip

    async def mapping(self, ctx: PhaseContext) -> PhaseResult:
        """The mapping is checked; a person corrects it if needed and approves it at C2."""
        _, found = await self._target()
        master = await self.port.load_golden_master()
        text = await self.port.load_artifact(MAPPING)
        if master is None or text is None:
            raise PhaseFailedError("The mapping and the golden master are needed")
        problems = ivv_mapping.problems(ivv_mapping.load(text), master, found)
        if problems:
            await ctx.store.event("info", "running", f"The mapping has {len(problems)} problem(s) to fix before C2: "
                                  + "; ".join(problems[:3]), phase=ctx.phase.key)  # fmt: skip
            return PhaseResult(summary=f"{len(problems)} problem(s) in the mapping: correct it before approving C2")
        return PhaseResult(summary="The mapping covers every input, output, table and call: ready for C2")

    async def target_rules(self, ctx: PhaseContext) -> PhaseResult:
        archive, found = await self._target()
        sources = {f.path: f.text for f in _texts(archive)}
        views = [SliceView(s.unit, s.file, ((s.first, s.last),)) for s in found.slices if s.file in sources]
        if not views:
            return PhaseResult(summary="The target has no service methods to read")
        keys = {a.key for a in ctx.run.agents}
        extractor = EXTRACTOR if EXTRACTOR in keys or not keys else next(iter(sorted(keys)))

        async def one(shard_ctx: PhaseContext) -> list[dict[str, Any]]:
            view = next(v for v in views if v.unit == shard_ctx.shard)

            async def work() -> Attempt:
                try:
                    got = await extract(self.port.models, view, sources[view.file], {},
                                        max_iterations=ctx.run.max_iterations)  # fmt: skip
                except ReplyError as exc:
                    raise PhaseFailedError(str(exc)[:1500]) from exc
                return Attempt([r.model_dump(mode="json") for r in got.rules], f"{len(got.rules)} rule(s)",
                               total(got.usage))  # fmt: skip

            attempt = await shard_ctx.invoke(extractor, work, what=f"Rules of the target's {view.unit}")
            return list(attempt.artifact)

        batches = await ctx.fan_out([v.unit for v in views], one)
        target_rules = consolidate([Rule.model_validate(r) for batch in batches for r in batch])
        legacy = await self.port.load_rules()
        comparison = compare_rules(legacy, target_rules)
        await self.port.save_artifacts(
            {TARGET_RULES: json.dumps([r.model_dump(mode="json") for r in target_rules], indent=2),
             COMPARISON: json.dumps(comparison, indent=2)},
            {TARGET_RULES: "docs", COMPARISON: "docs"}, {},
        )  # fmt: skip
        return PhaseResult(summary=f"{len(target_rules)} rule(s) in the target; {len(comparison['present'])} of "
                                   f"{len(legacy)} legacy rule(s) found, {len(comparison['extra'])} extra")  # fmt: skip

    async def validation(self, ctx: PhaseContext) -> PhaseResult:
        async def work() -> Attempt:
            return Attempt(await self._validate(ctx), "verdict")

        attempt = await ctx.invoke(VALIDATOR, work, what="Independent validation of the target")
        return PhaseResult(summary=attempt.artifact["summary"])

    async def _validate(self, ctx: PhaseContext) -> dict[str, Any]:
        archive, found = await self._target()
        master = await self.port.load_golden_master()
        text = await self.port.load_artifact(MAPPING)
        if master is None or text is None:
            raise PhaseFailedError("The golden master and the approved mapping are needed")
        mapping = ivv_mapping.load(text)
        problems = ivv_mapping.problems(mapping, master, found)
        sandbox = self.port.sandbox(IMAGE)
        await ctx.store.event("started", "running", "The golden master on the target, in the sandbox",
                              phase=ctx.phase.key)  # fmt: skip
        golden = await run(sandbox, archive, found, mapping, master) if not problems else IvvRun(False, "not run")
        fresh, unavailable = await self._fresh(sandbox, archive, found, mapping, master) if golden.ready else (None, "")
        rules = await self.port.load_rules()
        outcomes = [CaseOutcome(c.name, c.rules, c.differences, c.error) for c in golden.cases]
        masks = [f"{m.path} ({m.when}): {m.reason}" for p in mapping.programs for m in p.masks]
        source = await self.port.source_files()
        found_checks = [
            checks.target_runs(golden.ready, golden.diagnostic),
            checks.contract_mapped(problems, approved=True),
            checks.same_behaviour(outcomes, masks) if golden.ready else checks.Check(
                "same_behaviour", "failed", "the target did not run the golden master"),
            checks.fresh_inputs([CaseOutcome(c.name, c.rules, c.differences, c.error) for c in fresh.cases]
                                if fresh else None, unavailable),
            checks.rules_covered(checks.trace_rules(rules, outcomes, {})),
            checks.source_intact(master.source_sha256, source_digest(source)),
        ]  # fmt: skip
        not_proven = [
            "The target is exercised through its HTTP endpoint and its tables: paths no case reaches are not observed",
            "External services are stubs that answer as each case says",
        ]
        if master.from_traces:
            not_proven.append("The legacy's behaviour comes from recorded traces: only the traced cases are compared")
        module = f"ivv-{master.program.rsplit('.', 1)[-1].lower()}"
        verdict = checks.compute(module, found_checks, not_proven, required=checks.IVV_CHECKS)
        comparison_text = await self.port.load_artifact(COMPARISON)
        comparison = json.loads(comparison_text) if comparison_text else None
        key = await self.port.save_verdict(verdict, proof_pack(verdict, golden, fresh, text, comparison))
        await self.port.save_artifacts({REPORT: report(verdict, golden, comparison, found)}, {REPORT: "docs"}, {})
        passed = sum(1 for c in verdict.checks if c.status == "passed")
        return {"summary": f"{module}: {verdict.verdict} ({passed} of {len(verdict.checks)} checks passed)",
                "verdict": verdict.verdict, "proof_pack": key}  # fmt: skip

    async def _fresh(self, sandbox: Sandbox, archive: dict[str, bytes], found: TargetInventory,
                     mapping: ivv_mapping.Mapping, master: GoldenMaster) -> tuple[IvvRun | None, str]:  # fmt: skip
        if master.from_traces:
            return None, "the golden master comes from recorded traces: fresh inputs cannot be observed on the legacy"
        runner = self.port.legacy_runner()
        if runner is None:
            return None, "there is no engine to run the legacy with fresh inputs"
        suite = fresh_suite(
            Suite(program=master.program, schema_=master.schema_, cases=[r.case for r in master.results])
        )
        try:
            legacy = await runner.run(await self.port.source_files(), suite)
        except LegacyUnavailableError as exc:
            return None, f"the legacy could not run fresh inputs: {exc}"[:500]
        expected = {r.case.name: r.observation for r in legacy.results}
        cases = [r.case for r in legacy.results if not r.observation.error]
        return await run(sandbox, archive, found, mapping, master, cases, expected), ""

    async def report(self, ctx: PhaseContext) -> PhaseResult:
        text = await self.port.load_artifact(REPORT)
        if text is None:
            raise PhaseFailedError("There is no validation to report")
        verdict = re.search(r"\*\*(PROVEN|PARTLY PROVEN|NOT PROVEN)\*\*", text)
        return PhaseResult(summary=f"IV&V report ready ({verdict.group(1) if verdict else 'no verdict'}): "
                                   "download it from Code or the proof pack from Validation")  # fmt: skip
