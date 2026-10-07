"""Characterization (spec 6.1 phase 9) on the fictitious application: the test engineer's suite is checked against
the rules and the code, the legacy runs it (here, the recording of a real Sybase ASE run) and the golden master is
frozen; without an engine or a recording the phase waits instead of inventing expected results."""

import hashlib
import json
import re
import uuid
from pathlib import Path

import pytest

from nexti_adapter_sybase.ase import RecordedRunner
from nexti_core.adapters import LegacyRunner, SourceFile
from nexti_core.spec.characterization import GoldenMaster, Suite
from nexti_core.spec.model import Rule
from nexti_orchestration import PhaseSpec, RunContext
from nexti_orchestration.characterization import CharacterizationPhases, coverage_problems, parse_suite
from nexti_orchestration.context import PhaseContext
from nexti_orchestration.extraction import ModelCaller, ModelReply
from nexti_orchestration.memory import MemoryStore
from nexti_orchestration.model import PhaseUnavailableError
from nexti_orchestration.store import Usage

FIXTURES = Path(__file__).resolve().parents[2] / "adapters/source/sybase/tests/fixtures/pago_orden"
FILES = [SourceFile("sp/sp_pago_orden.sp", (FIXTURES / "sp_pago_orden.sp").read_text(encoding="utf-8"))]
RULES = [Rule.model_validate(r) for r in json.loads((FIXTURES / "reference_spec.json").read_text("utf-8"))["rules"]]
SUITE = (FIXTURES / "characterization.json").read_text(encoding="utf-8")


def _without(case: str) -> str:
    data = json.loads(SUITE)
    data["cases"] = [c for c in data["cases"] if c["name"] != case]
    return json.dumps(data)


