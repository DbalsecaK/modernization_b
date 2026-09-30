"""The worker observes the legacy according to its inputs: recorded CICS traces when the archive has them, the
engine it was given otherwise, and a clear wait when there is neither (ADR-0015)."""

import pytest

from nexti_core.adapters import LegacyUnavailableError, SourceFile
from nexti_core.spec.characterization import Case, GoldenMaster, Schema, Suite
from nexti_worker.project import SourceRunner

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
