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
from nexti_core.spec.characterization import Suite

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
    ])  # fmt: skip
    seen = golden.observe(plan, output)
    assert seen.returns == 50001
    assert seen.error is None
    assert seen.outputs == {"@o_mensaje": "NO PERMITIDO", "@o_movimiento": None}
    assert seen.tables["db_pagos..pg_orden"] == [{"ord_numero": "7001", "ord_empresa": "10", "ord_estado": "P",
                                                  "ord_fecha_pago": None, "ord_comision": None}]  # fmt: skip
    assert seen.calls[0].arguments == {"@t_from": "sp_pago_orden", "@i_num": "50001", "@i_msg": "NO PERMITIDO"}
    assert seen.messages == ["50001: Server 'MYSYBASE', Procedure 'sp_x', Line 3: raised by the program"]
    broken = golden.observe(plan, "Msg 208, Level 16, State 1:\nServer 'MYSYBASE', Line 5:\nx..y not found.")
    assert broken.error is not None
    assert "Msg 208" in broken.error


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
    # The first debit ran inside the transaction the program rolled back: it had no effect.
    assert [c.program for c in undone.calls] == ["cobis..sp_cerror"]


def test_replay_without_a_recording_says_so() -> None:
    changed = _suite({"description": "a suite nobody ran"})
    with pytest.raises(MissingGoldenMasterError):
        asyncio.run(RecordedRunner(FIXTURES / "golden", "replay").run(FILES, changed))


@pytest.mark.skipif(os.environ.get("NEXTI_LIVE_ASE") != "1", reason="live Sybase ASE run: set NEXTI_LIVE_ASE=1")
def test_a_live_run_reproduces_the_recording() -> None:
    recorded = asyncio.run(RecordedRunner(FIXTURES / "golden", "replay").run(FILES, SUITE))
    live = asyncio.run(AseRunner().run(FILES, SUITE))
    assert [r.observation for r in live.results] == [r.observation for r in recorded.results]
