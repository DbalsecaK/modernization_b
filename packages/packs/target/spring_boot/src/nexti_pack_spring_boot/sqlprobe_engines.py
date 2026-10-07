"""The SQL probe of the Spring Boot variants (P32 for MySQL and Oracle, step 12 of the plan): the statements of a
generated JDBC adapter prepared against the variant's schema in its sandbox, before the adapter is accepted.

MySQL prepares each statement with PREPARE (tables, columns and syntax, nothing runs); Oracle explains each one with
EXPLAIN PLAN, which parses and resolves it without running it. The engine starts as in the equivalence script."""

import re
from collections.abc import Mapping

from nexti_pack_spring_boot.build import compile_and_test
from nexti_pack_spring_boot.mysql import MYSQL_LIMITS, SQL_MODE
from nexti_pack_spring_boot.oracle import ORACLE_LIMITS, PASSWORD, SERVICE, USER
from nexti_pack_spring_boot.sqlprobe import LITERAL, _unescape
from nexti_sandbox import Sandbox
from nexti_sandbox.sqlprobe import END, MARK, PROBE_PATH, START, by_line, by_marker, statements

SCHEMA = "/work/p/src/main/resources/db/schema.sql"


def java_statements(java: str) -> list[str]:
    """The statements of a Java adapter with their `?` placeholders as written."""
    return statements(java, LITERAL, lambda m: (m.group(1) if m.group(1) is not None else _unescape(m.group(2) or ""),
                                                False))  # fmt: skip


MYSQL_SCRIPT = (
    r"""
mkdir -p /work/mysql-tmp
MYSQL_OPTS="--no-defaults --datadir=/work/mysql --tmpdir=/work/mysql-tmp --socket=/work/mysql.sock \
  --pid-file=/work/mysql.pid --log-error=/work/mysqld.log --secure-file-priv=NULL --mysqlx=OFF --skip-log-bin \
  --performance-schema=OFF --innodb-buffer-pool-size=32M --innodb-redo-log-capacity=8M --innodb-use-native-aio=OFF \
  --innodb-flush-method=fsync --innodb-doublewrite=OFF --innodb-flush-log-at-trx-commit=0 \
  --character-set-server=utf8mb4 --default-time-zone=+00:00 --sql-mode=__SQL_MODE__"
if ! mysqld $MYSQL_OPTS --initialize-insecure > /work/mysql-init.log 2>&1; then
  echo "__START__"; echo "the database could not start"; tail -20 /work/mysqld.log; echo "__END__"; exit 0
fi
mysqld $MYSQL_OPTS --bind-address=127.0.0.1 --port=3306 --skip-name-resolve > /dev/null 2>&1 &
for i in $(seq 1 120); do mysqladmin --socket=/work/mysql.sock -uroot ping > /dev/null 2>&1 && break; sleep 1; done
mysql --socket=/work/mysql.sock -uroot -e "CREATE DATABASE nexti"
if ! mysql --socket=/work/mysql.sock -uroot nexti < __SCHEMA__ > /work/schema.log 2>&1; then
  echo "__START__"; echo "the schema does not load:"; cat /work/schema.log; echo "__END__"; exit 0
fi
echo "__START__"
mysql --socket=/work/mysql.sock -uroot --force nexti < /input/__PROBE__ 2>&1 | grep -E "^ERROR" || true
echo "__END__"
""".replace("__SQL_MODE__", SQL_MODE)
    .replace("__SCHEMA__", SCHEMA)
    .replace("__PROBE__", PROBE_PATH)
    .replace("__START__", START)
    .replace("__END__", END)
)
MYSQL_ERROR = re.compile(r"ERROR \d+ \([0-9A-Z]+\) at line (\d+): (.*)")


def mysql_probe_file(found: list[str]) -> str:
    """One PREPARE per line, so the line of an error names its statement."""

    def quoted(text: str) -> str:
        return text.rstrip(";").replace("\\", "\\\\").replace("'", "''")

    return "".join(f"PREPARE nx_probe_{i} FROM '{quoted(s)}';\n" for i, s in enumerate(found, start=1))


async def probe_mysql(sandbox: Sandbox, files: Mapping[str, str], path: str) -> str:
    found = java_statements(files.get(path, ""))
    if not found:
        return ""
    build = await compile_and_test(sandbox, files, run_tests=False, extra_inputs={PROBE_PATH: mysql_probe_file(found)},
                                   after=MYSQL_SCRIPT, limits=MYSQL_LIMITS)  # fmt: skip
    return by_line(build.after_output, found, MYSQL_ERROR) if build.compiled else ""


ORACLE_TEMPLATE = r"""
/opt/oracle/container-entrypoint.sh > /work/oracle.log 2>&1 &
for i in $(seq 1 300); do
  grep -q "DATABASE IS READY" /work/oracle.log && break
  grep -q "ORA-00600" /work/oracle.log && break
  sleep 1
done
if ! grep -q "DATABASE IS READY" /work/oracle.log; then
  echo "__START__"; echo "the database could not start"; tail -20 /work/oracle.log; echo "__END__"; exit 0
fi
( echo "WHENEVER SQLERROR EXIT FAILURE"; cat __SCHEMA__; echo "EXIT" ) > /work/schema-run.sql
if ! sqlplus -s __LOGIN__ @/work/schema-run.sql > /work/schema.log 2>&1; then
  echo "__START__"; echo "the schema does not load:"; cat /work/schema.log; echo "__END__"; exit 0
fi
echo "__START__"
sqlplus -s __LOGIN__ @/input/__PROBE__ 2>&1 | grep -E "__MARK__|ORA-|SP2-" || true
echo "__END__"
"""


def oracle_script(schema: str) -> str:
    """The probe's script on an Oracle sandbox (the Java pack's or the .NET pack's): the schema at `schema`."""
    return (ORACLE_TEMPLATE.replace("__SCHEMA__", schema).replace("__PROBE__", PROBE_PATH)
            .replace("__LOGIN__", f"{USER}/{PASSWORD}@localhost/{SERVICE}").replace("__MARK__", MARK.rstrip("|"))
            .replace("__START__", START).replace("__END__", END))  # fmt: skip


ORACLE_SCRIPT = oracle_script(SCHEMA)


def binds(text: str) -> str:
    """`?` placeholders as Oracle binds :1, :2..."""
    parts = text.split("?")
    return parts[0] + "".join(f":{n}{rest}" for n, rest in enumerate(parts[1:], start=1))


def oracle_probe_file(found: list[str]) -> str:
    """A marker before each EXPLAIN PLAN, so the errors that follow belong to that statement; `?` become binds."""
    lines = ["SET FEEDBACK OFF", "SET HEADING OFF", "WHENEVER SQLERROR CONTINUE"]
    for i, text in enumerate(found, start=1):
        bound = binds(text.rstrip(";"))
        lines += [f"PROMPT {MARK}{i}", f"EXPLAIN PLAN FOR {bound};"]
    return "\n".join([*lines, "EXIT", ""])


async def probe_oracle(sandbox: Sandbox, files: Mapping[str, str], path: str) -> str:
    found = java_statements(files.get(path, ""))
    if not found:
        return ""
    build = await compile_and_test(sandbox, files, run_tests=False,
                                   extra_inputs={PROBE_PATH: oracle_probe_file(found)}, after=ORACLE_SCRIPT,
                                   limits=ORACLE_LIMITS)  # fmt: skip
    return by_marker(build.after_output, found) if build.compiled else ""
