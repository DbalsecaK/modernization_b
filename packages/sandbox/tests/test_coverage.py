"""Target coverage under the golden master (M29, ADR-0049): each tool's report, read back from the harness output."""

import base64
import gzip

from nexti_sandbox.coverage import Region, from_cobertura, from_coverprofile, from_jacoco, target_coverage

JACOCO = """<?xml version="1.0"?><report name="t"><package name="com/acme/pay">
<sourcefile name="PayService.java">
<line nr="10" mi="0" ci="4" mb="0" cb="0"/><line nr="11" mi="3" ci="0" mb="0" cb="0"/>
<line nr="12" mi="2" ci="0" mb="0" cb="0"/><line nr="15" mi="0" ci="2" mb="0" cb="0"/>
<line nr="20" mi="5" ci="0" mb="0" cb="0"/></sourcefile></package></report>"""

COBERTURA = """<?xml version="1.0"?><coverage><packages><package name="App"><classes>
<class name="App.Pay" filename="/work/p/src/App/Services/Pay.cs"><lines>
<line number="5" hits="1"/><line number="6" hits="0"/><line number="7" hits="0"/></lines></class>
<class name="Harness.Main" filename="/work/harness/Program.cs"><lines><line number="1" hits="0"/></lines></class>
</classes></package></packages></coverage>"""

PROFILE = """mode: set
example.com/app/internal/pay/service.go:10.2,12.16 2 1
example.com/app/internal/pay/service.go:13.3,14.20 1 0
example.com/app/cmd/nexti-equivalence/main.go:5.1,9.2 3 0
"""


def _emitted(fmt: str, text: str) -> str:
    payload = base64.b64encode(gzip.compress(text.encode("utf-8"))).decode("ascii")
    return f"NXE {{}}\n===EQUIVALENCE-END===\n===COVERAGE {fmt}===\n{payload}\n===COVERAGE-END===\n"


def test_jacoco_lines_no_case_ran_become_regions_of_the_source_file() -> None:
    measured = from_jacoco(JACOCO)
    assert (measured.lines_total, measured.lines_covered) == (5, 2)
    path = "src/main/java/com/acme/pay/PayService.java"
    assert measured.uncovered == [Region(path, 11, 12), Region(path, 20, 20)]


def test_cobertura_leaves_the_harness_out() -> None:
    measured = from_cobertura(COBERTURA)
    assert (measured.lines_total, measured.lines_covered) == (3, 1)
    assert measured.uncovered == [Region("src/App/Services/Pay.cs", 6, 7)]


def test_go_profile_blocks_leave_the_harness_out() -> None:
    measured = from_coverprofile(PROFILE)
    assert measured.uncovered == [Region("example.com/app/internal/pay/service.go", 13, 14)]
    assert measured.lines_covered == 3


def test_the_report_comes_back_from_the_harness_output_or_not_at_all() -> None:
    measured = target_coverage(_emitted("jacoco", JACOCO))
    assert measured is not None
    assert measured.tool == "jacoco"
    assert "2 of 5 executable lines" in measured.note()
    assert target_coverage("NXE {}\n===EQUIVALENCE-END===\n") is None  # an image without the tool
    assert target_coverage("===COVERAGE go===\nnot base64!\n===COVERAGE-END===") is None
