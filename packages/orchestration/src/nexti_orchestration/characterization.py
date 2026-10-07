"""Characterization (spec 6.1 phase 9): the test engineer designs the suite (legacy schema, cases, how external
programs answer); code checks it against the source and the rules; the legacy itself runs every case in its own
isolated engine and what it did is frozen as the golden master, before anything is generated. Nothing of the
expected behaviour comes from a model: the model only chooses the inputs."""

import asyncio
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from pydantic import ValidationError

from nexti_agents import prompt
from nexti_core.adapters import LegacyRunner, LegacyUnavailableError, SourceFile
from nexti_core.spec.characterization import Case, CoveredBranch, GoldenMaster, Schema, Suite
from nexti_core.spec.model import Rule
from nexti_orchestration.context import Attempt, PhaseContext, Verification
from nexti_orchestration.extraction import JSON_ERRORS, ModelCaller, ReplyError, parse_json, raise_if_cut
from nexti_orchestration.guided import enabled as guided_enabled
from nexti_orchestration.model import PhaseFailedError, PhaseResult, PhaseUnavailableError
from nexti_orchestration.scope import scope_files, split_rules
from nexti_orchestration.store import Usage
from nexti_orchestration.usage import total

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


GROUP = 6  # rules per request of cases in the guided suite (ADR-0036): every answer stays small
SCHEMA_REQUEST = (
    'Answer now with the `program` and the `schema` only, as {"program": "...", "schema": {"tables": [...]}, '
    '"cases": []}. The cases come in later requests, a few rules at a time.'
)
CASES_REQUEST = (
    "The schema above is agreed: do not repeat it and use its table and column names. Answer with the cases for the "
    'rules listed below only, as {"cases": [...]}: at least one case per rule listed, one per branch of a P0 rule.'
)
RULE_ID = re.compile(r"RULE-\d{3,}")


def parse_schema(content: str) -> tuple[str, Schema]:
    """The first piece of a guided suite: the program and its schema."""
    data = table_keys_from_columns(parse_json(content))
    if not isinstance(data, dict) or not str(data.get("program") or "").strip():
        raise ReplyError('the answer must be {"program": "...", "schema": {"tables": [...]}, "cases": []}')
    try:
        return str(data["program"]).strip(), Schema.model_validate(data.get("schema") or {})
    except ValidationError as exc:
        raise ReplyError(f"the schema does not follow the format: {format_problems(exc)}") from exc


def case_name(raw: Any) -> Any:
    """The name a model wrote, in the form a case name takes (lowercase letters, digits and underscores, starting
    with a letter): `Batch-Flag COBIS (S)` becomes `batch_flag_cobis_s`. Only the guided suite (ADR-0036) applies
    it, before validation: a wrong spelling of the name is not a reason to ask for the cases again. Anything that is
    not a string is left for the validator to reject."""
    if not isinstance(raw, str):
        return raw
    slug = re.sub(r"_+", "_", re.sub(r"[^a-z0-9_]+", "_", raw.strip().lower())).strip("_")
    if slug and not slug[0].isalpha():
        slug = f"case_{slug}"
    return slug[:80] if len(slug) >= 3 else raw


def parse_cases(content: str) -> list[Case]:
    """A piece of cases of a guided suite."""
    data = parse_json(content)
    items = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise ReplyError('the answer must be {"cases": [...]} with at least one case')
    try:
        return [
            Case.model_validate({**item, "name": case_name(item.get("name"))} if isinstance(item, dict) else item)
            for item in items
        ]
    except ValidationError as exc:
        raise ReplyError(f"the cases do not follow the format: {format_problems(exc)}") from exc


def groups_of(rules: Sequence[Rule], size: int = GROUP) -> list[list[Rule]]:
    """The rules in groups of `size`, by id: each group is one request of cases."""
    ordered = sorted(rules, key=lambda r: r.id)
    return [ordered[i : i + size] for i in range(0, len(ordered), size)] or [[]]


BRANCHES_AT_MOST = 25  # branches named in one request: the rest come in the report


