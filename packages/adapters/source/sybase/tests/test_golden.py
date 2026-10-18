"""Golden master of the fictitious application (plan M4 step 10): the scripts fit the code, the output is read back
exactly, and the recording made with a real Sybase ASE 16 is what CI compares against. The live run needs the
image datagrip/sybase:16.0 (9 GB) and is opt-in: NEXTI_LIVE_ASE=1."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from nexti_adapter_sybase import golden
from nexti_adapter_sybase.ase import AseRunner, MissingGoldenMasterError, RecordedRunner
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import OMITTED, StubAnswer, Suite

FIXTURES = Path(__file__).parent / "fixtures" / "pago_orden"
FILES = [SourceFile("sp/sp_pago_orden.sp", (FIXTURES / "sp_pago_orden.sp").read_text(encoding="utf-8"))]
SUITE = Suite.model_validate_json((FIXTURES / "characterization.json").read_text(encoding="utf-8"))


def _suite(change: dict[str, object]) -> Suite:
    data = json.loads(SUITE.model_dump_json(by_alias=True))
    data["cases"][0].update(change)
    return Suite.model_validate(data)


def test_external_programs_become_stubs_with_the_parameters_of_their_calls() -> None:
    stubs = golden.stubs(FILES)
    assert set(stubs) == {"db_cuentas..sp_debito", "cobis..sp_cerror"}
    debit = stubs["db_cuentas..sp_debito"]
    assert [(p.name, p.type, p.output) for p in debit.parameters] == [
        ("@i_cuenta", "char(10)", False), ("@i_tipo", "char(3)", False), ("@i_valor", "money", False),
        ("@i_referencia", "varchar(255)", False), ("@o_secuencial", "int", True),
    ]  # fmt: skip


def test_the_plan_rejects_a_suite_that_does_not_fit_the_code() -> None:
    plan = golden.plan(FILES, SUITE)
    assert plan.databases == ["cobis", "db_admin", "db_cuentas", "db_pagos", "nexti_gm"]
    with pytest.raises(golden.GoldenError, match="no parameter @i_moneda"):
        golden.plan(FILES, _suite({"inputs": {"@i_moneda": "USD"}}))
    with pytest.raises(golden.GoldenError, match="no column ord_total"):
        golden.plan(FILES, _suite({"setup": {"db_pagos..pg_orden": [{"ord_total": 1}]}}))
    with pytest.raises(golden.GoldenError, match="no output parameter @i_valor"):
        golden.plan(FILES, _suite({"stubs": {"db_cuentas..sp_debito": [{"outputs": {"@i_valor": 1}}]}}))
    data = json.loads(SUITE.model_dump_json(by_alias=True))
    data["schema"]["tables"] = data["schema"]["tables"][1:]
    data["cases"] = [dict(c, setup={}) for c in data["cases"]]
    with pytest.raises(golden.GoldenError, match=r"lacks tables the code uses: db_pagos\.\.pg_orden"):
        golden.plan(FILES, Suite.model_validate(data))


def test_values_are_read_back_whatever_they_contain() -> None:
    assert golden.read_values("3:a|b|~|0:|4:1:23   ") == ["a|b", None, "", "1:23"]


def test_the_observation_separates_business_messages_from_engine_errors() -> None:
    plan = golden.plan(FILES, SUITE)
    output = "\n".join([
        " NXR|5:50001", " NXO|@o_mensaje|12:NO PERMITIDO   ", " NXO|@o_movimiento|~",
        " NXT|db_pagos..pg_orden|4:7001|2:10|1:P|~|~",
        " NXC|cobis..sp_cerror|13:sp_pago_orden|5:50001|12:NO PERMITIDO",
        "Msg 50001, Level 16, State 1:", "Server 'MYSYBASE', Procedure 'sp_x', Line 3:", "raised by the program",
        " NXKN|1", " NXK|cobis..sp_cerror|13:sp_pago_orden|5:50001|12:NO PERMITIDO",
    ])  # fmt: skip
    seen = golden.observe(plan, output)
    assert seen.returns == 50001
    assert seen.error is None
    assert seen.outputs == {"@o_mensaje": "NO PERMITIDO", "@o_movimiento": None}
    assert seen.tables["db_pagos..pg_orden"] == [{"ord_numero": "7001", "ord_empresa": "10", "ord_estado": "P",
                                                  "ord_fecha_pago": None, "ord_comision": None}]  # fmt: skip
    assert seen.calls[0].arguments == {"@t_from": "sp_pago_orden", "@i_num": "50001", "@i_msg": "NO PERMITIDO"}
    assert seen.undone == []
    assert seen.messages == ["50001: Server 'MYSYBASE', Procedure 'sp_x', Line 3: raised by the program"]


def test_a_substitute_writes_the_rows_the_case_declares_inside_the_callers_transaction() -> None:
    # ADR-0055 (transactional substitutes): the stub of sp_debito leaves the account's balance the case says, as
    # an update by the table's key (or an insert when the row is new), before it answers; being a statement of
    # the stub, it runs inside the program's transaction and a rollback undoes it.
    effects = {"db_cuentas..ct_cuenta": [{"cta_numero": "1000000001", "cta_tipo": "CTE", "cta_saldo": "399.3700"}]}
    suite = _suite({"stubs": {"db_cuentas..sp_debito": [{"returns": 0, "effects": effects}]}})
    plan = golden.plan(FILES, suite)
    script = golden.case_script(plan, suite.cases[0])
    expected = ("if exists (select 1 from db_cuentas..ct_cuenta where cta_numero = '1000000001' and cta_tipo = 'CTE') "
                "update db_cuentas..ct_cuenta set cta_saldo = 399.3700 where cta_numero = '1000000001' and "
                "cta_tipo = 'CTE' else insert db_cuentas..ct_cuenta (cta_numero, cta_tipo, cta_saldo) values "
                "('1000000001', 'CTE', 399.3700)")  # fmt: skip
    assert expected in script
    assert script.index("create procedure dbo.sp_debito") < script.index(expected) < script.index("return 0")
    # The table, its columns and its key are checked against the schema before anything runs.
    with pytest.raises(golden.GoldenError, match=r"writes db_x\.\.y, which is not in the schema"):
        golden.plan(FILES, _suite({"stubs": {"db_cuentas..sp_debito": [{"effects": {"db_x..y": [{"a": 1}]}}]}}))
    with pytest.raises(golden.GoldenError, match="lacks its key column"):
        golden.plan(FILES, _suite({"stubs": {"db_cuentas..sp_debito": [
            {"effects": {"db_cuentas..ct_cuenta": [{"cta_saldo": "1.0000"}]}}]}}))  # fmt: skip
    row = {"cta_numero": "1", "cta_tipo": "CTE", "cta_x": 1}
    with pytest.raises(golden.GoldenError, match="has no column cta_x"):
        golden.plan(
            FILES, _suite({"stubs": {"db_cuentas..sp_debito": [{"effects": {"db_cuentas..ct_cuenta": [row]}}]}})
        )


def test_a_call_the_rollback_undid_is_reported_apart_from_the_ones_in_the_final_state() -> None:
    # ADR-0055: the attempts are printed as they happen (NXC), the rows that survived the unit of work at the end
    # (NXK). A debit inside the rolled-back transaction is `undone`; the error log after the rollback survived.
    plan = golden.plan(FILES, SUITE)
    debit = "db_cuentas..sp_debito|10:1000000001|3:CTE|8:100.0000|10:PAGO ORDEN"
    log = "cobis..sp_cerror|13:sp_pago_orden|5:50006|17:ERROR EN COMISION"
    output = "\n".join([" NXR|5:50006", f" NXC|{debit}", f" NXC|{log}", " NXKN|1", f" NXK|{log}"])
    seen = golden.observe(plan, output)
    assert [c.program for c in seen.calls] == ["cobis..sp_cerror"]
    assert [c.program for c in seen.undone] == ["db_cuentas..sp_debito"]
    assert seen.undone[0].arguments["@i_valor"] == "100.0000"
    # Without the dump (a case cut before it) every attempt counts as a call, as the recordings before it meant.
    cut = golden.observe(plan, "\n".join([" NXR|5:50006", f" NXC|{debit}", f" NXC|{log}"]))
    assert [c.program for c in cut.calls] == ["db_cuentas..sp_debito", "cobis..sp_cerror"]
    assert cut.undone == []
    # The script prints the count and then the rows, after the program's outputs and before the tables.
    script = golden.case_script(plan, SUITE.cases[0])
    assert script.index("select 'NXO|") < script.index("select 'NXKN|'") < script.index("select 'NXK|'")
    assert script.index("select 'NXK|'") < script.index("select 'NXT|")
    broken = golden.observe(plan, "Msg 208, Level 16, State 1:\nServer 'MYSYBASE', Line 5:\nx..y not found.")
    assert broken.error is not None
    assert "Msg 208" in broken.error


def test_a_substitute_tells_an_omitted_argument_from_an_explicit_null() -> None:
    # ADR-0056 (N7): the inputs of a substitute default to a sentinel of their type instead of null, the log marks
    # an omitted argument apart (`^`) and the call drops it, so a target that passes NULL where the legacy passed
    # nothing differs. Outputs stay `= null`: they are always bound.
    plan = golden.plan(FILES, SUITE)
    script = golden.case_script(plan, SUITE.cases[0])
    assert "create procedure dbo.sp_debito @i_cuenta char(10) = '~', @i_tipo char(3) = '~', " in script
    assert "@i_valor money = -922337203685477.5807, @i_referencia varchar(255) = '~', " in script
    assert "@o_secuencial int = null output as" in script
    assert "case when @i_cuenta = '~' then '^' else case when @i_cuenta is null then '~'" in script
    assert golden.sentinel("numeric(5,2)") == "-999.99"
    assert golden.sentinel("numeric(3,3)") == "-0.999"
    assert golden.sentinel("decimal") == "-999999999999999999"
    assert golden.sentinel("tinyint") == "255"
    assert golden.sentinel("smalldatetime") == "'2079-06-06 00:00:00'"
    assert golden.sentinel("bit") is None
    assert golden.sentinel("text") is None
    assert golden.read_values("^|~|2:ab") == [OMITTED, None, "ab"]
    output = "\n".join([" NXR|1:0", " NXC|db_cuentas..sp_debito|10:1000000001|^|8:100.0000|~", " NXKN|1",
                        " NXK|db_cuentas..sp_debito|10:1000000001|^|8:100.0000|~"])  # fmt: skip
    seen = golden.observe(plan, output)
    assert seen.calls[0].arguments == {"@i_cuenta": "1000000001", "@i_valor": "100.0000", "@i_referencia": None}


def test_a_substitute_raises_the_messages_the_case_declares_before_it_returns() -> None:
    # ADR-0056 (N1): a case says the called program fails with raiserror; the substitute raises the same texts in
    # the user range and then returns the status, so the legacy is observed going on (or not) exactly as with the
    # real program, and the target has to do the same.
    suite = _suite({"stubs": {"db_cuentas..sp_debito": [{"returns": 5, "messages": ["Saldo insuficiente"]}]}})
    plan = golden.plan(FILES, suite)
    script = golden.case_script(plan, suite.cases[0])
    raised = f"raiserror {golden.STUB_MESSAGE_NUMBER} 'Saldo insuficiente'\n    return 5"
    assert raised in script
    assert script.index("insert nexti_gm..nx_call") < script.index(raised)
    # The answer without messages serialises as before (the recordings keep their keys).
    assert json.loads(StubAnswer(returns=5).model_dump_json()) == {"returns": 5, "outputs": {}}
    assert json.loads(StubAnswer(messages=["x"]).model_dump_json()) == {"returns": 0, "outputs": {}, "messages": ["x"]}


def test_the_recorded_golden_master_is_the_behaviour_of_the_legacy() -> None:
    master = asyncio.run(RecordedRunner(FIXTURES / "golden", "replay").run(FILES, SUITE))
    assert master.engine == "sybase-ase-16.0"
    seen = {r.case.name: r.observation for r in master.results}
    assert len(seen) == len(SUITE.cases)
    assert not any(o.error for o in seen.values())
    web = seen["web_order_pays_half_the_service_tariff"]
    assert web.returns == 0
    assert web.outputs["@o_movimiento"] == "900001"
    assert web.tables["db_pagos..pg_orden"][0]["ord_comision"] == "0.6300"  # round(1.25 / 2, 2)
    assert web.tables["db_pagos..pg_orden"][0]["ord_fecha_pago"] == "2026-03-02T09:30:00.000"
    assert [c.arguments["@i_valor"] for c in web.calls] == ["100.6300"]
    separate = seen["separate_commission_is_a_second_debit"]
    assert [c.arguments["@i_valor"] for c in separate.calls] == ["100.0000", "1.5000"]
    assert seen["current_account_overdraws_up_to_100"].returns == 0
    assert seen["overdraft_beyond_100_is_rejected"].returns == 50004
    undone = seen["failed_commission_undoes_the_payment"]
    assert undone.returns == 50006
    assert undone.tables["db_pagos..pg_orden"][0]["ord_estado"] == "P"
    # Both debits were called inside the transaction the program rolled back (ADR-0055): their effects are not in
    # the final state (the order stays pending), so they are `undone`; the error log, after the rollback, survived.
    assert [c.program for c in undone.calls] == ["cobis..sp_cerror"]
    assert [c.program for c in undone.undone] == ["db_cuentas..sp_debito", "db_cuentas..sp_debito"]
    assert [c.arguments["@i_valor"] for c in undone.undone] == ["100.0000", "1.5000"]
    assert [c.program for c in seen["failed_debit_undoes_the_payment"].undone] == ["db_cuentas..sp_debito"]
    assert all(o.undone == [] for name, o in seen.items() if not name.startswith("failed_"))


def test_replay_without_a_recording_says_so() -> None:
    changed = _suite({"description": "a suite nobody ran"})
    with pytest.raises(MissingGoldenMasterError):
        asyncio.run(RecordedRunner(FIXTURES / "golden", "replay").run(FILES, changed))


@pytest.mark.skipif(os.environ.get("NEXTI_LIVE_ASE") != "1", reason="live Sybase ASE run: set NEXTI_LIVE_ASE=1")
def test_a_live_run_reproduces_the_recording() -> None:
    recorded = asyncio.run(RecordedRunner(FIXTURES / "golden", "replay").run(FILES, SUITE))
    live = asyncio.run(AseRunner().run(FILES, SUITE))
    assert [r.observation for r in live.results] == [r.observation for r in recorded.results]
    # ADR-0047: the instrumented copy behaves as the original in every case, and its coverage is measured.
    assert live.coverage is not None
    assert live.coverage.unreliable == []
    assert live.coverage.exercised
    print("legacy coverage:", live.coverage.note())
    # M28: every probe of the quirks the program relies on is confirmed by the real engine, and its settings measured
    probed = [q for q in live.quirks if q.probe]
    assert probed
    assert [(q.id, q.observed) for q in probed if not q.confirmed] == []
    assert {"version", "language", "isolation-level"} <= {e.key for e in live.environment if e.source == "engine"}
    print("environment:", [(e.key, e.value) for e in live.environment])


def test_output_parameters_the_program_never_assigns_are_detected() -> None:
    # ADR-0044: an OUTPUT no statement writes (not even as `@x = @p output` of a nested call) echoes the caller.
    lines = [
        "create procedure sp_x @i_a int, @o_b int output, @o_c int output, @o_d int output, @o_e int output as",
        "begin",
        "  select @o_b = 1",
        "  exec @rc = sp_y @x = @o_c output",
        "  declare cur cursor for select 1",
        "  open cur",
        "  fetch cur into @o_e",
        "  return 0",
        "end",
    ]
    (_, program) = golden.procedures([SourceFile("sp/sp_x.sp", "\n".join(lines) + "\n")])[0]
    assert golden.unassigned_outputs(program) == ["@o_d"]
    (_, pago) = golden.procedures(FILES)[0]
    assert golden.unassigned_outputs(pago) == []  # the fixture assigns both of its outputs


def test_a_batch_of_cases_is_split_by_its_markers_and_a_cut_case_is_absent() -> None:
    from nexti_adapter_sybase.ase import _split_cases

    output = "header\n NXCASE|0\nNXR|0\nMsg 50001, Level 16\n NXCASE|1\nNXR|1\n"
    parts = _split_cases(output, 3)
    assert set(parts) == {0, 1}  # case 2 never printed its marker: it runs again alone
    assert "Msg 50001" in parts[0]  # an engine message stays with the case that raised it
    assert parts[1].strip() == "NXR|1"


def test_a_correction_runs_only_the_changed_cases_and_none_needs_no_engine() -> None:
    # Plan step 3b: the cases already observed with the same code, schema and stubs are not run again.
    from nexti_adapter_sybase.ase import AseRunner

    class FakeAse(AseRunner):
        def __init__(self) -> None:
            super().__init__(batch_size=5, coverage=False)
            self.starts = 0
            self.batches: list[int] = []

        async def _start(self, network: str = "none") -> str:
            self.starts += 1
            return "engine"

        async def _stop(self, name: str) -> None:
            return None

        async def _isql(self, name: str, script: str, seconds: int) -> str:
            if "NXCASE|" not in script:
                return ""  # the setup script loads without errors
            count = script.count("select 'NXCASE|")
            self.batches.append(count)
            return "\n".join(f"NXCASE|{index}\nNXR|1:0" for index in range(count))  # values as length:text

    runner = FakeAse()
    first = asyncio.run(runner.run(FILES, SUITE))
    assert len(first.results) == len(SUITE.cases)
    assert (runner.starts, runner.batches) == (1, [5, 5, 2])  # 12 cases in batches of 5, one engine start
    again = asyncio.run(runner.run(FILES, SUITE))
    assert runner.starts == 1  # nothing changed: no engine started
    assert [r.case.name for r in again.results] == [c.name for c in SUITE.cases]
    changed = SUITE.model_copy(update={"cases": [SUITE.cases[0].model_copy(update={"description": "changed"}),
                                                 *SUITE.cases[1:]]})  # fmt: skip
    asyncio.run(runner.run(FILES, changed))
    assert (runner.starts, runner.batches[-1]) == (2, 1)  # only the changed case ran


def test_an_engine_that_stops_answering_cuts_the_recording_as_transient() -> None:
    # Plan step 3b: a wedged engine is not waited case by case (a real run lost 87 minutes); the recording is cut as
    # a transient failure and the phase tries again with a fresh engine.
    from nexti_adapter_sybase.ase import AseRunner, LegacyEngineTimeoutError

    class SilentAse(AseRunner):
        async def _start(self, network: str = "none") -> str:
            return "engine"

        async def _stop(self, name: str) -> None:
            return None

        async def _isql(self, name: str, script: str, seconds: int) -> str:
            return ""  # the setup loads, then nothing answers

    with pytest.raises(LegacyEngineTimeoutError, match="stopped answering") as cut:
        asyncio.run(SilentAse().run(FILES, SUITE))
    assert cut.value.transient


def test_the_branches_of_the_program_are_marked_in_a_copy_that_still_parses() -> None:
    # ADR-0047: every THEN, ELSE, implicit ELSE and loop body gets a mark in a COPY; the original is untouched.
    from nexti_adapter_sybase.coverage import executed, instrument
    from nexti_adapter_sybase.parser import parse

    (_, program) = golden.procedures(FILES)[0]
    copy = instrument(FILES[0].text, program)
    kinds = {b.kind for b in copy.branches}
    assert {"if-true", "if-false", "else"} <= kinds
    assert all(b.measurable for b in copy.branches)
    assert copy.text.count("print 'NXB|") == len(copy.branches)
    assert parse(copy.text)  # the copy is still a valid procedure
    assert FILES[0].text.count("NXB|") == 0
    hits, rest = executed("NXB|35-39:if-true\nNXR|1:0\n  NXB|81-81:if-true  ")
    assert hits == {"35-39:if-true", "81-81:if-true"}
    assert rest.strip() == "NXR|1:0"
    # A one-statement body sharing its line with the condition cannot be marked without risk: not measurable.
    one_line = "create procedure sp_x @a int as\nbegin\n  if @a = 1 select @a = 2\n  return 0\nend\n"
    (_, tiny) = golden.procedures([SourceFile("sp/sp_x.sp", one_line)])[0]
    marked = instrument(one_line, tiny)
    assert [(b.kind, b.measurable) for b in marked.branches] == [("if-true", False), ("if-false", True)]


def test_the_coverage_pass_marks_a_case_unreliable_when_the_copy_behaves_differently() -> None:
    from nexti_adapter_sybase.ase import AseRunner

    class FakeAse(AseRunner):
        def __init__(self) -> None:
            super().__init__(batch_size=50)
            self.copy = False

        async def _start(self, network: str = "none") -> str:
            return "engine"

        async def _stop(self, name: str) -> None:
            return None

        async def _isql(self, name: str, script: str, seconds: int) -> str:
            if "NXCASE|" not in script:
                self.copy = self.copy or "drop procedure" in script  # the instrumented copy is installed
                return ""
            count = script.count("select 'NXCASE|")
            lines = []
            for index in range(count):
                lines.append(f"NXCASE|{index}")
                if self.copy:
                    lines.append("NXB|35-39:if-true")
                    lines.append("NXR|1:9" if index == 0 else "NXR|1:0")  # the first case behaves differently
                else:
                    lines.append("NXR|1:0")
            return "\n".join(lines)

    master = asyncio.run(FakeAse().run(FILES, SUITE))
    assert master.coverage is not None
    assert master.coverage.unreliable == [SUITE.cases[0].name]
    assert master.coverage.executed[SUITE.cases[1].name] == ["35-39:if-true"]
    assert "35-39:if-true" in master.coverage.exercised
    assert master.coverage.note().startswith("1 of ")
    assert "1 case(s) without reliable coverage" in master.coverage.note()
    assert all(r.observation.returns == 0 for r in master.results)  # the oracle comes from the original
    # The recording carries the coverage the real engine measured, with every case reliable.
    recorded = asyncio.run(RecordedRunner(FIXTURES / "golden", "replay").run(FILES, SUITE))
    assert recorded.coverage is not None
    assert recorded.coverage.unreliable == []


def test_the_engine_a_target_runs_against_has_the_tables_the_substitutes_and_the_log_but_not_the_program() -> None:
    # ADR-0055 (point 10): the target is what runs, so the legacy program is not installed; each case is prepared
    # with the same rows and substitutes the golden master used, as batches a JDBC client runs one by one.
    plan = golden.plan(FILES, SUITE)
    script = golden.setup_script(plan, with_sources=False)
    assert "create table nx_call" in script
    assert "create table db_pagos..pg_orden" in script
    assert "create procedure dbo.sp_debito" in script  # the placeholder of the substitute
    assert "sp_pago_orden" not in script
    assert "sp_pago_orden" in golden.setup_script(plan)
    case = next(c for c in SUITE.cases if c.name == "failed_commission_undoes_the_payment")
    batches = golden.case_setup_batches(plan, case)
    assert batches[0] == "use nexti_gm"
    assert batches[1] == "truncate table nx_call"
    assert any(b.startswith("insert db_pagos..pg_orden (") for b in batches)
    assert "use db_cuentas" in batches
    assert any(b.startswith("create procedure dbo.sp_debito") and "return " in b for b in batches)
    assert batches[-1] == "use nexti_gm"
    assert not any(b.strip() == "go" or "exec @nx_rc" in b for b in batches)
    assert golden.CALLS_QUERY == "select program, args from nexti_gm..nx_call order by seq"


def test_the_same_engine_starts_on_a_private_network_and_hands_the_target_what_it_needs() -> None:
    from nexti_adapter_sybase.ase import SameEngine

    commands: list[list[str]] = []

    class Fake(AseRunner):
        def _cli(self, args: list[str], stdin: str | None = None, timeout: int = 60) -> tuple[int, str]:
            commands.append(args)
            if args[0] == "logs":
                return 0, "SYBASE INITIALIZED"
            if args[0] == "exec":
                return 0, "NXREADY\n"
            return 0, "ok\n"

    async def run() -> None:
        engine = SameEngine(FILES, SUITE, Fake(start_seconds=5))
        async with engine as target:
            assert target.network.startswith("nexti-eq-")
            assert target.name is not None
            assert target.name.startswith("nexti-ase-")
            assert target.jdbc_url == f"jdbc:jtds:sybase://{target.name}:5000/nexti_gm;prepareSQL=0"  # ADR-0056
            assert target.programs["db_cuentas..sp_debito"] == ["@i_cuenta", "@i_tipo", "@i_valor", "@i_referencia"]
            assert target.setup_for(SUITE.cases[0])[0] == "use nexti_gm"
            made = target.calls(
                [{"program": "db_cuentas..sp_debito", "args": "10:1000000001|3:CTE|8:100.6300|10:PAGO ORDEN"}]
            )
            assert made[0].arguments == {"@i_cuenta": "1000000001", "@i_tipo": "CTE", "@i_valor": "100.6300",
                                         "@i_referencia": "PAGO ORDEN"}  # fmt: skip
        started = next(a for a in commands if a[0] == "run")
        assert started[started.index("--network") + 1] == target.network
        assert ["network", "create", "--internal", target.network] in commands
        assert ["network", "rm", target.network] in commands
        assert any(a[0] == "kill" for a in commands)

    asyncio.run(run())


def test_a_statement_error_the_program_lived_through_is_a_message_not_a_failure_of_the_engine() -> None:
    # ADR-0056: the only way into a rollback branch guarded by @@error is a statement that fails (a NULL into a
    # NOT NULL column, Msg 515, level 16); the program handles it and returns. That is the behaviour the golden
    # master must keep, so the case is observed with the message, not refused as an engine failure.
    plan = golden.plan(FILES, SUITE)
    output = "\n".join([
        "Msg 515, Level 16, State 2:", "Server 'MYSYBASE', Procedure 'sp_pago_orden', Line 144:",
        "Attempt to insert NULL value into column 'ord_fecha_pago'; column does not allow nulls. "
        "Update fails.",
        " NXR|5:50007", " NXKN|0",
    ])  # fmt: skip
    seen = golden.observe(plan, output)
    assert seen.error is None
    assert seen.returns == 50007
    assert seen.messages == ["Msg 515: Server 'MYSYBASE', Procedure 'sp_pago_orden', Line 144: Attempt to insert NULL "
                             "value into column 'ord_fecha_pago'; column does not allow nulls. Update fails."]  # fmt: skip
    # A fatal error (level 17 and up), or a program that never returned, still fails the case.
    fatal = golden.observe(plan, "Msg 1105, Level 17, State 2:\nServer 'MYSYBASE':\nCan't allocate space.\n NXR|1:0")
    assert fatal.error is not None
    cut = golden.observe(plan, "Msg 515, Level 16, State 2:\nServer 'MYSYBASE', Line 3:\nnull not allowed.")
    assert cut.error is not None
