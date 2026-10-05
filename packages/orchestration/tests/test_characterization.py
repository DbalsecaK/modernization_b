"""Characterization (spec 6.1 phase 9) on the fictitious application: the test engineer's suite is checked against
the rules and the code, the legacy runs it (here, the recording of a real Sybase ASE run) and the golden master is
frozen; without an engine or a recording the phase waits instead of inventing expected results."""

import hashlib
import json
import uuid
from pathlib import Path

import pytest

from nexti_adapter_sybase.ase import RecordedRunner
from nexti_core.adapters import LegacyRunner, SourceFile
from nexti_core.spec.characterization import GoldenMaster
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
    assert len(port.tester.requests) == 1  # not asked again
    assert [i["status"] for i in store.invocations.values()] == ["failed"]
    # A whole reply that happens to reach the limit is used as any other (a recording has one).
    from nexti_orchestration.characterization import parse_suite as parse
    from nexti_orchestration.extraction import raise_if_cut

    whole = ModelReply(SUITE, Usage(model="t", output_tokens=16000), cut_at=16000)
    raise_if_cut(whole, "x", ReplyError("rules without a case: RULE-001"))  # a content problem, not a cut
    assert parse(whole.content).program