def branch_request(missed: Sequence[CoveredBranch], files: Sequence[SourceFile], rules: Sequence[Rule]) -> str:
    """The branches no case entered, each with its lines of code and the rules citing them (so the pieces of the
    guided suite that own them are asked again), and what to do: keep every case, add cases that enter them."""
    texts = {f.path: f.text.splitlines() for f in files}
    blocks = []
    for branch in missed[:BRANCHES_AT_MOST]:
        lines = texts.get(branch.file) or next(iter(texts.values()), [])
        start = max(branch.line_start - 2, 0)
        end = min(branch.line_end + 1, len(lines), start + 14)
        code = "\n".join(f"{n + 1:5}  {lines[n]}" for n in range(start, end))
        citing = sorted({r.id for r in rules for ref in r.sources
                         if ref.line_start <= branch.line_end and ref.line_end >= branch.line_start})  # fmt: skip
        blocks.append(f"- {branch.kind} at lines {branch.line_start}-{branch.line_end}"
                      + (f" (rules {', '.join(citing)})" if citing else "") + f":\n{code}")  # fmt: skip
    more = len(missed) - BRANCHES_AT_MOST
    return (
        f"No case of the suite enters {len(missed)} branch(es) of the program, so the golden master cannot prove "
        "what they do. Keep every case you already wrote and add cases whose inputs, rows and stub answers make "
        "the program enter each branch below (a branch that no input can reach: say so instead of inventing one):\n"
        + "\n".join(blocks)
        + (f"\n... and {more} more branch(es)" if more > 0 else "")
    )


def affected_groups(feedback: str, groups: Sequence[Sequence[Rule]], cases: Mapping[int, Sequence[Case]]) -> set[int]:
    """The groups a diagnostic points at (by rule id or case name); every group when it points at none."""
    ids = set(RULE_ID.findall(feedback))
    found = {i for i, group in enumerate(groups) if any(r.id in ids for r in group)}
    found |= {i for i, items in cases.items() if any(re.search(rf"\b{re.escape(c.name)}\b", feedback) for c in items)}
    return found or set(range(len(groups)))


def unique_names(cases: Sequence[Case]) -> list[Case]:
    """Cases from different requests may repeat a name: the later ones get a suffix."""
    seen: dict[str, int] = {}
    out = []
    for case in cases:
        n = seen.get(case.name, 0)
        seen[case.name] = n + 1
        out.append(case if n == 0 else case.model_copy(update={"name": f"{case.name}_{n + 1}"[:80]}))
    return out


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


# A transient engine failure is tried again after these waits before the phase waits for a person (ADR-0046).
ENGINE_RETRY_SECONDS: tuple[int, ...] = (60, 180)


