"""Compile and test generated Go in the sandbox (spec 11.1, 11.3 check 1): `go build ./...` from the module cache the
image carries (no network), then `go test -json`. Its events become a JUnit XML report, read into the same test
results as every other pack (ADR-0029); counts never come from what an agent says."""

import json
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from typing import Any

from nexti_sandbox import Limits, Sandbox
from nexti_sandbox.build import BuildResult, parse_junit

IMAGE = "nexti-sandbox-go:1"
# `go test` runs the test binaries it links from GOTMPDIR (/work/tmp), and the harness runs from /work: /work allows
# running what it builds. The warm build cache (about 150 MB) and PostgreSQL's data live in /work too.
LIMITS = Limits(cpus=2.0, memory_mb=2048, pids=512, timeout_seconds=900, work_mb=1024,
                max_output_bytes=4 * 1024 * 1024, work_exec=True)  # fmt: skip
REPORT_START = "===GO-TEST-JSON==="

SCRIPT = r"""
set -e
mkdir -p /work/tmp
cp -r /opt/gocache /work/gocache
cp -r /input/project /work/p
cd /work/p
if ! go build ./... > /work/build.txt 2>&1; then
  echo "===COMPILE-FAILED==="; cat /work/build.txt; exit 2
fi
if [ "$RUN_TESTS" = "1" ] && [ -n "$(find . -name '*_test.go' | head -1)" ]; then
  go test -json -count=1 -vet=off ./... > /work/test.json 2> /work/test.err || true
  echo "===GO-TEST-JSON==="; cat /work/test.json; cat /work/test.err
fi
echo "===AFTER==="
"""
DONE = '\necho "===DONE==="\n'


def _events(text: str) -> list[dict[str, Any]]:
    events = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def build_errors(events: list[dict[str, Any]]) -> str:
    """The compiler output of the test packages that did not build; empty when every one did."""
    if not any(e.get("Action") == "build-fail" for e in events):
        return ""
    return "".join(e.get("Output", "") for e in events if e.get("Action") == "build-output").strip() or "build failed"


def junit_from_events(events: list[dict[str, Any]]) -> str:
    """The `go test -json` events as a JUnit XML report: one test case per test that has no subtests (a subtest is a
    case of its own), with its output as the failure text; a package that failed outside any test is a failed
    case named after the package."""
    results: dict[tuple[str, str], str] = {}
    output: dict[tuple[str, str], list[str]] = {}
    elapsed: dict[tuple[str, str], float] = {}
    packages: dict[str, str] = {}
    for event in events:
        package, test, action = event.get("Package", ""), event.get("Test"), event.get("Action")
        if not package:
            continue
        key = (package, test or "")
        if action == "output":
            output.setdefault(key, []).append(event.get("Output", ""))
        elif action in ("pass", "fail", "skip"):
            if test:
                results[key] = action
                elapsed[key] = float(event.get("Elapsed") or 0)
            else:
                packages[package] = action
    parents = {(p, t.rsplit("/", 1)[0]) for p, t in results if "/" in t}
    root = ET.Element("testsuites")
    by_package: dict[str, list[tuple[str, str]]] = {}
    for package, test in sorted(k for k in results if k not in parents):
        by_package.setdefault(package, []).append((test, results[(package, test)]))
    for package, action in sorted(packages.items()):
        failed_inside = any(r == "fail" for (p, _), r in results.items() if p == package)
        if action == "fail" and not failed_inside:
            by_package.setdefault(package, []).append(("(package)", "fail"))
    for package, cases in sorted(by_package.items()):
        suite = ET.SubElement(root, "testsuite", name=package, tests=str(len(cases)),
                              failures=str(sum(1 for _, a in cases if a == "fail")))  # fmt: skip
        for test, action in cases:
            key = (package, "" if test == "(package)" else test)
            case = ET.SubElement(suite, "testcase", classname=package, name=test, time=f"{elapsed.get(key, 0):.3f}")
            text = "".join(output.get(key, []))
            if action == "fail":
                lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("===")]
                failure = ET.SubElement(case, "failure", message=(" ".join(lines[-3:]) or "failed")[:500])
                failure.text = text[-4000:]
            elif action == "skip":
                ET.SubElement(case, "skipped")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


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
    if "===COMPILE-FAILED===" in out:
        errors = out.split("===COMPILE-FAILED===", 1)[1]
        return BuildResult(False, errors.replace("/work/p/", "").strip(), duration_ms=result.duration_ms)
    if "===DONE===" not in out:
        detail = (result.stderr or out)[-3000:]
        return BuildResult(False, f"the build did not finish (exit {result.exit_code}): {detail}",
                           duration_ms=result.duration_ms)  # fmt: skip
    report = out.split(REPORT_START, 1)[1].split("===AFTER===", 1)[0] if REPORT_START in out else ""
    events = _events(report)
    errors = build_errors(events)
    if errors:
        return BuildResult(False, errors.replace("/work/p/", ""), duration_ms=result.duration_ms)
    xml = junit_from_events(events) if events else ""
    after_output = out.split("===AFTER===", 1)[1].split("===DONE===", 1)[0] if "===AFTER===" in out else ""
    return BuildResult(True, tests=parse_junit(xml) if xml else [], junit_xml=xml, duration_ms=result.duration_ms,
                       after_output=after_output)  # fmt: skip
