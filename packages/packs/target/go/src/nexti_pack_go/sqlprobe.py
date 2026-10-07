"""The SQL probe of the Go pack (P32 for Go, step 12 of the plan): the statements of a generated pgx adapter prepared
against the target schema with PostgreSQL's PREPARE in the sandbox, before the adapter is accepted."""

import re
from collections.abc import Mapping

from nexti_pack_go.build import compile_and_test
from nexti_pack_go.generate import SCHEMA
from nexti_pack_spring_boot.sqlprobe import probe_file, report
from nexti_sandbox import Sandbox
from nexti_sandbox.sqlprobe import END, PROBE_PATH, START, statements

# Go: a raw string `...` or an interpreted "..." with escapes.
LITERAL = re.compile(r'`([^`]*)`|"((?:[^"\\\n]|\\.)*)"')


def _text(match: re.Match[str]) -> tuple[str, bool]:
    if match.group(1) is not None:
        return match.group(1), False
    return (match.group(2) or "").replace('\\"', '"').replace("\\n", " ").replace("\\t", " ").replace(
        "\\\\", "\\"
    ), False


def go_statements(source: str) -> list[str]:
    return statements(source, LITERAL, _text)


SCRIPT = rf"""
if ! initdb -D /work/pg -U nexti --auth=trust -E UTF8 --no-locale > /work/pg-init.log 2>&1; then
  echo "{START}"; echo "the database could not start:"; cat /work/pg-init.log; echo "{END}"; exit 0
fi
if ! pg_ctl -D /work/pg -l /work/pg.log -o "-k /work -c listen_addresses=localhost -c port=5432 -F" -w start \
    > /dev/null; then
  echo "{START}"; echo "the database could not start:"; cat /work/pg.log; echo "{END}"; exit 0
fi
psql -h localhost -U nexti -d postgres -q -c "CREATE DATABASE nexti" > /dev/null
if ! psql -h localhost -U nexti -d nexti -q -v ON_ERROR_STOP=1 -f /work/p/{SCHEMA} > /work/schema.log 2>&1; then
  echo "{START}"; echo "the schema does not load:"; cat /work/schema.log; echo "{END}"; exit 0
fi
echo "{START}"
psql -h localhost -U nexti -d nexti -v ON_ERROR_STOP=0 -f /input/{PROBE_PATH} 2>&1 | grep -E "ERROR|LINE|HINT" || true
echo "{END}"
pg_ctl -D /work/pg -m fast stop > /dev/null 2>&1 || true
"""


async def probe_sql(sandbox: Sandbox, files: Mapping[str, str], path: str) -> str:
    """Prepare every SQL statement of the adapter at `path` against the project's schema; the errors, or ""."""
    found = go_statements(files.get(path, ""))
    if not found:
        return ""
    build = await compile_and_test(sandbox, files, run_tests=False, extra_inputs={PROBE_PATH: probe_file(found)},
                                   after=SCRIPT)  # fmt: skip
    return report(build.after_output, found) if build.compiled else ""
