"""The legacy on a Sybase ASE test server of the customer (`kind = sybase`, ADR-0055): the platform installs nothing
there but its call log, checks that the customer's objects exist, refuses cases that stub a call (the programs run
for real) and never puts the password on a command line."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from nexti_adapter_sybase import golden
from nexti_adapter_sybase.ase import LiveAseRunner
from nexti_core.adapters import SourceFile
from nexti_core.legacy_execution import Credentials
from nexti_core.spec.characterization import Suite

FIXTURES = Path(__file__).parent / "fixtures" / "pago_orden"
FILES = [SourceFile("sp/sp_pago_orden.sp", (FIXTURES / "sp_pago_orden.sp").read_text(encoding="utf-8"))]
SUITE = Suite.model_validate_json((FIXTURES / "characterization.json").read_text(encoding="utf-8"))
CONFIG = {"host": "ase-test.banco.local", "port": 5000, "database": "cob_pagos"}
SECRET = "s3cret"  # noqa: S105 - the fake password the test follows through the docker commands


def _without_stubs() -> Suite:
    data = json.loads(SUITE.model_dump_json(by_alias=True))
    for case in data["cases"]:
        case["stubs"] = {}
    return Suite.model_validate(data)


class Client(LiveAseRunner):
    """The docker CLI replaced: a client container that answers as a customer's server would."""

    def __init__(self, missing: str = "") -> None:
        super().__init__(CONFIG, Credentials(user="nx user", password=SECRET))
        self.commands: list[tuple[list[str], str | None]] = []
        self.missing = missing

    def _cli(self, args: list[str], stdin: str | None = None, timeout: int = 60) -> tuple[int, str]:
        self.commands.append((args, stdin))
        if args[0] in ("run", "kill"):
            return 0, "abc123\n"
        script = (stdin or "").split("\n", 1)[1]
        if "NXREADY" in script:
            return 0, " NXREADY|Adaptive Server Enterprise/16.0 SP03\n"
        if "NXMISSING" in script:
            return 0, self.missing
        count = script.count("select 'NXCASE|")
        return 0, "\n".join(f"NXCASE|{i}\nNXR|1:0\nNXKN|0" for i in range(count))


def test_the_live_setup_installs_only_the_call_log_and_checks_the_customers_objects() -> None:
    plan = replace(golden.plan(FILES, SUITE), work="cob_pagos")
    script = golden.live_setup_script(plan)
    assert script.startswith("use cob_pagos\ngo\n")
    assert "create database" not in script
    assert "disk init" not in script
    assert "create procedure" not in script
    assert "if object_id('dbo.sp_pago_orden') is null select 'NXMISSING|procedure dbo.sp_pago_orden'" in script
    assert "if object_id('db_pagos..pg_orden') is null select 'NXMISSING|table db_pagos..pg_orden'" in script
    assert "if object_id('db_cuentas..sp_debito') is null select 'NXMISSING|procedure db_cuentas..sp_debito'" in script
    assert "create table nx_call" in script
    assert golden.missing_objects("x\n NXMISSING|table db_pagos..pg_orden \n") == ["table db_pagos..pg_orden"]
    # The cases run in the program's database, where the call log is; nothing is created for the stubs.
    case = golden.case_script(replace(plan, stubs={}), SUITE.cases[0])
    assert "use cob_pagos" in case
    assert "nexti_gm" not in case
    assert "create procedure" not in case


def test_stubbed_cases_are_refused_and_the_password_travels_only_on_standard_input() -> None:
    client = Client()
    with pytest.raises(ValueError, match="run for real"):
        asyncio.run(client.run(FILES, SUITE))
    master = asyncio.run(client.run(FILES, _without_stubs()))
    assert master.engine == "sybase-ase-customer"
    assert len(master.results) == len(SUITE.cases)
    assert master.coverage is None  # no instrumented copy replaces the customer's program
    assert all(r.observation.returns == 0 for r in master.results)
    started = next(args for args, _ in client.commands if args[0] == "run")
    assert (started[-4], started[-3]) == ("--entrypoint", "sleep")  # a client, not an engine
    assert "--network" not in started  # it reaches the customer's server
    sessions = [(args, stdin) for args, stdin in client.commands if args[0] == "exec"]
    assert sessions
    for args, stdin in sessions:
        assert SECRET not in " ".join(args)
        assert "'nx user'" in args[-1]
        assert "ase-test.banco.local:5000" in args[-1]
        assert stdin is not None
        assert stdin.startswith(SECRET + "\n")
    assert not any("create procedure" in (stdin or "") for _, stdin in sessions)


def test_a_missing_object_on_the_customers_server_stops_the_run_with_its_name() -> None:
    client = Client(missing=" NXMISSING|table db_pagos..pg_orden\n NXMISSING|procedure db_cuentas..sp_debito\n")
    expected = r"lacks what the program needs: table db_pagos\.\.pg_orden, procedure db_cuentas\.\.sp_debito"
    with pytest.raises(golden.GoldenError, match=expected):
        asyncio.run(client.run(FILES, _without_stubs()))
    assert any(args[0] == "kill" for args, _ in client.commands)  # the client container never outlives the run


def test_the_connection_check_signs_on_and_uses_the_database() -> None:
    ok, detail = asyncio.run(Client().check())
    assert ok
    assert detail == ("signed on to ase-test.banco.local:5000, database cob_pagos usable "
                      "(Adaptive Server Enterprise/16.0 SP03)")  # fmt: skip

    class Refused(Client):
        def _cli(self, args: list[str], stdin: str | None = None, timeout: int = 60) -> tuple[int, str]:
            if args[0] == "exec":
                return 0, "CT-LIBRARY error:\n\tct_connect(): Login failed.\n"
            return super()._cli(args, stdin, timeout)

    ok, detail = asyncio.run(Refused().check())
    assert not ok
    assert detail.startswith("ase-test.banco.local:5000 did not sign on: ")
    assert "Login failed" in detail
