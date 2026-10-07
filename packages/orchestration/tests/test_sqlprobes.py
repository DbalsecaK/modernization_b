"""The SQL of an adapter, read from the literals of each language, and the probe report (P32, step 12)."""

import re

from nexti_pack_dotnet.sqlprobe import csharp_statements
from nexti_pack_dotnet.sqlprobe import probe_file as sqlserver_probe_file
from nexti_pack_go.sqlprobe import go_statements
from nexti_pack_spring_boot.sqlprobe_engines import binds, java_statements, mysql_probe_file, oracle_probe_file
from nexti_sandbox.sqlprobe import END, START, by_line, by_marker

CSHARP = '''
const string Find = "SELECT o.estado FROM pg_orden o " +
    "WHERE o.id = @id";
const string Raw = """
    UPDATE pg_orden SET estado = @estado WHERE id = @id
    """;
var built = $"SELECT * FROM {table}";
var verbatim = @"DELETE FROM pg_orden WHERE note = ""x""";
var list = "SELECT id FROM t WHERE id IN (" + string.Join(",", ids) + ")";
'''

GO = """
const findOrder = `SELECT estado
FROM pg_orden WHERE id = $1`
var insert = "INSERT INTO pg_orden (id) " +
    "VALUES ($1)"
var dynamic = "SELECT id FROM " + table
"""


def test_each_language_gives_its_statements_and_skips_the_ones_built_at_run_time() -> None:
    assert csharp_statements(CSHARP) == [
        "SELECT o.estado FROM pg_orden o WHERE o.id = @id",
        "UPDATE pg_orden SET estado = @estado WHERE id = @id",
        'DELETE FROM pg_orden WHERE note = "x"',
    ]
    assert go_statements(GO) == ["SELECT estado FROM pg_orden WHERE id = $1", "INSERT INTO pg_orden (id) VALUES ($1)"]
    java = 'String q = "SELECT a FROM t WHERE b = ? " + "AND c = ?";'
    assert java_statements(java) == ["SELECT a FROM t WHERE b = ? AND c = ?"]


def test_the_probe_files_keep_one_statement_per_line_or_marker() -> None:
    assert binds("SELECT a FROM t WHERE b = ? AND c = ?") == "SELECT a FROM t WHERE b = :1 AND c = :2"
    mysql = mysql_probe_file(["SELECT 'x' FROM t WHERE a = ?"])
    assert mysql == "PREPARE nx_probe_1 FROM 'SELECT ''x'' FROM t WHERE a = ?';\n"
    oracle = oracle_probe_file(["SELECT a FROM t WHERE b = ?"])
    assert "PROMPT NXSQL|1\nEXPLAIN PLAN FOR SELECT a FROM t WHERE b = :1;" in oracle
    assert "EXEC sp_describe_undeclared_parameters @tsql = N'SELECT 1'" in sqlserver_probe_file(["SELECT 1"])


def test_the_errors_go_back_with_their_statement() -> None:
    found = ["SELECT 1 FROM dual", "SELECT x FROM nope"]
    marked = f"noise\n{START}\nNXSQL|1\nNXSQL|2\nORA-00942: table or view does not exist\n{END}"
    assert by_marker(marked, found) == "ORA-00942: table or view does not exist\n  statement: SELECT x FROM nope"
    assert by_marker(f"{START}\nNXSQL|1\nNXSQL|2\n{END}", found) == ""
    line = f"{START}\nERROR 1146 (42S02) at line 2: Table 'nexti.nope' doesn't exist\n{END}"
    pattern = re.compile(r"ERROR \d+ \([0-9A-Z]+\) at line (\d+): (.*)")
    assert by_line(line, found, pattern) == "Table 'nexti.nope' doesn't exist\n  statement: SELECT x FROM nope"
