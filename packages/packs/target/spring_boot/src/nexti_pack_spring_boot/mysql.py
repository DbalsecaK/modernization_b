# ruff: noqa: S608 - the SQL is built from the design and runs only in the MySQL database inside the sandbox
"""MySQL as the persistence of the Spring Boot pack (spec 8.4, ADR-0027): the neutral types in MySQL 8.4, the schema,
and the golden master run by the same Java harness against MySQL Community Server inside the sandbox
(`nexti-sandbox-java-mysql`). Unlike Oracle it needs none of the exceptions of ADR-0021: each run initializes a
throwaway database in the /work tmpfs and starts MySQL on loopback only, like PostgreSQL in the base image."""

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
from nexti_pack_spring_boot.build import compile_and_test
from nexti_pack_spring_boot.design import Design, UseCase
from nexti_pack_spring_boot.equivalence import harness_source, plan
from nexti_pack_spring_boot.generate import _snake
from nexti_sandbox import Limits, Sandbox

IMAGE = "nexti-sandbox-java-mysql:1"
SCHEMA = "src/main/resources/db/schema.sql"
# The default hardening of the sandbox (no network, read-only root, user nobody): MySQL listens on loopback and keeps
# its data in /work. More memory and /work than the base image: the JVM and mysqld run side by side.
MYSQL_LIMITS = Limits(cpus=2.0, memory_mb=2048, pids=512, timeout_seconds=900, work_mb=768,
                      max_output_bytes=2 * 1024 * 1024)  # fmt: skip
USER, PASSWORD, DATABASE = "nexti", "Nexti_Sandbox_1", "nexti"  # a throwaway database without network: not secrets
JDBC_URL = (f"jdbc:mysql://127.0.0.1:3306/{DATABASE}?sslMode=DISABLED&allowPublicKeyRetrieval=true"
            "&connectionTimeZone=UTC")  # fmt: skip
# Strict: a value that does not fit its column is an error, never a silent truncation; a backslash is a character like
# any other (the case literals only double their quotes); every timestamp in UTC.
SQL_MODE = ("STRICT_ALL_TABLES,ONLY_FULL_GROUP_BY,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,"
            "NO_ENGINE_SUBSTITUTION,NO_BACKSLASH_ESCAPES")  # fmt: skip
SESSION = [f"SET SESSION sql_mode = '{SQL_MODE}'", "SET SESSION time_zone = '+00:00'"]


