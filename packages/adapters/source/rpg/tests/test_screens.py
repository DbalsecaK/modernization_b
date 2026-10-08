"""Interactive RPG programs (R3): the records of a display file as screen specs, like the BMS maps of CICS, and the
golden master of the interactive program from recorded 5250 session traces (the fictitious CONSCTA)."""

import asyncio
import uuid
from pathlib import Path

import pytest

from nexti_adapter_cobol import TraceRunner
from nexti_adapter_rpg import RpgAdapter, dds
from nexti_adapter_rpg.ibmi import IbmiRunner, IbmiUnavailableError
from nexti_adapter_rpg.screens import screen_size
from nexti_core.adapters import SourceFile
from nexti_core.legacy_execution import Credentials
from nexti_core.spec.characterization import Case, Suite

FIXTURES = Path(__file__).parent / "fixtures" / "cooperativa"
FILES = [SourceFile(p.relative_to(FIXTURES).as_posix(), p.read_text(encoding="utf-8"))
         for p in sorted(FIXTURES.rglob("*")) if p.is_file()]  # fmt: skip
ADAPTER = RpgAdapter()


def test_a_display_record_is_a_screen_spec_with_its_fields_literals_and_keys() -> None:
    (screen,) = ADAPTER.screens(FILES)
    assert (screen.id, screen.name, screen.mapset, screen.map) == ("SCR-PANTALLA", "CONSULTA DE CUENTAS",
                                                                   "CONSCTAD", "PANTALLA")  # fmt: skip
    assert (screen.rows, screen.columns) == (24, 80)
    account = screen.field("SCCTA")
    assert account is not None
    assert (account.kind, account.position.row if account.position else None, account.length) == ("input", 4, 10)
    assert account.type == "text(fixed,10,ebcdic)"
    balance = screen.field("SCSALD")
    assert balance is not None
    assert (balance.kind, balance.type, balance.format) == ("output", "decimal(11,2,signed)", "EDTCDE(J)")
    assert [f.initial for f in screen.fields if f.kind == "literal"] == ["CONSULTA DE CUENTAS", "Cuenta:", "Saldo:"]
    assert [(a.key, a.label) for a in screen.actions] == [("ENTER", "Enter"), ("PF3", "Salir")]


def test_the_ui_phase_reads_the_5250_screens() -> None:
    from nexti_orchestration.ui import screens_of

    assert [s.id for s in screens_of(FILES)] == ["SCR-PANTALLA"]


def test_screen_sizes_and_field_rules_from_the_dds() -> None:
    source = (
        "     A                                      DSPSIZ(*DS4)\n"
        "     A          R ALTA                      CA12(12 'Cancelar')\n"
        "     A            NOMBRE        30A  B  5 10CHECK(ME)\n"
        "     A                                      ERRMSG('Nombre obligatorio' 41)\n"
        "     A            EDAD           3Y 0B  6 10RANGE(18 99)\n"
        "     A                                      DSPATR(HI)\n"
    )
    display = dds.parse("qddssrc/ALTA.dspf", source)
    assert screen_size(display) == (27, 132)
    (screen,) = ADAPTER.screens([SourceFile("qddssrc/ALTA.dspf", source)])
    name, age = screen.field("NOMBRE"), screen.field("EDAD")
    assert name is not None
    assert age is not None
    assert (name.required, name.message) == (True, "Nombre obligatorio")
    assert (age.type, age.validation, age.attributes) == ("decimal(3,0,signed)", "RANGE(18 99)",
                                                          ("unprotected", "numeric", "bright"))  # fmt: skip
    assert [(a.key, a.description) for a in screen.actions][1] == ("PF12", "does not return the screen's data")


def test_the_interactive_golden_master_comes_from_5250_session_traces() -> None:
    suite = Suite(program="CONSCTA", cases=[
        Case(name="consulta_cuenta_existente", rules=["RULE-001"]),
        Case(name="salir_con_f3", rules=["RULE-003"]),
    ])  # fmt: skip
    master = asyncio.run(TraceRunner(branches=ADAPTER.coverage_branches).run(FILES, suite))
    assert (master.engine, master.from_traces) == ("ibmi-trace", True)
    assert master.results[0].case.inputs == {"SCCTA": "0000000001", "KEY": "ENTER"}
    assert master.results[0].observation.outputs["SCSALD"] == "1250.75"
    # A live IBM i cannot run it without a terminal: the phase waits with the reason, never hangs.
    runner = IbmiRunner({"host": "ibmi.example.com", "library": "NXTEST"},
                        Credentials(user="NXUSER", password=uuid.uuid4().hex))  # fmt: skip
    with pytest.raises(IbmiUnavailableError, match="interactive"):
        asyncio.run(runner.run(FILES, suite))
