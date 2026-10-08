"""The live IBM i runner (ADR-0053) on the fictitious Cooperativa Andina program ACTSALDO, with the bridge replaced by
a function: what goes to the IBM i (the typed parameters from the program, the rows, the test library) and how its
answer becomes the golden master."""

import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest

from nexti_adapter_rpg.ibmi import IbmiRunner, IbmiTimeoutError, IbmiUnavailableError, parameter
from nexti_core.adapters import SourceFile
from nexti_core.legacy_execution import Credentials
from nexti_core.spec.characterization import Case, Column, Schema, StubAnswer, Suite, Table

FIXTURES = Path(__file__).parent / "fixtures" / "cooperativa"
FILES = [SourceFile(p.relative_to(FIXTURES).as_posix(), p.read_text(encoding="utf-8"))
         for p in sorted(FIXTURES.rglob("*")) if p.is_file() and "traces" not in p.parts]  # fmt: skip
CONFIG = {"host": "ibmi.example.com", "library": "nxtest", "programs": "nxpgm"}
PASSWORD = uuid.uuid4().hex
SCHEMA = Schema(tables=[
    Table(name="CUENTAS", key=["CTNUME"], columns=[Column(name="CTNUME", type="A(10)"),
                                                   Column(name="CTSALD", type="P(11:2)")]),
])  # fmt: skip
SUITE = Suite(program="ACTSALDO", schema_=SCHEMA, cases=[
    Case(name="debito_con_comision", rules=["RULE-001"], inputs={"PCUENTA": "0000000001", "PMONTO": "40", "PTIPO": "D"},
         setup={"CUENTAS": [{"CTNUME": "0000000001", "CTSALD": "100.00"}]}),
])  # fmt: skip


def bridge(answer: dict[str, Any], seen: list[dict[str, Any]]) -> Any:
    async def send(request: dict[str, Any]) -> dict[str, Any]:
        seen.append(request)
        return answer

    return send


def test_the_request_carries_the_typed_parameters_the_rows_and_the_test_library() -> None:
    seen: list[dict[str, Any]] = []
    answer = {"system": {"version": "V7R5M0", "ccsid": 284}, "cases": [{
        "name": "debito_con_comision", "error": None,
        "outputs": {"PCUENTA": "0000000001", "PMONTO": "40.00", "PTIPO": "D", "PRESULT": "000"},
        "tables": {"CUENTAS": [{"CTNUME": "0000000001", "CTSALD": "58.50"}]}}]}  # fmt: skip
    runner = IbmiRunner(CONFIG, Credentials(user="NXUSER", password=PASSWORD), bridge(answer, seen))
    master = asyncio.run(runner.run(FILES, SUITE))
    (request,) = seen
    assert request["program"] == "ACTSALDO"
    assert (request["library"], request["programs"]) == ("NXTEST", "NXPGM")
    assert request["parameters"] == [
        {"name": "PCUENTA", "type": "char", "length": 10, "decimals": 0},
        {"name": "PMONTO", "type": "packed", "length": 11, "decimals": 2},
        {"name": "PTIPO", "type": "char", "length": 1, "decimals": 0},
        {"name": "PRESULT", "type": "zoned", "length": 3, "decimals": 0},
    ]
    assert request["tables"] == [{"name": "CUENTAS", "key": ["CTNUME"]}]
    assert request["cases"][0]["setup"] == {"CUENTAS": [{"CTNUME": "0000000001", "CTSALD": "100.00"}]}
    assert request["connection"]["password"] == PASSWORD  # only to the bridge's stdin
    # The answer is the golden master: canonical outputs, the tables after the call, the IBM i release.
    assert (master.engine, master.from_traces) == ("ibmi", False)
    observation = master.results[0].observation
    assert observation.outputs["PRESULT"] == "0"
    assert observation.outputs["PMONTO"] == "40.00"
    assert observation.tables["CUENTAS"][0]["CTSALD"] == "58.50"
    assert [(e.key, e.value) for e in master.environment] == [
        ("os_release", "V7R5M0"), ("ccsid", "284"),  # measured on the IBM i
        ("rpg:dftactgrp", "*NO"), ("rpg:actgrp", "*CALLER"), ("rpg:datfmt", "*ISO (default)"),  # set by the program
    ]  # fmt: skip
    # R4: the behaviours the program relies on travel with the golden master to the developer.
    assert [q.id for q in master.quirks] == ["decimal-truncation", "record-not-found", "immediate-writes"]


def test_failures_say_whether_to_wait_retry_or_correct_the_suite() -> None:
    credentials = Credentials(user="NXUSER", password=PASSWORD)
    for kind, error in (("signon", IbmiUnavailableError), ("library", IbmiUnavailableError),
                        ("connect", IbmiTimeoutError), ("request", ValueError)):  # fmt: skip
        runner = IbmiRunner(CONFIG, credentials, bridge({"error": {"kind": kind, "message": "x"}}, []))
        with pytest.raises(error):
            asyncio.run(runner.run(FILES, SUITE))
    assert IbmiTimeoutError("x").transient
    assert not IbmiUnavailableError("x").transient
    # A case cannot stub a call: on a live IBM i the called programs run for real.
    stubbed = Suite(program="ACTSALDO", cases=[Case(name="con_stub", rules=["RULE-001"],
                                                    stubs={"OTRO": [StubAnswer(returns=0)]})])  # fmt: skip
    with pytest.raises(ValueError, match="cannot stub calls: con_stub"):
        asyncio.run(IbmiRunner(CONFIG, credentials, bridge({}, [])).run(FILES, stubbed))
    # A service program module has no program to call (yet), and an unknown program is a suite problem.
    with pytest.raises(IbmiUnavailableError, match="service program module"):
        asyncio.run(IbmiRunner(CONFIG, credentials, bridge({}, [])).run(FILES, Suite(
            program="VALCTA", cases=[Case(name="valida", rules=["RULE-001"])])))  # fmt: skip
    with pytest.raises(ValueError, match="no RPG program NOEXISTE"):
        asyncio.run(IbmiRunner(CONFIG, credentials, bridge({}, [])).run(FILES, Suite(
            program="NOEXISTE", cases=[Case(name="nada_aqui", rules=["RULE-001"])])))  # fmt: skip


def test_the_connection_check_signs_on_without_calling_a_program() -> None:
    seen: list[dict[str, Any]] = []
    credentials = Credentials(user="NXUSER", password=PASSWORD)
    ok = IbmiRunner(CONFIG, credentials, bridge({"system": {"version": "V7R5M0"}, "cases": []}, seen))
    assert asyncio.run(ok.check()) == (True, "signed on to ibmi.example.com (V7R5M0); library NXTEST, NXPGM usable")
    assert (seen[0]["cases"], seen[0]["parameters"]) == ([], [])
    refused = IbmiRunner(CONFIG, credentials, bridge({"error": {"kind": "signon", "message": "sign-on refused"}}, []))
    assert asyncio.run(refused.check()) == (False, "sign-on refused")


def test_parameter_types_the_bridge_can_pass() -> None:
    assert parameter("X", "P", 7, 2).type == "packed"
    assert parameter("X", "INT", 10, None) == parameter("X", "I", 10, None)
    assert parameter("X", "B", 4, None).length == 5
    assert parameter("X", "N", None, None).type == "char"
    with pytest.raises(IbmiUnavailableError, match="cannot be passed"):
        parameter("X", "F", 8, None)
