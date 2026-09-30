"""Characterization (spec 6.1 phase 9): the test engineer designs the suite (legacy schema, cases, how external
programs answer); code checks it against the source and the rules; the legacy itself runs every case in its own
isolated engine and what it did is frozen as the golden master, before anything is generated. Nothing of the
expected behaviour comes from a model: the model only chooses the inputs."""

import json
from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import ValidationError

from nexti_agents import prompt
from nexti_core.adapters import LegacyRunner, LegacyUnavailableError, SourceFile
from nexti_core.spec.characterization import GoldenMaster, Suite
from nexti_core.spec.model import Rule
from nexti_orchestration.context import Attempt, PhaseContext, Verification
from nexti_orchestration.extraction import ModelCaller, ReplyError, parse_json
from nexti_orchestration.model import PhaseFailedError, PhaseResult, PhaseUnavailableError
from nexti_orchestration.scope import scope_files, split_rules

TESTER = "test-engineer"


class CharacterizationPort(Protocol):
    models: ModelCaller

    async def load_rules(self) -> list[Rule]: ...

    async def source_files(self) -> list[SourceFile]: ...

    async def inventory_digest(self) -> str: ...

    def legacy_runner(self) -> LegacyRunner | None: ...

    async def save_file(self, path: str, content: str) -> str:
        """A draft of the run in the object store; returns its reference."""
        ...

    async def load_file(self, reference: str) -> str: ...

    async def save_golden_master(self, master: GoldenMaster) -> None: ...


def parse_suite(content: str) -> Suite:
    try:
        return Suite.model_validate(parse_json(content))
    except ValidationError as exc:
        raise ReplyError(f"the suite does not follow the format: {exc.errors()[:5]}") from exc


def coverage_problems(suite: Suite, rules: Sequence[Rule], required: Sequence[Rule] | None = None) -> list[str]:
    """Every required rule needs a case (all of them unless a scope says otherwise); cases cite known rules only."""
    covered = {r for case in suite.cases for r in case.rules}
    known = {r.id for r in rules}
    problems = []
    missing = sorted({r.id for r in (rules if required is None else required)} - covered)
    if missing:
        problems.append(f"rules without a case: {', '.join(missing)}")
    unknown = sorted(covered - known)
    if unknown:
        problems.append(f"cases cite rules that do not exist: {', '.join(unknown)}")
    return problems


def _sources(files: Sequence[SourceFile]) -> str:
    return "\n\n".join(f"// {f.path}\n{f.text}" for f in files)


class CharacterizationPhases:
    def __init__(self, port: CharacterizationPort) -> None:
        self.port = port

    async def characterization(self, ctx: PhaseContext) -> PhaseResult:
        runner = self.port.legacy_runner()
        if runner is None:
            raise PhaseUnavailableError("There is no engine to run this legacy: characterization waits for one")
        rules = await self.port.load_rules()
        if not rules:
            raise PhaseFailedError("There are no approved rules to characterize")
        files = await self.port.source_files()
        request = [
            {"role": "system", "content": prompt("test-engineer-characterization")},
            {"role": "user", "content": (
                f"Inventory:\n{await self.port.inventory_digest()}\n\nRules:\n"
                f"{json.dumps([r.model_dump(mode='json') for r in rules], ensure_ascii=False, indent=1)}\n\n"
                f"Source:\n{_sources(files)}")},
        ]  # fmt: skip
        master: dict[str, GoldenMaster] = {}

        async def work(iteration: int, feedback: str | None) -> Attempt:
            messages = list(request)
            if feedback:
                messages.append({"role": "user", "content": f"The suite could not be used:\n{feedback}\nFix it."})
            reply = await self.port.models.complete(TESTER, "characterization", messages, iteration=iteration)
            try:
                suite = parse_suite(reply.content)
            except ReplyError as exc:  # verified below: the reply goes back with the reason
                return Attempt({"error": str(exc)[:3000]}, "suite with format errors", reply.usage)
            reference = await self.port.save_file("characterization/suite.json", suite.model_dump_json(by_alias=True))
            return Attempt({"suite": reference}, f"{len(suite.cases)} case(s)", reply.usage)

        async def verify(artifact: dict[str, Any]) -> Verification:
            if "error" in artifact:
                return Verification(False, artifact["error"])
            suite = Suite.model_validate_json(await self.port.load_file(artifact["suite"]))
            # Only the rules this program exercises (its code and what it calls) need a case; the others belong to
            # the golden master of another program.
            required, _ = split_rules(rules, scope_files(files, suite.program))
            problems = coverage_problems(suite, rules, required)
            if problems:
                return Verification(False, "; ".join(problems))
            try:
                recorded = await runner.run(files, suite)
            except ValueError as exc:  # the suite does not fit the code (GoldenError)
                return Verification(False, str(exc)[:3000])
            except LegacyUnavailableError as exc:  # no engine, or a replay without a recording: the run waits
                raise PhaseUnavailableError(str(exc)[:500]) from exc
            failed = [f"{r.case.name}: {r.observation.error}" for r in recorded.results if r.observation.error]
            if failed:
                return Verification(False, "the engine failed these cases:\n" + "\n".join(failed)[:3000])
            await self.port.save_golden_master(recorded)
            master["run"] = recorded
            return Verification(True)

        attempt = await ctx.do_verify_correct(TESTER, work, verify, what="Characterization suite")
        recorded = master.get("run")
        cases = attempt.summary
        if recorded is not None:
            rejected = sum(1 for r in recorded.results if r.observation.returns not in (0, None))
            cases = f"{len(recorded.results)} case(s) frozen, {rejected} of them rejected by the legacy"
        return PhaseResult(summary=f"Golden master: {cases} ({runner.engine})")
