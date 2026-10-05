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
from nexti_orchestration.extraction import ModelCaller, ReplyError, parse_json, raise_if_cut
from nexti_orchestration.guided import enabled as guided_enabled
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


FORMAT = (
    'The format: {"program": name, "schema": {"tables": [{"name", "columns": [{"name", "type", '
    '"nullable"}], "key": [column names]}]}, "cases": [...]}; a column has only name, type and nullable; the '
    "key is a list of column names on the table"
)


def format_problems(exc: ValidationError, limit: int = 8) -> str:
    """The validation errors as the model can act on them: where, what, and what the format allows there."""
    lines = []
    for error in exc.errors()[:limit]:
        path = ".".join(str(part) for part in error["loc"])
        if error["type"] == "extra_forbidden":
            lines.append(
                f"{path}: '{error['loc'][-1]}' is not a field here; remove it or put it where the format has it"
            )
        elif error["type"] == "missing":
            lines.append(f"{path}: required and missing")
        else:
            lines.append(f"{path}: {error['msg']}")
    more = len(exc.errors()) - limit
    return "; ".join(lines) + (f"; and {more} more" if more > 0 else "") + f". {FORMAT}"


KEY_MARKERS = ("key", "primary_key", "primaryKey", "pk", "is_key", "isKey")


def table_keys_from_columns(data: Any) -> Any:
    """A key written as a marker on each column (`"key": true`, `"primary_key": true`, the way database tools show
    it) means the table's key: the marked columns, in order, join the table's list. Other fields stay as they are."""
    tables = data.get("schema", {}).get("tables") if isinstance(data, dict) else None
    if not isinstance(tables, list):
        return data
    fixed = []
    for table in tables:
        if not isinstance(table, dict) or not isinstance(table.get("columns"), list):
            fixed.append(table)
            continue
        marked: list[str] = []
        columns = []
        for item in table["columns"]:
            if isinstance(item, dict):
                if any(item.get(k) is True for k in KEY_MARKERS) and isinstance(item.get("name"), str):
                    marked.append(item["name"])
                item = {k: v for k, v in item.items() if k not in KEY_MARKERS}
            columns.append(item)
        key = list(table["key"]) if isinstance(table.get("key"), list) else []
        key += [m for m in marked if m.lower() not in {k.lower() for k in key}]
        fixed.append({**table, "columns": columns, "key": key})
    return {**data, "schema": {**data["schema"], "tables": fixed}}


def parse_suite(content: str, *, guided: bool = False) -> Suite:
    """The suite of the reply. With `guided` (guided extraction, ADR-0033) a key marked on the columns is read as
    the table's key, and the format errors go back in words instead of the validator's raw records. Without it the
    parse is the strict one the recordings were made with."""
    data = parse_json(content)
    try:
        return Suite.model_validate(table_keys_from_columns(data) if guided else data)
    except ValidationError as exc:
        detail = format_problems(exc) if guided else str(exc.errors()[:5])
        raise ReplyError(f"the suite does not follow the format: {detail}") from exc


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
                suite = parse_suite(reply.content, guided=guided_enabled(ctx.run.options))
            except ReplyError as exc:  # verified below: the reply goes back with the reason
                raise_if_cut(reply, "Characterization suite", exc)
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
