"""What a build in the sandbox produced (ADR-0017), the same for every backend pack: whether it compiled, the
tests read from the JUnit XML report (never from what an agent says) and what a script printed after it."""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


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
