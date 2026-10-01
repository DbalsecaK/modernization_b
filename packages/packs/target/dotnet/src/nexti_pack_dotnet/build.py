"""Compile and test generated C# in the sandbox (spec 11.1, 11.3 check 1): an offline restore from the packages the
image carries, `dotnet build` of the application, then `dotnet test` with the JUnit logger. Test counts are read
from the JUnit XML report, never from what an agent says."""

from collections.abc import Mapping

from nexti_pack_dotnet.generate import APP, TESTS
from nexti_sandbox import Limits, Sandbox
from nexti_sandbox.build import BuildResult, parse_junit

IMAGE = "nexti-sandbox-dotnet:1"
# SQL Server needs about 2 GB and writes where it is installed: /var/opt/mssql is a tmpfs of its own. xUnit v3 runs
# each test project as its own executable, so /work allows running what it builds (ADR-0017).
LIMITS = Limits(cpus=2.0, memory_mb=3072, pids=1024, timeout_seconds=1500, work_mb=1536,
                max_output_bytes=2 * 1024 * 1024, scratch=(("/var/opt/mssql", 1024),), work_exec=True)  # fmt: skip
REPORT_START = "===JUNIT-XML==="

SCRIPT = rf"""
set -e
export TMPDIR=/work/tmp DOTNET_CLI_HOME=/work MSBUILDDISABLENODEREUSE=1 DOTNET_CLI_DO_NOT_USE_MSBUILD_SERVER=1
mkdir -p /work/tmp /work/reports
cp -r /input/project /work/p
cd /work/p
# The compiler errors once each, or the whole log when there is none to pick.
errors() {{ grep -E "error [A-Z]+[0-9]+" "$1" | sort -u | grep . || cat "$1"; }}
OPTS="--nologo -v q -c Release -p:UseSharedCompilation=false -p:TreatWarningsAsErrors=false"
if ! dotnet restore {APP}/App.csproj --source /opt/nuget -v q > /work/restore.txt 2>&1; then
  echo "===COMPILE-FAILED==="; cat /work/restore.txt; exit 2
fi
if ! dotnet build {APP}/App.csproj --no-restore $OPTS -clp:NoSummary > /work/build.txt 2>&1; then
  echo "===COMPILE-FAILED==="; errors /work/build.txt; exit 2
fi
if [ "$RUN_TESTS" = "1" ] && [ -f {TESTS}/App.Tests.csproj ] && ls {TESTS}/*.cs > /dev/null 2>&1; then
  if ! dotnet restore {TESTS}/App.Tests.csproj --source /opt/nuget -v q > /work/restore.txt 2>&1 \
      || ! dotnet build {TESTS}/App.Tests.csproj --no-restore $OPTS -clp:NoSummary > /work/build.txt 2>&1; then
    echo "===TEST-COMPILE-FAILED==="; cat /work/restore.txt; errors /work/build.txt; exit 3
  fi
  dotnet test {TESTS}/App.Tests.csproj --no-build --nologo -c Release \
    --logger "junit;LogFilePath=/work/reports/junit.xml" > /work/test.txt 2>&1 || true
  echo "{REPORT_START}"; cat /work/reports/junit.xml 2>/dev/null || true
fi
echo "===AFTER==="
"""
DONE = '\necho "===DONE==="\n'


async def compile_and_test(
    sandbox: Sandbox,
    files: Mapping[str, str],
    *,
    run_tests: bool = True,
    extra_inputs: Mapping[str, str] | None = None,
    after: str = "",
) -> BuildResult:
    """`extra_inputs` land in /input next to the project; `after` runs once the project compiled and tested."""
    inputs = {f"project/{path}": content.encode("utf-8") for path, content in files.items()}
    inputs.update({path: content.encode("utf-8") for path, content in (extra_inputs or {}).items()})
    script = f"RUN_TESTS={'1' if run_tests else '0'}; export RUN_TESTS; {SCRIPT}{after}{DONE}"
    result = await sandbox.run(["sh", "-c", script], files=inputs, limits=LIMITS)
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
    return BuildResult(True, tests=parse_junit(xml.strip()) if xml.strip() else [], junit_xml=xml.strip(),
                       duration_ms=result.duration_ms, after_output=after_output)  # fmt: skip
