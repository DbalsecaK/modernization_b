"""Compile and test generated Java in the sandbox (spec 11.1, 11.3 check 1): javac over the chosen source folders
with the pack's libraries, then the JUnit console launcher. Test counts are read from the JUnit XML report, never
from what an agent says."""

import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass, field

from nexti_sandbox import Limits, Sandbox

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


@dataclass
class TestCaseResult:
    __test__ = False  # not a pytest class

    classname: str
    name: str
    status: str  # passed, failed, skipped
    message: str = ""


@dataclass
class BuildResult:
    compiled: bool
    compile_errors: str = ""
    tests: list[TestCaseResult] = field(default_factory=list)
    junit_xml: str = ""
    duration_ms: int = 0
    after_output: str = ""  # what the `after` script printed (e.g. the equivalence harness)

    @property
    def passed(self) -> int:
        return sum(1 for t in self.tests if t.status == "passed")

    @property
    def failed(self) -> int:
        return sum(1 for t in self.tests if t.status == "failed")

    @property
    def ok(self) -> bool:
        return self.compiled and self.failed == 0

    def diagnostic(self, limit: int = 4000) -> str:
        if not self.compiled:
            return self.compile_errors[:limit]
        failures = [f"{t.classname}.{t.name}: {t.message}" for t in self.tests if t.status == "failed"]
        return "\n".join(failures)[:limit]


def parse_junit(xml: str) -> list[TestCaseResult]:
    results: list[TestCaseResult] = []
    documents = [d for d in re.split(r"(?=<\?xml)", xml) if d.strip()]
    for document in documents:
        root = ET.fromstring(document)  # noqa: S314 - produced by the JUnit launcher in our sandbox
        for case in root.iter("testcase"):
            failure = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")
            problem = failure if failure is not None else error
            status = "failed" if problem is not None else ("skipped" if skipped is not None else "passed")
            message = (problem.get("message") or problem.text or "")[:500] if problem is not None else ""
            results.append(TestCaseResult(case.get("classname", ""), case.get("name", ""), status, message))
    return results


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
    return BuildResult(True, tests=parse_junit(xml), junit_xml=xml.strip(), duration_ms=result.duration_ms,
                       after_output=after_output)  # fmt: skip
