"""Compile and test generated Java in the sandbox (spec 11.1, 11.3 check 1): javac over the chosen source folders
with the pack's libraries, then the JUnit console launcher. Test counts are read from the JUnit XML report, never
from what an agent says."""

from collections.abc import Mapping

from nexti_sandbox import Limits, Sandbox
from nexti_sandbox.build import BuildResult, TestCaseResult, parse_junit

__all__ = ["IMAGE", "LIMITS", "BuildResult", "TestCaseResult", "compile_and_test", "parse_junit"]

IMAGE = "nexti-sandbox-java:2"
LIMITS = Limits(cpus=2.0, memory_mb=1536, pids=512, timeout_seconds=600, work_mb=512, max_output_bytes=2 * 1024 * 1024)
REPORT_START = "===JUNIT-XML==="

SCRIPT = r"""
set -e
cd /work
cp -r /input/project /work/p
find /work/p/src/main/java -name '*.java' > /work/main.txt
mkdir -p /work/out /work/test-out /work/reports
if ! javac -nowarn -encoding UTF-8 -d /work/out -cp '/opt/lib/*' @/work/main.txt 2> /work/javac.txt; then
  echo "===COMPILE-FAILED==="; cat /work/javac.txt; exit 2
fi
if [ "$RUN_TESTS" = "1" ] && [ -d /work/p/src/test/java ]; then
  find /work/p/src/test/java -name '*.java' > /work/test.txt
  if [ -s /work/test.txt ]; then
    if ! javac -nowarn -encoding UTF-8 -d /work/test-out -cp "/work/out:/opt/lib/*" @/work/test.txt \
        2> /work/javac.txt; then
      echo "===TEST-COMPILE-FAILED==="; cat /work/javac.txt; exit 3
    fi
    # The launcher does not expand wildcards like java does: the libraries go one by one.
    LIBS=$(ls /opt/lib/*.jar | grep -v junit-platform-console | tr '\n' ':')
    java -jar /opt/lib/junit-platform-console-standalone-*.jar execute --disable-banner --details=none \
      --class-path "/work/out:/work/test-out:$LIBS" --scan-class-path --reports-dir /work/reports \
      > /work/junit.txt 2>&1 || true
    echo "===JUNIT-XML==="; cat /work/reports/*.xml
  fi
fi
echo "===AFTER==="
"""
DONE = '\necho "===DONE==="\n'

# ADR-0055 (point 17): the schema of the design is created on a real PostgreSQL in the sandbox, nothing else.
SCHEMA_SCRIPT = r"""
set -u
if ! initdb -D /work/pg -U nexti --auth=trust -E UTF8 --no-locale > /work/pg-init.log 2>&1; then
  echo "===SCHEMA-ENGINE-FAILED==="; cat /work/pg-init.log; exit 5
fi
if ! pg_ctl -D /work/pg -l /work/pg.log -o "-k /work -c listen_addresses=localhost -c port=5432 -F" -w start \
    > /dev/null; then
  echo "===SCHEMA-ENGINE-FAILED==="; cat /work/pg.log; exit 5
fi
psql -h localhost -U nexti -d postgres -q -c "CREATE DATABASE nexti" > /dev/null
if psql -h localhost -U nexti -d nexti -q -v ON_ERROR_STOP=1 -f /input/schema.sql > /work/schema.log 2>&1; then
  echo "===SCHEMA-OK==="
else
  echo "===SCHEMA-FAILED==="; cat /work/schema.log
fi
pg_ctl -D /work/pg -m fast stop > /dev/null 2>&1 || true
echo "===SCHEMA-END==="
"""


async def apply_schema(sandbox: Sandbox, schema: str, limits: Limits = LIMITS) -> str:
    """Creates `schema` on a real PostgreSQL inside the sandbox: "" when it applied, else the engine's error."""
    result = await sandbox.run(["sh", "-c", SCHEMA_SCRIPT], files={"schema.sql": schema.encode("utf-8")},
                               limits=limits)  # fmt: skip
    out = result.stdout
    if "===SCHEMA-OK===" in out:
        return ""
    if "===SCHEMA-FAILED===" in out:
        return out.split("===SCHEMA-FAILED===", 1)[1].split("===SCHEMA-END===", 1)[0].strip() or "unknown error"
    if "===SCHEMA-ENGINE-FAILED===" in out:
        return (
            "the database engine of the sandbox did not start: "
            + out.split("===SCHEMA-ENGINE-FAILED===", 1)[1][:800].strip()
        )
    return f"the schema check did not finish (exit {result.exit_code}): {(result.stderr or out)[-800:]}"


async def compile_and_test(
    sandbox: Sandbox,
    files: Mapping[str, str],
    *,
    run_tests: bool = True,
    extra_inputs: Mapping[str, str] | None = None,
    after: str = "",
    limits: Limits = LIMITS,
) -> BuildResult:
    """`extra_inputs` land in /input next to the project; `after` runs once the project compiled and tested."""
    inputs = {f"project/{path}": content.encode("utf-8") for path, content in files.items()}
    inputs.update({path: content.encode("utf-8") for path, content in (extra_inputs or {}).items()})
    script = f"RUN_TESTS={'1' if run_tests else '0'}; export RUN_TESTS; {SCRIPT}{after}{DONE}"
    result = await sandbox.run(["sh", "-c", script], files=inputs, limits=limits)
    out = result.stdout
    if "===COMPILE-FAILED===" in out or "===TEST-COMPILE-FAILED===" in out:
        marker = "===COMPILE-FAILED===" if "===COMPILE-FAILED===" in out else "===TEST-COMPILE-FAILED==="
        errors = out.split(marker, 1)[1]
        return BuildResult(False, errors.replace("/work/p/", "").strip(), duration_ms=result.duration_ms)
    if "===DONE===" not in out:
        detail = (result.stderr or out)[-3000:]
        return BuildResult(False, f"the build did not finish (exit {result.exit_code}): {detail}",
                           duration_ms=result.duration_ms)  # fmt: skip
    xml = out.split(REPORT_START, 1)[1].split("===AFTER===", 1)[0] if REPORT_START in out else ""
    after_output = out.split("===AFTER===", 1)[1].split("===DONE===", 1)[0] if "===AFTER===" in out else ""
    return BuildResult(True, tests=parse_junit(xml), junit_xml=xml.strip(), duration_ms=result.duration_ms,
                       after_output=after_output)  # fmt: skip
