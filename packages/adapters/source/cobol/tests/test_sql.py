"""EXEC SQL in the local COBOL engine (ADR-0056, point 7): DB2 statements as PostgreSQL understands them, the
tables of the suite as PostgreSQL tables, the rows of a case and the dump after the task."""

import asyncio
import os
from pathlib import Path

import pytest

from nexti_adapter_cobol import CobolAdapter
from nexti_adapter_cobol.gnucobol import GnuCobolRunner
from nexti_adapter_cobol.local import translate
from nexti_adapter_cobol.sql import case_sql, dump_sql, parse_dump, pg_type, rewrite_sql, schema_sql
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import Case, Schema, Suite

SCHEMA = Schema.model_validate({"tables": [
    {"name": "SEG.USUARIOS", "key": ["COD_USUARIO"], "columns": [
        {"name": "COD_USUARIO", "type": "CHAR(8)", "nullable": False},
        {"name": "NOMBRE", "type": "VARCHAR(40)", "nullable": True},
        {"name": "SALDO", "type": "DECIMAL(11,2)", "nullable": False},
        {"name": "ALTA", "type": "DATE", "nullable": True},
        {"name": "INTENTOS", "type": "INTEGER", "nullable": False},
    ]},
    {"name": "CUENTAS", "key": ["CTA_NUMERO"], "columns": [
        {"name": "CTA_NUMERO", "type": "PIC 9(10)", "nullable": False},
        {"name": "CTA_SALDO", "type": "PIC S9(11)V99 COMP-3", "nullable": False},
    ]},
]})  # fmt: skip


def test_db2_statements_are_rewritten_for_postgresql_and_declare_table_is_dropped() -> None:
    assert rewrite_sql("DECLARE SEG.USUARIOS TABLE (COD_USUARIO CHAR(8))") is None
    found = rewrite_sql(
        "SELECT NOMBRE, VALUE(ALTA, CURRENT DATE) INTO :W-NOMBRE, :W-ALTA FROM SEG.USUARIOS WHERE COD_USUARIO = :W-COD "
        "FETCH FIRST 1 ROWS ONLY WITH UR",
        ["SEG.USUARIOS"],
    )
    assert found == ("SELECT NOMBRE, COALESCE(ALTA, CURRENT_DATE) INTO :W-NOMBRE, :W-ALTA FROM USUARIOS WHERE "
                     "COD_USUARIO = :W-COD LIMIT 1 ")  # fmt: skip
    assert rewrite_sql("UPDATE OTRO.TABLA SET X = CURRENT TIMESTAMP", ["SEG.USUARIOS"]) == (
        "UPDATE OTRO.TABLA SET X = CURRENT_TIMESTAMP"
    )
    assert rewrite_sql("INCLUDE SQLCA") == "INCLUDE SQLCA"


def test_column_types_become_postgresql_types() -> None:
    assert pg_type("CHAR(8)") == "CHAR(8)"
    assert pg_type("DECIMAL(11,2)") == "NUMERIC(11,2)"
    assert pg_type("TIMESTAMP") == "TIMESTAMP"
    assert pg_type("INTEGER") == "INTEGER"
    assert pg_type("PIC S9(11)V99 COMP-3") == "NUMERIC(13,2)"
    assert pg_type("PIC X(10)") == "VARCHAR(10)"


def test_the_schema_the_rows_and_the_dump_of_a_case_are_sql_and_the_dump_reads_back() -> None:
    ddl = schema_sql(SCHEMA, files=["CUENTAS"])  # CUENTAS is reached as a file: not a table here
    assert "CREATE TABLE usuarios (" in ddl
    assert "    cod_usuario CHAR(8) NOT NULL" in ddl
    assert "    PRIMARY KEY (cod_usuario)" in ddl
    assert "cuentas" not in ddl
    rows = case_sql(SCHEMA, {"SEG.USUARIOS": [{"COD_USUARIO": "ADMIN", "SALDO": "10.50", "INTENTOS": 0, "ALTA": None}]},
                    files=["CUENTAS"])  # fmt: skip
    assert "TRUNCATE TABLE usuarios;" in rows
    assert "INSERT INTO usuarios (cod_usuario, saldo, intentos, alta) VALUES ('ADMIN', 10.50, 0, NULL);" in rows
    dump = dump_sql(SCHEMA, files=["CUENTAS"])
    assert dump.startswith("SELECT 'NXT|SEG.USUARIOS|' || COALESCE(CAST(cod_usuario AS TEXT), '~')")
    assert "ORDER BY cod_usuario;" in dump
    tables = parse_dump("NXT|SEG.USUARIOS|ADMIN   |Ana|10.5|~|3\nignored\n", SCHEMA)
    assert tables["SEG.USUARIOS"] == [
        {"COD_USUARIO": "ADMIN", "NOMBRE": "Ana", "SALDO": "10.50", "ALTA": None, "INTENTOS": "3"}
    ]
    assert tables["CUENTAS"] == []