async def engine_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


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
        branch_round: list[bool] = []  # M27b: the branches without a case are asked once
        guided = guided_enabled(ctx.run.options)

        async def work_single(iteration: int, feedback: str | None) -> Attempt:
            messages = list(request)
            if feedback:
                messages.append({"role": "user", "content": f"The suite could not be used:\n{feedback}\nFix it."})
            reply = await self.port.models.complete(TESTER, "characterization", messages, iteration=iteration)
            try:
                suite = parse_suite(reply.content, guided=guided_enabled(ctx.run.options))
            except ReplyError as exc:  # verified below: the reply goes back with the reason
                raise_if_cut(reply, "Characterization suite", exc, repeated=bool(feedback) and
                             str(feedback).startswith(JSON_ERRORS))  # fmt: skip
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
            recorded = None
            for wait in (*ENGINE_RETRY_SECONDS, None):
                try:
                    recorded = await runner.run(files, suite)
                    break
                except ValueError as exc:  # the suite does not fit the code (GoldenError)
                    return Verification(False, str(exc)[:3000])
                except LegacyUnavailableError as exc:
                    # A busy host makes the engine late (ADR-0046): a transient failure is tried again here before
                    # the run waits; no engine, or a replay without a recording, waits at once.
                    if not exc.transient or wait is None:
                        raise PhaseUnavailableError(str(exc)[:500]) from exc
                    await ctx.store.event("info", "running", f"The legacy engine is late ({str(exc)[:200]}); "
                                          f"trying again in {wait} s", phase=ctx.phase.key)  # fmt: skip
                    await engine_sleep(wait)
            assert recorded is not None  # noqa: S101 - the loop breaks with a recording or raises
            failed = [f"{r.case.name}: {r.observation.error}" for r in recorded.results if r.observation.error]
            if failed:
                return Verification(False, "the engine failed these cases:\n" + "\n".join(failed)[:3000])
            await self.port.save_golden_master(recorded)
            master["run"] = recorded
            # M27b (ADR-0047): the branches of the program no case entered go back to the test engineer once, with
            # their code and the rules that cite them; what stays uncovered after that round is reported, not looped.
            measured = recorded.coverage
            if guided and measured is not None and measured.not_exercised and not branch_round:
                branch_round.append(True)
                return Verification(False, branch_request(measured.not_exercised, files, rules))
            return Verification(True)

        # Guided (ADR-0036): the schema first, then the cases a few rules at a time, so a long program never needs
        # one answer the size of its whole suite; a diagnostic re-asks only the pieces it points at.
        groups = groups_of(rules)
        draft: dict[str, Any] = {"program": None, "schema": None, "cases": {}}
        cut_before: dict[str, bool] = {}
        inventory = await self.port.inventory_digest()

        def rules_json(items: Sequence[Rule]) -> str:
            return json.dumps([r.model_dump(mode="json") for r in items], ensure_ascii=False, indent=1)

        async def ask(key: str, user: str, feedback: str | None, iteration: int, what: str) -> tuple[Any, Usage]:
            messages = [request[0], {"role": "user", "content": user}]
            if feedback:
                messages.append({"role": "user", "content": f"The suite could not be used:\n{feedback}\nFix it."})
            reply = await self.port.models.complete(TESTER, "characterization", messages, iteration=iteration)
            try:
                value = parse_schema(reply.content) if key == "schema" else parse_cases(reply.content)
            except ReplyError as exc:
                raise_if_cut(reply, what, exc, repeated=cut_before.get(key, False))
                cut_before[key] = bool(reply.cut_at)
                raise
            cut_before[key] = False
            return value, reply.usage

        async def work_guided(iteration: int, feedback: str | None) -> Attempt:
            usage: list[Usage] = []
            source = _sources(files)
            redo = affected_groups(feedback, groups, draft["cases"]) if feedback else set(range(len(groups)))
            try:
                if draft["schema"] is None or (feedback and "schema" in feedback.lower()):
                    user = (f"Inventory:\n{inventory}\n\nRules:\n{rules_json(rules)}\n\nSource:\n{source}\n\n"
                            f"{SCHEMA_REQUEST}")  # fmt: skip
                    (program, schema), used = await ask("schema", user, feedback, iteration,
                                                        "Characterization schema")  # fmt: skip
                    usage.append(used)
                    draft.update(program=program, schema=schema)
                schema_json = draft["schema"].model_dump_json(by_alias=True, indent=1)
                for index in sorted(redo | {i for i in range(len(groups)) if i not in draft["cases"]}):
                    ids = ", ".join(r.id for r in groups[index]) or "none"
                    user = (f"Inventory:\n{inventory}\n\nAgreed schema:\n{schema_json}\n\nRules for this request "
                            f"({ids}):\n{rules_json(groups[index])}\n\nSource:\n{source}\n\n"
                            f"{CASES_REQUEST}")  # fmt: skip
                    cases, used = await ask(f"cases:{index}", user, feedback, iteration,
                                            f"Characterization cases ({ids})")  # fmt: skip
                    usage.append(used)
                    draft["cases"][index] = cases
            except ReplyError as exc:  # verified below: the reply goes back with the reason
                return Attempt({"error": str(exc)[:3000]}, "suite with format errors", total(usage))
            cases = unique_names([c for i in sorted(draft["cases"]) for c in draft["cases"][i]])
            try:
                suite = Suite(program=draft["program"], schema_=draft["schema"], cases=cases)
            except ValidationError as exc:
                return Attempt({"error": format_problems(exc)[:3000]}, "suite with format errors", total(usage))
            reference = await self.port.save_file("characterization/suite.json", suite.model_dump_json(by_alias=True))
            return Attempt({"suite": reference}, f"{len(cases)} case(s) in {len(groups)} request(s)", total(usage))

        work = work_guided if guided else work_single
        attempt = await ctx.do_verify_correct(TESTER, work, verify, what="Characterization suite")
        recorded = master.get("run")
        cases = attempt.summary
        if recorded is not None:
            rejected = sum(1 for r in recorded.results if r.observation.returns not in (0, None))
            cases = f"{len(recorded.results)} case(s) frozen, {rejected} of them rejected by the legacy"
            if recorded.coverage is not None:  # ADR-0047: what of the legacy the cases exercised
                cases += f"; legacy coverage: {recorded.coverage.note()}"
        return PhaseResult(summary=f"Golden master: {cases} ({runner.engine})")
