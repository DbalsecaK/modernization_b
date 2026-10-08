"""The worker observes the legacy according to its inputs: recorded CICS traces when the archive has them, the
engine it was given otherwise, and a clear wait when there is neither (ADR-0015)."""

import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from nexti_core.adapters import LegacyUnavailableError, SourceFile
from nexti_core.legacy_execution import Credentials
from nexti_core.spec.characterization import Case, GoldenMaster, Schema, Suite
from nexti_worker.project import LegacyExecution, SourceRunner

SUITE = Suite(program="PAGOORD", cases=[Case(name="pago_web_exitoso", rules=["RULE-001"])])


class Engine:
    engine = "sybase-ase-16.0"

    async def run(self, files: list[SourceFile], suite: Suite) -> GoldenMaster:
        return GoldenMaster(program=suite.program, source_sha256="0" * 64, engine=self.engine, schema_=Schema(),
                            results=[])  # fmt: skip


async def test_traces_in_the_inputs_choose_the_trace_runner() -> None:
    runner = SourceRunner(Engine)
    trace = SourceFile("traces/PAGOORD.json", '{"engine": "cics-trace", "program": "OTRO", "results": []}')
    with pytest.raises(ValueError, match="no traces of PAGOORD"):
        await runner.run([trace], SUITE)
    assert runner.engine == "cics-trace"


async def test_without_traces_the_given_engine_runs_or_the_phase_waits() -> None:
    runner = SourceRunner(Engine)
    master = await runner.run([SourceFile("sp/x.sp", "create procedure x as return 0")], SUITE)
    assert (master.engine, runner.engine) == ("sybase-ase-16.0", "sybase-ase-16.0")
    with pytest.raises(LegacyUnavailableError):
        await SourceRunner(None).run([], SUITE)


class LiveIbmi(Engine):
    engine = "ibmi-7.5"

    def __init__(self, config: dict[str, object], credentials: Credentials) -> None:
        self.seen = (config, credentials.user)


def setting(execution: LegacyExecution | None) -> Callable[[], Awaitable[LegacyExecution | None]]:
    async def read() -> LegacyExecution | None:
        return execution

    return read


SOURCE = [SourceFile("qrpglesrc/ACTSALDO.rpgle", "**FREE\nreturn;\n")]
RPG_ROOT = Path(__file__).resolve().parents[3] / "packages/adapters/source/rpg/tests/fixtures/cooperativa"
RPG_FILES = [SourceFile(p.relative_to(RPG_ROOT).as_posix(), p.read_text(encoding="utf-8"))
             for p in sorted(RPG_ROOT.rglob("*")) if p.is_file()]  # fmt: skip
TRACE = SourceFile("traces/ACTSALDO.json", '{"engine": "ibmi-trace", "program": "OTRO", "results": []}')


async def test_the_project_setting_chooses_traces_or_the_live_system_and_never_falls_back() -> None:
    # ADR-0052: `traces` never runs the engine; without traces the phase waits.
    traces_only = SourceRunner(Engine, setting(LegacyExecution("traces")))
    with pytest.raises(LegacyUnavailableError, match="recorded traces and the inputs have none"):
        await traces_only.run(SOURCE, SUITE)
    with pytest.raises(ValueError, match="no traces of PAGOORD"):
        await traces_only.run([*SOURCE, TRACE], SUITE)
    # `live` builds the runner of its kind with the project's config and credentials, even if traces are there.
    config = {"host": "ibmi.example.com", "library": "NXTEST"}
    live = LegacyExecution("live", "ibmi", config, Credentials(user="NXUSER", password=uuid.uuid4().hex))
    built: list[LiveIbmi] = []

    def factory(cfg: dict[str, object], credentials: Credentials) -> LiveIbmi:
        built.append(LiveIbmi(cfg, credentials))
        return built[-1]

    runner = SourceRunner(Engine, setting(live), {"ibmi": factory})
    master = await runner.run([*SOURCE, TRACE], SUITE)
    assert (master.engine, built[0].seen) == ("ibmi-7.5", (config, "NXUSER"))
    # A live system the worker cannot reach, or without credentials, makes the phase wait.
    with pytest.raises(LegacyUnavailableError, match="cannot run a legacy on a live ibmi"):
        await SourceRunner(Engine, setting(live)).run(SOURCE, SUITE)
    without = LegacyExecution("live", "ibmi", config, None)
    with pytest.raises(LegacyUnavailableError, match="has no credentials"):
        await SourceRunner(Engine, setting(without), {"ibmi": factory}).run(SOURCE, SUITE)
    # No setting (or `auto`) keeps the behaviour by inputs.
    assert (await SourceRunner(Engine, setting(None)).run(SOURCE, SUITE)).engine == "sybase-ase-16.0"


async def test_traced_rpg_brings_the_quirks_of_its_code() -> None:
    # R4: traces record what the legacy did; the behaviours its code relies on come from the RPG catalog.
    suite = Suite(program="ACTSALDO", cases=[Case(name="debito_con_comision", rules=["RULE-001"])])
    master = await SourceRunner(None, setting(LegacyExecution("traces"))).run(RPG_FILES, suite)
    assert master.engine == "ibmi-trace"
    assert [q.id for q in master.quirks] == ["decimal-truncation", "record-not-found", "immediate-writes"]
    assert ("rpg:datfmt", "*ISO (default)") in [(e.key, e.value) for e in master.environment]