SQL_FIXTURE = Path(__file__).parent / "fixtures" / "pagos_sql"
SQL_FILES = [SourceFile("cbl/PAGOSQL.cbl", (SQL_FIXTURE / "PAGOSQL.cbl").read_text(encoding="utf-8"))]
ACCOUNTS = Schema.model_validate({"tables": [{"name": "SEG.CUENTAS", "key": ["NUMERO"], "columns": [
    {"name": "NUMERO", "type": "CHAR(10)", "nullable": False},
    {"name": "SALDO", "type": "DECIMAL(11,2)", "nullable": False},
    {"name": "ESTADO", "type": "CHAR(1)", "nullable": False},
]}]})  # fmt: skip


def test_a_program_with_exec_sql_is_translated_to_connect_commit_and_postgresql_statements() -> None:
    programs, problems = CobolAdapter()._programs(SQL_FILES)
    assert problems == []
    found = translate(programs[0], SQL_FILES[0].text, ACCOUNTS, {"PAGOSQL"}, main=True)
    assert found.sql is True
    assert found.unsupported == []
    out = found.text
    assert "EXEC SQL CONNECT :NX-DB-USER IDENTIFIED BY :NX-DB-PASS" in out
    assert "DECLARE SEG.CUENTAS TABLE" not in out  # documents the table: dropped
    flat = " ".join(out.split())
    assert "FROM CUENTAS WHERE NUMERO = :W-CUENTA END-EXEC" in flat  # unqualified, WITH UR gone
    assert "WITH UR" not in flat
    assert all(len(line) <= 72 for line in out.split("\n")), [line for line in out.split("\n") if len(line) > 72]
    assert "EXEC SQL COMMIT WORK END-EXEC" in out  # the syncpoint and the end of the task confirm the work
    assert "EXEC SQL ROLLBACK WORK END-EXEC" in out
    assert "CALL 'NXCICS' USING 'ABEND   ' 'NXSQ' NX-NAME NX-LEN" in out


@pytest.mark.skipif(not os.environ.get("NEXTI_LIVE_GNUCOBOL"), reason="GnuCOBOL sandbox run: set NEXTI_LIVE_GNUCOBOL=1")
def test_the_local_engine_runs_exec_sql_against_the_postgresql_of_the_sandbox() -> None:
    from nexti_sandbox import DockerSandbox

    rows = [{"NUMERO": "1234567890", "SALDO": "500.00", "ESTADO": "A"},
            {"NUMERO": "2222222222", "SALDO": "10.00", "ESTADO": "A"}]  # fmt: skip
    suite = Suite(program="PAGOSQL", schema_=ACCOUNTS, cases=[
        Case(name="debito_exitoso", rules=["RULE-001"], inputs={"COMMAREA": "1234567890" + "00000015000" + "  "},
             setup={"SEG.CUENTAS": rows}),
        Case(name="saldo_insuficiente", rules=["RULE-001"], inputs={"COMMAREA": "2222222222" + "00000015000" + "  "},
             setup={"SEG.CUENTAS": rows}),
        Case(name="cuenta_no_existe", rules=["RULE-001"], inputs={"COMMAREA": "9999999999" + "00000015000" + "  "},
             setup={"SEG.CUENTAS": rows}),
    ])  # fmt: skip
    master = asyncio.run(GnuCobolRunner(lambda image: DockerSandbox(image)).run(SQL_FILES, suite))
    seen = {r.case.name: r.observation for r in master.results}
    assert all(o.error is None for o in seen.values()), {n: o.error for n, o in seen.items()}
    assert seen["debito_exitoso"].tables["SEG.CUENTAS"][0] == {"NUMERO": "1234567890", "SALDO": "350.00", "ESTADO": "A"}
    assert seen["saldo_insuficiente"].tables["SEG.CUENTAS"][1]["SALDO"] == "10.00"
    assert seen["cuenta_no_existe"].tables["SEG.CUENTAS"] == [
        {"NUMERO": "1234567890", "SALDO": "500.00", "ESTADO": "A"},
        {"NUMERO": "2222222222", "SALDO": "10.00", "ESTADO": "A"},
    ]