# MySQL 8.4's reserved words (INFORMATION_SCHEMA.KEYWORDS, RESERVED = 1): an identifier named like one is quoted with
# backticks.
RESERVED = frozenset(
    [
        "ACCESSIBLE",
        "ADD",
        "ALL",
        "ALTER",
        "ANALYZE",
        "AND",
        "AS",
        "ASC",
        "ASENSITIVE",
        "BEFORE",
        "BETWEEN",
        "BIGINT",
        "BINARY",
        "BLOB",
        "BOTH",
        "BY",
        "CALL",
        "CASCADE",
        "CASE",
        "CHANGE",
        "CHAR",
        "CHARACTER",
        "CHECK",
        "COLLATE",
        "COLUMN",
        "CONDITION",
        "CONSTRAINT",
        "CONTINUE",
        "CONVERT",
        "CREATE",
        "CROSS",
        "CUBE",
        "CUME_DIST",
        "CURRENT_DATE",
        "CURRENT_TIME",
        "CURRENT_TIMESTAMP",
        "CURRENT_USER",
        "CURSOR",
        "DATABASE",
        "DATABASES",
        "DAY_HOUR",
        "DAY_MICROSECOND",
        "DAY_MINUTE",
        "DAY_SECOND",
        "DEC",
        "DECIMAL",
        "DECLARE",
        "DEFAULT",
        "DELAYED",
        "DELETE",
        "DENSE_RANK",
        "DESC",
        "DESCRIBE",
        "DETERMINISTIC",
        "DISTINCT",
        "DISTINCTROW",
        "DIV",
        "DOUBLE",
        "DROP",
        "DUAL",
        "EACH",
        "ELSE",
        "ELSEIF",
        "EMPTY",
        "ENCLOSED",
        "ESCAPED",
        "EXCEPT",
        "EXISTS",
        "EXIT",
        "EXPLAIN",
        "FALSE",
        "FETCH",
        "FIRST_VALUE",
        "FLOAT",
        "FLOAT4",
        "FLOAT8",
        "FOR",
        "FORCE",
        "FOREIGN",
        "FROM",
        "FULLTEXT",
        "FUNCTION",
        "GENERATED",
        "GET",
        "GRANT",
        "GROUP",
        "GROUPING",
        "GROUPS",
        "HAVING",
        "HIGH_PRIORITY",
        "HOUR_MICROSECOND",
        "HOUR_MINUTE",
        "HOUR_SECOND",
        "IF",
        "IGNORE",
        "IN",
        "INDEX",
        "INFILE",
        "INNER",
        "INOUT",
        "INSENSITIVE",
        "INSERT",
        "INT",
        "INT1",
        "INT2",
        "INT3",
        "INT4",
        "INT8",
        "INTEGER",
        "INTERSECT",
        "INTERVAL",
        "INTO",
        "IO_AFTER_GTIDS",
        "IO_BEFORE_GTIDS",
        "IS",
        "ITERATE",
        "JOIN",
        "JSON_TABLE",
        "KEY",
        "KEYS",
        "KILL",
        "LAG",
        "LAST_VALUE",
        "LATERAL",
        "LEAD",
        "LEADING",
        "LEAVE",
        "LEFT",
        "LIKE",
        "LIMIT",
        "LINEAR",
        "LINES",
        "LOAD",
        "LOCALTIME",
        "LOCALTIMESTAMP",
        "LOCK",
        "LONG",
        "LONGBLOB",
        "LONGTEXT",
        "LOOP",
        "LOW_PRIORITY",
        "MATCH",
        "MAXVALUE",
        "MEDIUMBLOB",
        "MEDIUMINT",
        "MEDIUMTEXT",
        "MIDDLEINT",
        "MINUTE_MICROSECOND",
        "MINUTE_SECOND",
        "MOD",
        "MODIFIES",
        "NATURAL",
        "NO_WRITE_TO_BINLOG",
        "NOT",
        "NTH_VALUE",
        "NTILE",
        "NULL",
        "NUMERIC",
        "OF",
        "ON",
        "OPTIMIZE",
        "OPTIMIZER_COSTS",
        "OPTION",
        "OPTIONALLY",
        "OR",
        "ORDER",
        "OUT",
        "OUTER",
        "OUTFILE",
        "OVER",
        "PARTITION",
        "PERCENT_RANK",
        "PRECISION",
        "PRIMARY",
        "PROCEDURE",
        "PURGE",
        "QUALIFY",
        "RANGE",
        "RANK",
        "READ",
        "READ_WRITE",
        "READS",
        "REAL",
        "RECURSIVE",
        "REFERENCES",
        "REGEXP",
        "RELEASE",
        "RENAME",
        "REPEAT",
        "REPLACE",
        "REQUIRE",
        "RESIGNAL",
        "RESTRICT",
        "RETURN",
        "REVOKE",
        "RIGHT",
        "RLIKE",
        "ROW",
        "ROW_NUMBER",
        "ROWS",
        "SCHEMA",
        "SCHEMAS",
        "SECOND_MICROSECOND",
        "SELECT",
        "SENSITIVE",
        "SEPARATOR",
        "SET",
        "SHOW",
        "SIGNAL",
        "SMALLINT",
        "SPATIAL",
        "SPECIFIC",
        "SQL",
        "SQL_BIG_RESULT",
        "SQL_CALC_FOUND_ROWS",
        "SQL_SMALL_RESULT",
        "SQLEXCEPTION",
        "SQLSTATE",
        "SQLWARNING",
        "SSL",
        "STARTING",
        "STORED",
        "STRAIGHT_JOIN",
        "SYSTEM",
        "TABLE",
        "TABLESAMPLE",
        "TERMINATED",
        "THEN",
        "TINYBLOB",
        "TINYINT",
        "TINYTEXT",
        "TO",
        "TRAILING",
        "TRIGGER",
        "TRUE",
        "UNDO",
        "UNION",
        "UNIQUE",
        "UNLOCK",
        "UNSIGNED",
        "UPDATE",
        "USAGE",
        "USE",
        "USING",
        "UTC_DATE",
        "UTC_TIME",
        "UTC_TIMESTAMP",
        "VALUES",
        "VARBINARY",
        "VARCHAR",
        "VARCHARACTER",
        "VARYING",
        "VIRTUAL",
        "WHEN",
        "WHERE",
        "WHILE",
        "WINDOW",
        "WITH",
        "WRITE",
        "XOR",
        "YEAR_MONTH",
        "ZEROFILL",
    ]
)


def quoted(identifier: str) -> str:
    """An identifier as MySQL SQL must write it: a reserved word between backticks, the rest as it is."""
    return f"`{identifier}`" if identifier.upper() in RESERVED else identifier


