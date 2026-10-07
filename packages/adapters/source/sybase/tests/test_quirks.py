"""Engine quirks and environment of Sybase ASE (M28): found in the code by its tokens, probed on the engine that
records the golden master. Everything here is fictitious code (ADR-0011)."""

import asyncio
import os
from pathlib import Path

import pytest

from nexti_adapter_sybase import SybaseAdapter, golden, quirks
from nexti_adapter_sybase.ase import AseRunner
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import Suite

FIXTURES = Path(__file__).parent / "fixtures" / "pago_orden"
FILES = [SourceFile("sp/sp_pago_orden.sp", (FIXTURES / "sp_pago_orden.sp").read_text(encoding="utf-8"))]
SUITE = Suite.model_validate_json((FIXTURES / "characterization.json").read_text(encoding="utf-8"))

DEMO = """create procedure sp_demo_quirks
    @i_codigo   int,
    @i_nombre   varchar(20),
    @o_texto    varchar(60) = null output
as
declare @w_mitad int, @w_fecha varchar(10)
set rowcount 10
if @i_nombre = null
    select @o_texto = 'SIN NOMBRE'
else
    select @o_texto = 'HOLA ' + @i_nombre
select @w_mitad = @i_codigo / 2
if @o_texto = ''
    select @o_texto = null
select @w_fecha = convert(varchar(10), getdate(), 103)
update demo set nombre = null where codigo = @i_codigo
set rowcount 0
return 0
go
create trigger tr_demo on demo for update as
print 'demo'
go
"""


def _detected(text: str) -> dict[str, list[int]]:
    source = SourceFile("sp/demo.sp", text)
    (_, procedure) = golden.procedures([source])[0]
    return {q.id: q.lines for q in quirks.detect(source, procedure)}


def test_the_quirks_are_found_in_the_code_with_their_lines() -> None:
    found = _detected(DEMO)
    assert found["null-compare"] == [8]  # `if @i_nombre = null`, not `select @o_texto = null` nor `set nombre = null`
    assert found["null-concat"] == [11]
    assert found["integer-division"] == [12]
    assert found["empty-string"] == [13]
    assert found["date-style"] == [15]
    assert found["rowcount-option"] == [7, 17]
    assert "char-padding" not in found  # no fixed CHAR in this program


def test_the_fixture_relies_on_the_quirks_of_its_statements() -> None:
    found = _detected(FILES[0].text)
    assert {"select-assign-from-table", "error-continues", "nested-tran", "char-padding"} <= set(found)
    assert "null-compare" not in found  # `@o_mensaje = null` in a SELECT list is an assignment
    assert SybaseAdapter().engine_quirks(FILES)  # the adapter exposes the same register (adapter-neutral name)


def test_the_program_settings_are_set_options_and_triggers_not_update_columns() -> None:
    source = SourceFile("sp/demo.sp", DEMO)
    (_, procedure) = golden.procedures([source])[0]
    items = {e.key: e.value for e in quirks.program_environment([source], source, procedure)}
    assert set(items) == {"set rowcount", "trigger tr_demo"}
    assert items["trigger tr_demo"].startswith("on demo")


def test_the_engine_answers_are_read_from_the_output() -> None:
    answers = quirks.probe_answers(" NXQ|null-concat|a   \n(1 row affected)\n NXQ|nested-tran|0\nMsg 102, Level 15")
    assert answers == {"null-concat": "a", "nested-tran": "0"}
    environment = quirks.engine_environment(" NXE|language|us_english \n NXE|isolation-level|1")
    assert [(e.key, e.value) for e in environment] == [("isolation-level", "1"), ("language", "us_english")]


def test_the_runner_records_the_register_and_the_environment_once() -> None:
    class FakeAse(AseRunner):
        def __init__(self) -> None:
            super().__init__(coverage=False)
            self.probes = 0

        async def _start(self) -> str:
            return "engine"

        async def _stop(self, name: str) -> None:
            return None

        async def _isql(self, name: str, script: str, seconds: int) -> str:
            if "NXCASE|" in script:
                count = script.count("select 'NXCASE|")
                return "\n".join(f"NXCASE|{index}\nNXR|1:0" for index in range(count))
            if "NXQ|" in script:
                self.probes += 1
                return " NXQ|select-assign-from-table|5\n NXQ|nested-tran|1\n"  # this engine counts differently
            if "NXE|" in script:
                return " NXE|language|us_english\n NXE|isolation-level|1\n"
            return ""

    runner = FakeAse()
    master = asyncio.run(runner.run(FILES, SUITE))
    register = {q.id: q for q in master.quirks}
    assert register["select-assign-from-table"].confirmed is True
    assert register["nested-tran"].confirmed is False  # the register says what THIS engine does
    assert register["error-continues"].confirmed is None  # no probe: not probed
    assert {"language", "isolation-level"} <= {e.key for e in master.environment}
    changed = SUITE.model_copy(update={"cases": [SUITE.cases[0].model_copy(update={"description": "changed"}),
                                                 *SUITE.cases[1:]]})  # fmt: skip
    asyncio.run(runner.run(FILES, changed))
    assert runner.probes == 1  # the engine answered once: a new start does not probe again


@pytest.mark.skipif(os.environ.get("NEXTI_LIVE_ASE") != "1", reason="live Sybase ASE run: set NEXTI_LIVE_ASE=1")
def test_every_probe_of_the_catalog_holds_on_a_live_engine() -> None:
    # M28: the expected answer of each probe is what Sybase ASE 16 with its default options says.
    from nexti_core.spec.characterization import EngineQuirk

    register = [EngineQuirk(id=s.id, severity=s.severity, behavior=s.behavior, target=s.target, probe=s.probe,
                            expected=s.expected) for s in quirks.CATALOG.values() if s.probe]  # fmt: skip

    async def probe() -> tuple[dict[str, str], str]:
        runner = AseRunner()
        name = await runner._start()
        try:
            answers = quirks.probe_answers(await runner._isql(name, quirks.probe_script(register), 120))
            return answers, await runner._isql(name, quirks.environment_script(), 120)
        finally:
            await runner._stop(name)

    answers, environment = asyncio.run(probe())
    assert {q.id: answers.get(q.id) for q in register} == {q.id: q.expected for q in register}
    assert len(quirks.engine_environment(environment)) == len(quirks.ENVIRONMENT_PROBES)
