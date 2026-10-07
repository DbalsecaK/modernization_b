"""The SQL probe of the .NET pack (P32 for SQL Server, step 12 of the plan): the statements of a generated ADO.NET
adapter resolved against the target schema in the sandbox before the adapter is accepted. SQL Server's
sp_describe_undeclared_parameters binds a statement (tables, columns, syntax, the types of its @parameters)
without running it."""

import re
from collections.abc import Mapping

from nexti_pack_dotnet.build import compile_and_test
from nexti_pack_dotnet.generate import SCHEMA
from nexti_sandbox import Sandbox
from nexti_sandbox.sqlprobe import END, MARK, PROBE_PATH, START, by_marker, statements

# C#: a raw literal """...""", a verbatim @"..." ("" is a quote), a regular "..." with escapes; `$` interpolates.
LITERAL = re.compile(r'"""(.*?)"""|(\$)?@"((?:[^"]|"")*)"|(\$)?"((?:[^"\\\n]|\\.)*)"', re.S)


def _text(match: re.Match[str]) -> tuple[str, bool]:
    if match.group(1) is not None:
        return match.group(1), False
    if match.group(3) is not None:
        text = match.group(3).replace('""', '"')
        return text, bool(match.group(2)) and "{" in text
    text = (match.group(5) or "").replace('\\"', '"').replace("\\n", " ").replace("\\t", " ").replace("\\\\", "\\")
    return text, bool(match.group(4)) and "{" in text


def csharp_statements(source: str) -> list[str]:
    return statements(source, LITERAL, _text)


SCRIPT = rf"""
cp -r /opt/mssql-seed/. /var/opt/mssql/
/opt/mssql/bin/sqlservr > /work/sql.log 2>&1 &
for i in $(seq 1 150); do grep -q "now ready for client connections" /work/sql.log && break; sleep 1; done
SQL="sqlcmd -S 127.0.0.1,1433 -U sa -P $MSSQL_SA_PASSWORD -C -l 30"
if ! $SQL -b -Q "CREATE DATABASE nexti" > /work/schema.log 2>&1 \
    || ! $SQL -b -d nexti -i /work/p/{SCHEMA} >> /work/schema.log 2>&1; then
  echo "{START}"; echo "the schema does not load:"; cat /work/schema.log; echo "{END}"; exit 0
fi
echo "{START}"
$SQL -d nexti -i /input/{PROBE_PATH} 2>&1 | awk '/{MARK.rstrip("|")}/{{print; next}} /^Msg /{{getline; print}}' || true
echo "{END}"
$SQL -Q "SHUTDOWN WITH NOWAIT" > /dev/null 2>&1 || true
"""


def probe_file(found: list[str]) -> str:
    """A marker before each statement, so the errors that follow belong to it."""
    out = ["SET NOCOUNT ON", "GO"]
    for i, text in enumerate(found, start=1):
        quoted = text.rstrip(";").replace("'", "''")
        out += [f"PRINT '{MARK}{i}'", "GO", f"EXEC sp_describe_undeclared_parameters @tsql = N'{quoted}'", "GO"]
    return "\n".join([*out, ""])


async def probe_sql(sandbox: Sandbox, files: Mapping[str, str], path: str) -> str:
    """Resolve every SQL statement of the adapter at `path` against the project's schema; the errors, or ""."""
    found = csharp_statements(files.get(path, ""))
    if not found:
        return ""
    build = await compile_and_test(sandbox, files, run_tests=False, extra_inputs={PROBE_PATH: probe_file(found)},
                                   after=SCRIPT)  # fmt: skip
    return by_marker(build.after_output, found) if build.compiled else ""


async def probe_oracle(sandbox: Sandbox, files: Mapping[str, str], path: str) -> str:
    """The .NET pack on Oracle: EXPLAIN PLAN of every statement (its :name parameters are binds already)."""
    from nexti_pack_dotnet.oracle import ORACLE_LIMITS
    from nexti_pack_spring_boot.sqlprobe_engines import oracle_probe_file, oracle_script

    found = csharp_statements(files.get(path, ""))
    if not found:
        return ""
    build = await compile_and_test(sandbox, files, run_tests=False,
                                   extra_inputs={PROBE_PATH: oracle_probe_file(found)},
                                   after=oracle_script(f"/work/p/{SCHEMA}"), limits=ORACLE_LIMITS)  # fmt: skip
    return by_marker(build.after_output, found) if build.compiled else ""
