"""The live systems a project's legacy may run on (ADR-0052, ADR-0055): each kind validates and normalises its own
configuration; the credentials never travel in it."""

import pytest

from nexti_core.legacy_execution import KINDS, SybaseConfig, checked_config


def test_the_two_kinds_of_live_system_validate_their_configuration() -> None:
    assert KINDS == ("ibmi", "sybase")
    ibmi = checked_config("ibmi", {"host": "Pub400.com", "library": "aleja04911"})
    assert (ibmi["host"], ibmi["port"], ibmi["library"]) == ("pub400.com", 8476, "ALEJA04911")
    sybase = checked_config("sybase", {"host": "ASE-TEST.banco.local", "database": "cob_pagos"})
    assert sybase == {"host": "ase-test.banco.local", "port": 5000, "database": "cob_pagos"}
    with pytest.raises(ValueError, match="unknown kind"):
        checked_config("mainframe", {})


def test_a_sybase_configuration_names_a_database_and_never_a_credential() -> None:
    with pytest.raises(ValueError, match="database name"):
        SybaseConfig(host="ase", database="cob pagos")
    with pytest.raises(ValueError, match="host name"):
        SybaseConfig(host="tcp://ase:5000", database="cob_pagos")
    with pytest.raises(ValueError, match="less than or equal to 65535"):
        SybaseConfig(host="ase", port=70000, database="cob_pagos")
    with pytest.raises(ValueError, match="Extra inputs"):  # a password in the configuration is refused
        SybaseConfig.model_validate({"host": "ase", "database": "cob_pagos", "password": "x"})