def mysql_type(neutral: str) -> str:
    value = nt.parse(neutral)
    if isinstance(value, nt.Decimal):
        return f"DECIMAL({value.precision},{value.scale})"
    if isinstance(value, nt.Integer):
        name = {8: "TINYINT", 16: "SMALLINT", 32: "INT", 64: "BIGINT"}[value.bits]
        return name if value.signed else f"{name} UNSIGNED"
    if isinstance(value, nt.Text):
        if value.length is None:
            return "TEXT"  # no row-size limit, unlike several VARCHAR(4000) in utf8mb4
        return f"{'CHAR' if value.kind == 'fixed' else 'VARCHAR'}({value.length})"
    if isinstance(value, nt.Enum):
        return f"VARCHAR({max(len(v) for v in value.values)})"
    if isinstance(value, nt.Date):
        return "DATE"
    if isinstance(value, nt.Timestamp):
        return "DATETIME(3)"  # MySQL keeps no offset: a timestamp with time zone is stored in UTC (session +00:00)
    if isinstance(value, nt.Boolean):
        return "BOOLEAN"  # TINYINT(1), read back by Connector/J as a Boolean
    return "BLOB"


def cast_type(neutral: str) -> str:
    """The type of a CAST in MySQL, which accepts fewer types than its DDL (no VARCHAR, INT nor BOOLEAN)."""
    value = nt.parse(neutral)
    if isinstance(value, nt.Integer):
        return "SIGNED" if value.signed else "UNSIGNED"
    if isinstance(value, nt.Text | nt.Enum):
        return "CHAR"
    if isinstance(value, nt.Boolean):
        return "BOOLEAN"  # not a CAST type: target_case writes the literal TRUE or FALSE instead
    if isinstance(value, nt.Decimal | nt.Date | nt.Timestamp):
        return mysql_type(neutral)
    return "BINARY"


def schema(design: Design) -> str:
    """The MySQL DDL of the entities (reserved names between backticks)."""
    statements = []
    for entity in design.entities:
        if not entity.table:
            continue
        columns = [f"    {quoted(f.column or _snake(f.name))} {mysql_type(f.type)}" for f in entity.fields]
        if entity.key:
            by_name = {f.name: f for f in entity.fields}
            keys = ", ".join(quoted(by_name[k].column or _snake(k)) for k in entity.key)
            columns.append(f"    PRIMARY KEY ({keys})")
        origin = f" -- legacy {entity.legacy_table}" if entity.legacy_table else ""
        statements.append(f"CREATE TABLE {quoted(entity.table)} ({origin}\n" + ",\n".join(columns) + "\n);")
    return "\n\n".join(statements) + "\n"


def _read(column: str, neutral: str) -> str:
    """A column as the harness reads it: dates and timestamps as ISO text, under the column's own name."""
    value = nt.parse(neutral)
    expression = quoted(column)
    if isinstance(value, nt.Date):
        expression = f"DATE_FORMAT({quoted(column)}, '%Y-%m-%d')"
    elif isinstance(value, nt.Timestamp):
        expression = f"DATE_FORMAT({quoted(column)}, '%Y-%m-%dT%H:%i:%s.%f')"
    return f"{expression} AS `{column}`"


def mysql_plan(design: Design, use_case: UseCase) -> dict[str, Any]:
    """The plan of the Java harness with MySQL's connection, session and statements."""
    found = plan(design, use_case)
    tables = [e for e in design.entities if e.table]
    dump = {}
    for entity in tables:
        columns = ", ".join(_read(column_of(f.name, f.column), f.type) for f in entity.fields)
        order = ", ".join(quoted(column_of(k, next(f.column for f in entity.fields if f.name == k)))
                          for k in entity.key)  # fmt: skip
        dump[entity.table] = f"SELECT {columns} FROM {quoted(entity.table or '')}" + (
            f" ORDER BY {order}" if order else ""
        )
    return {**found, "jdbc_url": JDBC_URL, "user": USER, "password": PASSWORD, "session": SESSION,
            "reset": [f"TRUNCATE TABLE {quoted(e.table)}" for e in tables if e.table], "dump": dump}  # fmt: skip


