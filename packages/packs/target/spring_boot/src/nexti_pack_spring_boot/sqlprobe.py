"""The SQL of a generated adapter, prepared against the target schema in the sandbox before the adapter is accepted
(P32). The adapter step used to verify compilation only: a real run generated a catalog adapter whose query joined
a legacy lookup table the design does not keep, and 68 of 73 golden-master cases crashed with BadSqlGrammarException
three rounds later, in a step that could not even show the developer that file. PostgreSQL's PREPARE checks tables,
columns and syntax without running anything."""

import re
from collections.abc import Mapping

from nexti_pack_spring_boot.build import compile_and_test
from nexti_sandbox import Sandbox

STATEMENT_START = re.compile(r"^\s*(select|insert|update|delete|with|merge)\b", re.I)
# A Java string literal ("..." with escapes) or a text block ("""..."""); `+` between them is concatenation.
LITERAL = re.compile(r'"""(.*?)"""|"((?:[^"\\\n]|\\.)*)"', re.S)
JOINER = re.compile(r"^[\s+]*$")
PROBE_PATH = "sql-probe.sql"
START = "===SQL-PROBE==="
END = "===SQL-PROBE-END==="

SCRIPT = rf"""
if ! initdb -D /work/pg -U nexti --auth=trust -E UTF8 --no-locale > /work/pg-init.log 2>&1; then
  echo "{START}"; echo "the database could not start:"; cat /work/pg-init.log; echo "{END}"; exit 0
fi
if ! pg_ctl -D /work/pg -l /work/pg.log -o "-k /work -c listen_addresses=localhost -c port=5432 -F" -w start \
    > /dev/null; then
  echo "{START}"; echo "the database could not start:"; cat /work/pg.log; echo "{END}"; exit 0
fi
psql -h localhost -U nexti -d postgres -q -c "CREATE DATABASE nexti" > /dev/null
if ! psql -h localhost -U nexti -d nexti -q -v ON_ERROR_STOP=1 -f /work/p/src/main/resources/db/schema.sql \
    > /work/schema.log 2>&1; then
  echo "{START}"; echo "the schema does not load:"; cat /work/schema.log; echo "{END}"; exit 0
fi
echo "{START}"
psql -h localhost -U nexti -d nexti -v ON_ERROR_STOP=0 -f /input/{PROBE_PATH} 2>&1 | grep -E "ERROR|LINE|HINT" || true
echo "{END}"
pg_ctl -D /work/pg -m fast stop > /dev/null 2>&1 || true
"""


def sql_statements(java: str) -> list[str]:
    """The SQL statements an adapter builds from its string literals: adjacent literals joined by `+` are one
    statement; `?` placeholders become $1, $2… so PREPARE can type them. A statement concatenated with code (an
    `IN (` list of placeholders built at run time, a table chosen by a variable) is only known when it runs: it is
    not probed (P38: the probe once rejected `… IN (` as a syntax error, a fragment of a correct statement)."""
    statements: list[tuple[str, bool]] = []
    current = ""
    dynamic = False
    last_end = 0
    for match in LITERAL.finditer(java):
        text = match.group(1) if match.group(1) is not None else _unescape(match.group(2) or "")
        between = java[last_end : match.start()]
        if current and JOINER.match(between):
            current += text
        elif current and between.strip().startswith("+"):  # literal + expression + literal: built at run time
            current += text
            dynamic = True
        else:
            if current:
                statements.append((current, dynamic))
            current, dynamic = text, False
        last_end = match.end()
        after = java[match.end() : match.end() + 200].lstrip()
        if after.startswith("+") and not after[1:].lstrip().startswith('"'):
            dynamic = True  # the literal goes on with an expression
    if current:
        statements.append((current, dynamic))
    found = []
    for statement, built_at_run_time in statements:
        if STATEMENT_START.match(statement) and not built_at_run_time:
            found.append(_numbered(" ".join(statement.split())))
    return found


def _unescape(text: str) -> str:
    return text.replace('\\"', '"').replace("\\n", " ").replace("\\t", " ").replace("\\\\", "\\")


def _numbered(statement: str) -> str:
    out = []
    n = 0
    for char in statement:
        if char == "?":
            n += 1
            out.append(f"${n}")
        else:
            out.append(char)
    return "".join(out)


def probe_file(statements: list[str]) -> str:
    """One PREPARE per line, so an error's line number names the statement."""
    return "".join(f"PREPARE probe_{i} AS {s.rstrip(';')};\n" for i, s in enumerate(statements, start=1))


def report(after_output: str, statements: list[str]) -> str:
    """The errors psql printed, each with the statement it refers to; empty when every statement prepared."""
    if START not in after_output:
        return ""
    body = after_output.split(START, 1)[1].split(END, 1)[0].strip()
    if not body:
        return ""
    lines = []
    for line in body.splitlines():
        match = re.search(rf"{re.escape(PROBE_PATH)}:(\d+):\s*(.*)", line)
        if match and 1 <= int(match.group(1)) <= len(statements):
            lines.append(f"{match.group(2).strip()}\n  statement: {statements[int(match.group(1)) - 1][:400]}")
        else:
            lines.append(line.strip())
    return "\n".join(lines)


async def probe_sql(sandbox: Sandbox, files: Mapping[str, str], path: str) -> str:
    """Prepare every SQL statement of the adapter at `path` against the project's schema; the errors, or ""."""
    statements = sql_statements(files.get(path, ""))
    if not statements:
        return ""
    build = await compile_and_test(sandbox, files, run_tests=False, extra_inputs={PROBE_PATH: probe_file(statements)},
                                   after=SCRIPT)  # fmt: skip
    if not build.compiled:
        return ""  # the compile step reports that
    return report(build.after_output, statements)