class StandInTester:
    """First a suite that forgets the only case of RULE-001, then the complete one."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.requests: list[list[dict[str, str]]] = []

    async def complete(
        self, agent: str, phase: str, messages: list[dict[str, str]], *, iteration: int = 1, judge: int = 0
    ) -> ModelReply:
        self.requests.append(messages)
        return ModelReply(self.replies[min(iteration, len(self.replies)) - 1], Usage(model="t", input_tokens=5))


class MemoryPort:
    def __init__(self, runner: LegacyRunner | None, replies: list[str]) -> None:
        self.tester = StandInTester(replies)
        self.models: ModelCaller = self.tester
        self.runner = runner
        self.drafts: dict[str, str] = {}
        self.master: GoldenMaster | None = None

    async def load_rules(self) -> list[Rule]:
        return RULES

    async def source_files(self) -> list[SourceFile]:
        return FILES

    async def inventory_digest(self) -> str:
        return "Procedure dbo.sp_pago_orden"

    def legacy_runner(self) -> LegacyRunner | None:
        return self.runner

    async def save_file(self, path: str, content: str) -> str:
        key = hashlib.sha256(content.encode()).hexdigest()
        self.drafts[key] = content
        return key

    async def load_file(self, reference: str) -> str:
        return self.drafts[reference]

    async def save_golden_master(self, master: GoldenMaster) -> None:
        self.master = master


def _context() -> tuple[PhaseContext, MemoryStore]:
    phase = PhaseSpec("characterization", None, True)
    run = RunContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pipeline", "modernization", (phase,), ("C1",),
                     "balanced", 3, (), target={"backend": "spring-boot"})  # fmt: skip
    store = MemoryStore()
    return PhaseContext(run, store, phase, None), store


def test_every_rule_needs_a_case() -> None:
    suite = parse_suite(_without("account_type_not_allowed"))
    assert coverage_problems(suite, RULES) == ["rules without a case: RULE-001"]


async def test_the_golden_master_is_what_the_legacy_did_with_the_corrected_suite() -> None:
    port = MemoryPort(RecordedRunner(FIXTURES / "golden", "replay"), [_without("account_type_not_allowed"), SUITE])
    ctx, store = _context()
    result = await CharacterizationPhases(port).characterization(ctx)
    assert result.summary == "Golden master: 12 case(s) frozen, 7 of them rejected by the legacy (sybase-ase-16.0)"
    assert port.master is not None
    assert len(port.master.results) == 12
    assert "rules without a case: RULE-001" in port.tester.requests[1][-1]["content"]
    assert store.kinds().count("selfCorrected") == 1


async def test_without_an_engine_or_a_recording_the_phase_waits() -> None:
    ctx, _ = _context()
    with pytest.raises(PhaseUnavailableError, match="no engine"):
        await CharacterizationPhases(MemoryPort(None, [SUITE])).characterization(ctx)
    ctx, _ = _context()
    changed = json.loads(SUITE)
    changed["cases"][0]["description"] = "never recorded"
    port = MemoryPort(RecordedRunner(FIXTURES / "golden", "replay"), [json.dumps(changed)])
    with pytest.raises(PhaseUnavailableError, match="no golden master recorded"):
        await CharacterizationPhases(port).characterization(ctx)


def test_format_errors_go_back_in_words_only_when_guided() -> None:
    from nexti_orchestration.extraction import ReplyError

    bad = json.dumps({"program": "dbo.sp_x", "schema": {"tables": [{"name": "db..t", "columns": [
        {"name": "a", "type": "int", "size": 4}]}]}, "cases": [{"rules": ["RULE-001"]}]})  # fmt: skip
    with pytest.raises(ReplyError) as raw:
        parse_suite(bad)
    assert "extra_forbidden" in str(raw.value)  # the recorded form stays as it is
    with pytest.raises(ReplyError) as worded:
        parse_suite(bad, guided=True)
    message = str(worded.value)
    assert "schema.tables.0.columns.0.size: 'size' is not a field here" in message
    assert "cases.0.name: required and missing" in message
    assert "a column has only name, type and nullable" in message
    assert "extra_forbidden" not in message


def test_the_guided_suite_takes_case_names_as_the_model_writes_them() -> None:
    from nexti_orchestration.characterization import case_name, parse_cases
    from nexti_orchestration.extraction import ReplyError

    assert case_name("Batch-Flag COBIS (S)") == "batch_flag_cobis_s"
    assert case_name("  01 fresh / unit  ") == "case_01_fresh_unit"
    assert case_name("ok_name") == "ok_name"
    assert case_name("x" * 100) == "x" * 80
    assert case_name("ab") == "ab"  # too short to be a name: the validator says so
    assert case_name(7) == 7
    data = json.loads(SUITE)
    case = {**data["cases"][0], "name": "Batch-Flag COBIS (S)"}
    (parsed,) = parse_cases(json.dumps({"cases": [case]}))
    assert parsed.name == "batch_flag_cobis_s"
    with pytest.raises(ReplyError, match="string_pattern_mismatch"):  # the recorded strict form is untouched
        parse_suite(json.dumps({**data, "cases": [case]}))


def test_a_key_marked_on_the_columns_becomes_the_table_key_only_when_guided() -> None:
    from nexti_orchestration.extraction import ReplyError

    data = json.loads(SUITE)
    table = data["schema"]["tables"][0]
    marked = {c["name"] for c in table["columns"][:2]}
    table.pop("key", None)
    for column in table["columns"]:
        column["key"] = column["name"] in marked
    content = json.dumps(data)
    with pytest.raises(ReplyError, match="does not follow the format"):  # the strict parse of the recordings
        parse_suite(content)
    suite = parse_suite(content, guided=True)
    assert suite.schema_.tables[0].key == [c["name"] for c in table["columns"][:2]]
    assert all(set(c.model_dump()) == {"name", "type", "nullable"} for c in suite.schema_.tables[0].columns)


async def test_a_suite_cut_at_the_output_limit_stops_the_phase_at_once_instead_of_paying_the_same_again() -> None:
    from nexti_orchestration.extraction import ReplyError
    from nexti_orchestration.model import PhaseFailedError

    class CutTester(StandInTester):
        async def complete(
            self, agent: str, phase: str, messages: list[dict[str, str]], *, iteration: int = 1, judge: int = 0
        ) -> ModelReply:
            self.requests.append(messages)
            return ModelReply(SUITE[:200], Usage(model="t", input_tokens=5, output_tokens=16000), cut_at=16000)

    port = MemoryPort(None, [SUITE])
    port.tester = CutTester([SUITE])
    port.models = port.tester
    ctx, store = _context()

    class Runner:
        engine = "test"

    port.runner = Runner()  # type: ignore[assignment]
    with pytest.raises(PhaseFailedError, match=r"cut at the output limit of its profile \(16000 tokens\)"):
        await CharacterizationPhases(port).characterization(ctx)
    assert len(port.tester.requests) == 2  # one correction (the model may answer shorter), then it stops
    assert [i["status"] for i in store.invocations.values()] == ["failed", "failed"]
    # A whole reply that happens to reach the limit is used as any other (a recording has one).
    from nexti_orchestration.extraction import is_cut, raise_if_cut

    whole = ModelReply(SUITE, Usage(model="t", output_tokens=16000), cut_at=16000)
    assert not is_cut(whole, ReplyError("rules without a case: RULE-001"))  # a content problem, not a cut
    raise_if_cut(whole, "x", ReplyError("the JSON is not valid: x"), repeated=False)  # the first cut is retried


# -- the guided suite in pieces (ADR-0036) ---------------------------------------------------------------------------
class GuidedTester(StandInTester):
    """Answers the schema request with the fixture's schema and each request of cases with the fixture's cases of
    the rules listed; the first time, it forgets the case of RULE-001 so one group is asked again."""

    def __init__(self) -> None:
        super().__init__([SUITE])
        self.forgot = False

    async def complete(
        self, agent: str, phase: str, messages: list[dict[str, str]], *, iteration: int = 1, judge: int = 0
    ) -> ModelReply:
        from nexti_orchestration.characterization import SCHEMA_REQUEST

        self.requests.append(messages)
        data = json.loads(SUITE)
        user = messages[1]["content"]
        if SCHEMA_REQUEST in user:
            content = {"program": data["program"], "schema": data["schema"], "cases": []}
        else:
            ids = set(re.findall(r"RULE-\d{3}", user.split("Rules for this request")[1].split("\n")[0]))
            cases = [c for c in data["cases"] if set(c["rules"]) & ids]
            if len(messages) == 2:  # the first round forgets the only case of RULE-001 in every request
                self.forgot = True
                cases = [c for c in cases if c["name"] != "account_type_not_allowed"]
            content = {"cases": cases}
        return ModelReply(json.dumps(content), Usage(model="t", input_tokens=5, output_tokens=50))


class EchoRunner:
    """A legacy engine for the test: it observes nothing, it only freezes the suite it was given."""

    engine = "test"

    async def run(self, files: list[SourceFile], suite: Suite) -> GoldenMaster:
        from nexti_core.spec.characterization import Observation, Recorded

        return GoldenMaster(program=suite.program, source_sha256="0" * 64, engine="test", schema_=suite.schema_,
                            results=[Recorded(case=c, observation=Observation()) for c in suite.cases])  # fmt: skip


async def test_the_guided_suite_comes_in_pieces_and_a_diagnostic_re_asks_only_its_group() -> None:
    from nexti_orchestration.characterization import GROUP

    port = MemoryPort(EchoRunner(), [SUITE])
    port.tester = GuidedTester()
    port.models = port.tester
    phase = PhaseSpec("characterization", None, True)
    run = RunContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pipeline", "modernization", (phase,), ("C1",),
                     "balanced", 3, (), target={"backend": "spring-boot"},
                     options={"guided_extraction": True})  # fmt: skip
    store = MemoryStore()
    ctx = PhaseContext(run, store, phase, None)
    result = await CharacterizationPhases(port).characterization(ctx)
    groups = -(-len(RULES) // GROUP)
    # One schema request, one request per group, and one group asked again after "rules without a case".
    assert len(port.tester.requests) == 1 + groups + 1
    again = port.tester.requests[-1]
    assert "RULE-001" in again[1]["content"].split("Rules for this request")[1].split("\n")[0]
    assert "rules without a case: RULE-001" in again[-1]["content"]
    assert "Agreed schema" in again[1]["content"]
    assert port.master is not None
    covered = {r for recorded in port.master.results for r in recorded.case.rules}
    assert covered >= {r.id for r in RULES}
    assert "case(s) frozen" in result.summary


async def test_a_late_engine_is_tried_again_before_the_phase_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    # ADR-0046: a busy host makes Sybase late; the phase tries again after short waits before waiting for a
    # person, and an engine that never comes still makes the phase wait.
    from nexti_adapter_sybase.ase import LegacyEngineTimeoutError
    from nexti_orchestration import characterization

    slept: list[float] = []

    async def no_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(characterization, "engine_sleep", no_sleep)
    recorded = RecordedRunner(FIXTURES / "golden", "replay")

    class LateRunner:
        engine = recorded.engine

        def __init__(self, late: int) -> None:
            self.late = late

        async def run(self, files: list[SourceFile], suite: Suite) -> GoldenMaster:
            if self.late:
                self.late -= 1
                raise LegacyEngineTimeoutError("the Sybase engine did not answer within 300 s")
            return await recorded.run(files, suite)

    port = MemoryPort(LateRunner(late=2), [SUITE])
    ctx, store = _context()
    result = await CharacterizationPhases(port).characterization(ctx)
    assert result.summary.startswith("Golden master: 12 case(s) frozen")
    assert slept == [60, 180]
    assert sum("The legacy engine is late" in e.message for e in store.events) == 2
    # Never comes: after the waits the phase waits for a person, as before.
    slept.clear()
    ctx, _ = _context()
    with pytest.raises(PhaseUnavailableError, match="did not answer"):
        await CharacterizationPhases(MemoryPort(LateRunner(late=9), [SUITE])).characterization(ctx)
    assert slept == [60, 180]


async def test_the_branches_no_case_enters_go_back_to_the_test_engineer_once() -> None:
    # M27b (ADR-0047): the coverage shows a branch no case entered; the test engineer gets its code and the rules
    # citing it once; what stays uncovered after that round is reported, never looped.
    from nexti_core.spec.characterization import Coverage, CoveredBranch

    cited = next(r for r in RULES if r.sources)
    ref = cited.sources[0]

    class CoveringRunner(EchoRunner):
        def __init__(self) -> None:
            self.runs = 0

        async def run(self, files: list[SourceFile], suite: Suite) -> GoldenMaster:
            self.runs += 1
            master = await super().run(files, suite)
            branch = CoveredBranch(id="b1", kind="if-true", line_start=ref.line_start, line_end=ref.line_end,
                                   file=ref.file)  # fmt: skip
            return master.model_copy(update={"coverage": Coverage(branches=[branch], executed={})})

    runner = CoveringRunner()
    port = MemoryPort(runner, [SUITE])
    port.tester = GuidedTester()
    port.models = port.tester
    phase = PhaseSpec("characterization", None, True)
    run = RunContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pipeline", "modernization", (phase,), ("C1",),
                     "balanced", 3, (), target={"backend": "spring-boot"},
                     options={"guided_extraction": True})  # fmt: skip
    ctx = PhaseContext(run, MemoryStore(), phase, None)
    result = await CharacterizationPhases(port).characterization(ctx)
    asked = [r[-1]["content"] for r in port.tester.requests if "No case of the suite enters" in r[-1]["content"]]
    assert asked
    assert f"rules {cited.id}" in asked[0]
    assert f"if-true at lines {ref.line_start}-{ref.line_end}" in asked[0]
    assert "Keep every case you already wrote" in asked[0]
    assert runner.runs >= 2  # recorded again after the round, then accepted with the branch still uncovered
    assert "legacy coverage: 0 of 1 measurable branches exercised" in result.summary


async def test_the_engine_quirks_no_case_reaches_go_in_the_branch_round_and_the_summary() -> None:
    # M28: a quirk inside a branch no case enters is asked with that branch; the summary counts the register.
    from nexti_core.spec.characterization import Coverage, CoveredBranch, EngineQuirk, EnvironmentItem

    ref = next(r for r in RULES if r.sources).sources[0]

    class QuirkRunner(EchoRunner):
        async def run(self, files: list[SourceFile], suite: Suite) -> GoldenMaster:
            master = await super().run(files, suite)
            branch = CoveredBranch(id="b1", kind="if-true", line_start=ref.line_start, line_end=ref.line_end)
            quirk = EngineQuirk(id="null-compare", severity="critical", behavior="NULL = NULL is true.", target="t.",
                                lines=[ref.line_start], probe="p", expected="true", observed="true")  # fmt: skip
            return master.model_copy(update={
                "coverage": Coverage(branches=[branch], executed={}), "quirks": [quirk],
                "environment": [EnvironmentItem(key="language", value="us_english", source="engine")],
            })  # fmt: skip

    port = MemoryPort(QuirkRunner(), [SUITE])
    port.tester = GuidedTester()
    port.models = port.tester
    phase = PhaseSpec("characterization", None, True)
    run = RunContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pipeline", "modernization", (phase,), ("C1",),
                     "balanced", 3, (), target={"backend": "spring-boot"},
                     options={"guided_extraction": True})  # fmt: skip
    result = await CharacterizationPhases(port).characterization(PhaseContext(run, MemoryStore(), phase, None))
    asked = [r[-1]["content"] for r in port.tester.requests if "behaviours of the legacy engine" in r[-1]["content"]]
    assert len(asked) == 1
    assert f"- null-compare (critical) at lines {ref.line_start}: NULL = NULL is true." in asked[0]
    assert "engine quirks: 1 (1 confirmed on the engine, 1 no case reaches); environment: 1 setting(s)" in (
        result.summary
    )
