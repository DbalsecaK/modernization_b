# ruff: noqa: S608 - the SQL is built from the design and runs only in the Oracle database inside the sandbox
"""Oracle as the persistence of the Spring Boot pack (spec 8.4, ADR-0021): the neutral types in Oracle 23ai, the schema,
and the golden master run by the same Java harness against Oracle Database Free inside the sandbox
(`nexti-sandbox-java-oracle`). The sandbox gives that image its two exceptions: a network of its own with no route
out, and its writable layer with the unprivileged `oracle` user."""

import json
import re
from typing import Any

from nexti_core.spec import neutral_types as nt
from nexti_core.spec.characterization import GoldenMaster, Observation, Scalar
from nexti_core.spec.equivalence import (
    CaseRun,
    EquivalenceRun,
    actual_view,
    column_of,
    expected_view,
    masks,
)
from nexti_core.spec.equivalence import target_case as neutral_target_case
from nexti_pack_spring_boot.build import LIMITS, compile_and_test
from nexti_pack_spring_boot.design import Design, UseCase
from nexti_pack_spring_boot.equivalence import harness_source, plan
from nexti_pack_spring_boot.generate import _snake
from nexti_sandbox import Limits, Sandbox

IMAGE = "nexti-sandbox-java-oracle:1"
SCHEMA = "src/main/resources/db/schema.sql"
# Oracle needs more memory and time to start; the exceptions of ADR-0021 apply only to this engine.
ORACLE_LIMITS = Limits(cpus=2.0, memory_mb=3584, pids=1024, timeout_seconds=1200, work_mb=512,
                       max_output_bytes=4 * 1024 * 1024, internal_network=True, writable_root=True,
                       user="54321:54321")  # fmt: skip
USER, PASSWORD, SERVICE = "nexti", "Nexti_Sandbox_1", "FREEPDB1"  # a throwaway database without network: not secrets
JDBC_URL = f"jdbc:oracle:thin:@localhost:1521/{SERVICE}"
SESSION = [
    "ALTER SESSION SET NLS_DATE_FORMAT = 'YYYY-MM-DD'",
    "ALTER SESSION SET NLS_TIMESTAMP_FORMAT = 'YYYY-MM-DD\"T\"HH24:MI:SS.FF'",
    "ALTER SESSION SET NLS_TIMESTAMP_TZ_FORMAT = 'YYYY-MM-DD\"T\"HH24:MI:SS.FFTZH:TZM'",
    "ALTER SESSION SET NLS_NUMERIC_CHARACTERS = '.,'",
]


# Oracle's reserved words (V$RESERVED_WORDS, RESERVED = 'Y'): a column named like one is quoted, in upper case.
RESERVED = frozenset(
    ["ACCESS", "ADD", "ALL", "ALTER", "AND", "ANY", "AS", "ASC", "AUDIT", "BETWEEN", "BY", "CHAR", "CHECK", "CLUSTER", "COLUMN", "COMMENT", "COMPRESS", "CONNECT", "CREATE", "CURRENT", "DATE", "DECIMAL", "DEFAULT", "DELETE", "DESC", "DISTINCT", "DROP", "ELSE", "EXCLUSIVE", "EXISTS", "FILE", "FLOAT", "FOR", "FROM", "GRANT", "GROUP", "HAVING", "IDENTIFIED", "IMMEDIATE", "IN", "INCREMENT", "INDEX", "INITIAL", "INSERT", "INTEGER", "INTERSECT", "INTO", "IS", "LEVEL", "LIKE", "LOCK", "LONG", "MAXEXTENTS", "MINUS", "MLSLABEL", "MODE", "MODIFY", "NOAUDIT", "NOCOMPRESS", "NOT", "NOWAIT", "NULL", "NUMBER", "OF", "OFFLINE", "ON", "ONLINE", "OPTION", "OR", "ORDER", "PCTFREE", "PRIOR", "PUBLIC", "RAW", "RENAME", "RESOURCE", "REVOKE", "ROW", "ROWID", "ROWNUM", "ROWS", "SELECT", "SESSION", "SET", "SHARE", "SIZE", "SMALLINT", "START", "SUCCESSFUL", "SYNONYM", "SYSDATE", "TABLE", "THEN", "TO", "TRIGGER", "UID", "UNION", "UNIQUE", "UPDATE", "USER", "VALIDATE", "VALUES", "VARCHAR", "VARCHAR2", "VIEW", "WHENEVER", "WHERE", "WITH"]
)


