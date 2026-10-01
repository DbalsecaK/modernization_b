"""Basic performance (ADR-0023): the time of each test of the clean build, from its JUnit XML. A test slower than
the threshold is a finding: the generated code may hide a slow query or a missing index."""

import xml.etree.ElementTree as ET

from nexti_hardening.report import Check, Finding

THRESHOLD_SECONDS = 2.0


def scan(junit_xml: str | None, threshold: float = THRESHOLD_SECONDS) -> tuple[list[Finding], Check]:
    if not junit_xml:
        return [], Check("performance", "not_checked", "no test report of the clean build")
    try:
        root = ET.fromstring(junit_xml)  # noqa: S314
    except ET.ParseError:
        return [], Check("performance", "not_checked", "the test report cannot be read")
    cases = root.iter("testcase")
    findings: list[Finding] = []
    count, total = 0, 0.0
    for case in cases:
        count += 1
        seconds = float(case.get("time") or 0)
        total += seconds
        if seconds > threshold:
            where = case.get("classname") or case.get("file") or "tests"
            message = f"{case.get('name')} took {seconds:.1f} s (threshold {threshold:.0f} s)"
            findings.append(Finding("performance", "low", "slow-test", where, None, message))
    return findings, Check("performance", "checked", f"{count} test(s) in {total:.1f} s")