def target_case(design: Design, use_case: UseCase, case: Any, defaults: dict[str, Scalar] | None = None
                ) -> dict[str, Any]:  # fmt: skip
    """A legacy case in target terms, with MySQL casts for the rows to insert and reserved names quoted."""
    found = neutral_target_case(design, use_case, case, defaults, cast_type)

    def columns(match: re.Match[str]) -> str:
        names = ", ".join(quoted(c.strip()) for c in match.group(2).split(","))
        return f"INSERT INTO {quoted(match.group(1))} ({names}) VALUES"

    def boolean(match: re.Match[str]) -> str:
        return match.group(1).upper()

    found["setup"] = [re.sub(r"CAST\('(true|false)' AS BOOLEAN\)", boolean,
                             re.sub(r"^INSERT INTO (\w+) \(([^)]*)\) VALUES", columns, sql))
                      for sql in found["setup"]]  # fmt: skip
    return found


SCRIPT = r"""
mkdir -p /work/harness-out /work/mysql-tmp
if ! javac -nowarn -encoding UTF-8 -d /work/harness-out -cp "/work/out:/opt/lib/*" \
    /input/harness/EquivalenceHarness.java 2> /work/javac.txt; then
  echo "===HARNESS-FAILED==="; cat /work/javac.txt; exit 4
fi
MYSQL_OPTS="--no-defaults --datadir=/work/mysql --tmpdir=/work/mysql-tmp --socket=/work/mysql.sock \
  --pid-file=/work/mysql.pid --log-error=/work/mysqld.log --secure-file-priv=NULL --mysqlx=OFF --skip-log-bin \
  --performance-schema=OFF --innodb-buffer-pool-size=32M --innodb-redo-log-capacity=8M --innodb-use-native-aio=OFF \
  --innodb-flush-method=fsync --innodb-doublewrite=OFF --innodb-flush-log-at-trx-commit=0 \
  --character-set-server=utf8mb4 --default-time-zone=+00:00 --sql-mode=__SQL_MODE__"
if ! mysqld $MYSQL_OPTS --initialize-insecure > /work/mysql-init.log 2>&1; then
  echo "===HARNESS-FAILED==="; echo "MySQL could not initialize"; cat /work/mysql-init.log; tail -40 /work/mysqld.log
  exit 5
fi
mysqld $MYSQL_OPTS --bind-address=127.0.0.1 --port=3306 --skip-name-resolve > /dev/null 2>&1 &
for i in $(seq 1 120); do
  mysqladmin --socket=/work/mysql.sock -uroot ping > /dev/null 2>&1 && break
  sleep 1
done
if ! mysqladmin --socket=/work/mysql.sock -uroot ping > /dev/null 2>&1; then
  echo "===HARNESS-FAILED==="; echo "MySQL did not start"; tail -40 /work/mysqld.log; exit 5
fi
mysql --socket=/work/mysql.sock -uroot -e "CREATE DATABASE nexti; \
  CREATE USER 'nexti'@'127.0.0.1' IDENTIFIED BY 'Nexti_Sandbox_1'; GRANT ALL ON nexti.* TO 'nexti'@'127.0.0.1';"
if ! mysql --socket=/work/mysql.sock -uroot nexti < /work/p/src/main/resources/db/schema.sql > /work/schema.log 2>&1
then
  echo "===HARNESS-FAILED==="; cat /work/schema.log; exit 6
fi
echo "===EQUIVALENCE==="
java -cp "/work/out:/work/harness-out:/opt/lib/*" nexti.equivalence.EquivalenceHarness \
  /input/harness/plan.json /input/harness/cases.json 2>&1 || true
echo "===EQUIVALENCE-END==="
mysqladmin --socket=/work/mysql.sock -uroot shutdown > /dev/null 2>&1 || true
""".replace("__SQL_MODE__", SQL_MODE)


async def run_equivalence(
    sandbox: Sandbox, files: dict[str, str], design: Design, use_case: UseCase, master: GoldenMaster,
    defaults: dict[str, Scalar] | None = None,
) -> EquivalenceRun:  # fmt: skip
    """Compiles the project and runs every golden case on it against MySQL."""
    recorded = [r for r in master.results if r.observation.error is None]
    cases = [target_case(design, use_case, r.case, defaults) for r in recorded]
    extra = {
        "harness/EquivalenceHarness.java": harness_source(),
        "harness/plan.json": json.dumps(mysql_plan(design, use_case)),
        "harness/cases.json": json.dumps(cases),
    }
    build = await compile_and_test(sandbox, files, extra_inputs=extra, after=SCRIPT, limits=MYSQL_LIMITS)
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


__all__ = ["IMAGE", "MYSQL_LIMITS", "cast_type", "mysql_plan", "mysql_type", "quoted", "run_equivalence", "schema",
           "target_case"]  # fmt: skip