def quoted(identifier: str) -> str:
    """An identifier as Oracle SQL must write it: a reserved word in quotes and upper case, the rest as it is."""
    return f'"{identifier.upper()}"' if identifier.upper() in RESERVED else identifier


def oracle_type(neutral: str) -> str:
    value = nt.parse(neutral)
    if isinstance(value, nt.Decimal):
        return f"NUMBER({value.precision},{value.scale})"
    if isinstance(value, nt.Integer):
        return {8: "NUMBER(3)", 16: "NUMBER(5)", 32: "NUMBER(10)", 64: "NUMBER(19)"}[value.bits]
    if isinstance(value, nt.Text):
        if value.length is None:
            return "VARCHAR2(4000)"
        return f"{'CHAR' if value.kind == 'fixed' else 'VARCHAR2'}({value.length})"
    if isinstance(value, nt.Enum):
        return f"VARCHAR2({max(len(v) for v in value.values)})"
    if isinstance(value, nt.Date):
        return "DATE"
    if isinstance(value, nt.Timestamp):
        return "TIMESTAMP WITH TIME ZONE" if value.tz else "TIMESTAMP"
    if isinstance(value, nt.Boolean):
        return "BOOLEAN"
    return "BLOB"


def schema(design: Design) -> str:
    """The Oracle DDL of the entities (unquoted names, folded to upper case by Oracle as usual)."""
    statements = []
    for entity in design.entities:
        if not entity.table:
            continue
        columns = [f"    {quoted(f.column or _snake(f.name))} {oracle_type(f.type)}" for f in entity.fields]
        if entity.key:
            by_name = {f.name: f for f in entity.fields}
            keys = ", ".join(quoted(by_name[k].column or _snake(k)) for k in entity.key)
            columns.append(f"    PRIMARY KEY ({keys})")
        origin = f" -- legacy {entity.legacy_table}" if entity.legacy_table else ""
        statements.append(f"CREATE TABLE {entity.table} ({origin}\n" + ",\n".join(columns) + "\n);")
    return "\n\n".join(statements) + "\n"


def _read(name: str, column: str, neutral: str) -> str:
    """A column as the harness reads it: dates and timestamps as ISO text, every name in lower case (quoted alias)."""
    value = nt.parse(neutral)
    expression = quoted(column)
    if isinstance(value, nt.Date):
        expression = f"TO_CHAR({quoted(column)}, 'YYYY-MM-DD')"
    elif isinstance(value, nt.Timestamp):
        expression = f"TO_CHAR({quoted(column)}, 'YYYY-MM-DD\"T\"HH24:MI:SS.FF6')"
    return f'{expression} AS "{column.lower()}"'


def oracle_plan(design: Design, use_case: UseCase) -> dict[str, Any]:
    """The plan of the Java harness with Oracle's connection, session and statements."""
    found = plan(design, use_case)
    tables = [e for e in design.entities if e.table]
    dump = {}
    for entity in tables:
        columns = ", ".join(_read(f.name, column_of(f.name, f.column), f.type) for f in entity.fields)
        order = ", ".join(quoted(column_of(k, next(f.column for f in entity.fields if f.name == k)))
                          for k in entity.key)  # fmt: skip
        dump[entity.table] = f"SELECT {columns} FROM {entity.table}" + (f" ORDER BY {order}" if order else "")
    return {**found, "jdbc_url": JDBC_URL, "user": USER, "password": PASSWORD, "session": SESSION,
            "reset": [f"TRUNCATE TABLE {e.table}" for e in tables], "dump": dump}  # fmt: skip


def target_case(design: Design, use_case: UseCase, case: Any, defaults: dict[str, Scalar] | None = None
                ) -> dict[str, Any]:  # fmt: skip
    """A legacy case in target terms, with Oracle types for the rows to insert and reserved columns quoted."""
    found = neutral_target_case(design, use_case, case, defaults, oracle_type)

    def columns(match: re.Match[str]) -> str:
        names = ", ".join(quoted(c.strip()) for c in match.group(2).split(","))
        return f"INSERT INTO {match.group(1)} ({names}) VALUES"

    found["setup"] = [re.sub(r"^INSERT INTO (\w+) \(([^)]*)\) VALUES", columns, sql) for sql in found["setup"]]
    return found


SCRIPT = r"""
mkdir -p /work/harness-out
if ! javac -nowarn -encoding UTF-8 -d /work/harness-out -cp "/work/out:/opt/lib/*" \
    /input/harness/EquivalenceHarness.java 2> /work/javac.txt; then
  echo "===HARNESS-FAILED==="; cat /work/javac.txt; exit 4
fi
/opt/oracle/container-entrypoint.sh > /work/oracle.log 2>&1 &
for i in $(seq 1 300); do
  grep -q "DATABASE IS READY" /work/oracle.log && break
  grep -q "ORA-00600" /work/oracle.log && break
  sleep 1
done
if ! grep -q "DATABASE IS READY" /work/oracle.log; then
  echo "===HARNESS-FAILED==="; echo "Oracle did not start"; tail -40 /work/oracle.log; exit 5
fi
( echo "WHENEVER SQLERROR EXIT FAILURE"; cat /work/p/src/main/resources/db/schema.sql; echo "EXIT" ) \
  > /work/schema-run.sql
if ! sqlplus -s nexti/Nexti_Sandbox_1@localhost/FREEPDB1 @/work/schema-run.sql > /work/schema.log 2>&1; then
  echo "===HARNESS-FAILED==="; cat /work/schema.log; exit 6
fi
echo "===EQUIVALENCE==="
java -cp "/work/out:/work/harness-out:/opt/lib/*" nexti.equivalence.EquivalenceHarness \
  /input/harness/plan.json /input/harness/cases.json 2>&1 || true
echo "===EQUIVALENCE-END==="
"""


async def run_equivalence(
    sandbox: Sandbox, files: dict[str, str], design: Design, use_case: UseCase, master: GoldenMaster,
    defaults: dict[str, Scalar] | None = None,
) -> EquivalenceRun:  # fmt: skip
    """Compiles the project and runs every golden case on it against Oracle."""
    recorded = [r for r in master.results if r.observation.error is None]
    cases = [target_case(design, use_case, r.case, defaults) for r in recorded]
    extra = {
        "harness/EquivalenceHarness.java": harness_source(),
        "harness/plan.json": json.dumps(oracle_plan(design, use_case)),
        "harness/cases.json": json.dumps(cases),
    }
    build = await compile_and_test(sandbox, files, extra_inputs=extra, after=SCRIPT, limits=ORACLE_LIMITS)
    found = masks(design, use_case, master)
    if not build.compiled:
        return EquivalenceRun(build, [], found, f"the project does not compile: {build.compile_errors[:300]}")
    if "===HARNESS-FAILED===" in build.after_output:
        return EquivalenceRun(build, [], found, build.after_output.split("===HARNESS-FAILED===", 1)[1][:3000])
    raw = {}
    for line in build.after_output.split("===EQUIVALENCE===", 1)[-1].splitlines():
        if line.startswith("NXE "):
            item = json.loads(line[4:])
            raw[item["name"]] = item
    runs = []
    for recorded_case in recorded:
        item = raw.get(recorded_case.case.name)
        expected = expected_view(design, use_case, recorded_case.observation, found)
        if item is None or item.get("failure"):
            failure = (item or {}).get("failure") or "the harness printed nothing for this case"
            runs.append(CaseRun(recorded_case.case.name, expected, Observation(), failure))
            continue
        rejected = recorded_case.observation.returns not in (0, None)
        actual = actual_view(design, use_case, item, found, rejected)
        if master.from_traces and actual.returns not in (0, None):
            actual = actual.model_copy(update={"returns": -1})
        runs.append(CaseRun(recorded_case.case.name, expected, actual))
    return EquivalenceRun(build, runs, found)


__all__ = ["IMAGE", "LIMITS", "ORACLE_LIMITS", "oracle_plan", "oracle_type", "run_equivalence", "schema",
           "target_case"]  # fmt: skip
