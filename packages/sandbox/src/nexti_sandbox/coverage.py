"""Which code of the TARGET the golden master cases ran (M29, ADR-0049).

The equivalence script of a pack runs the harness under the native coverage tool of its stack (JaCoCo, dotnet-coverage
with Cobertura output, Go's -cover build) when the sandbox image has it, and prints the report after the harness,
compressed, between `===COVERAGE <format>===` and `===COVERAGE-END===`. Code that no case runs is reported as a
finding (possible logic the legacy does not have, or a branch the suite misses): it never blocks the verdict."""

import base64
import binascii
import gzip
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

START = re.compile(r"===COVERAGE (jacoco|cobertura|go)===")
END = "===COVERAGE-END==="
REGIONS_AT_MOST = 200


@dataclass(frozen=True)
class Region:
    file: str
    line_start: int
    line_end: int


@dataclass(frozen=True)
class TargetCoverage:
    tool: str
    lines_total: int
    lines_covered: int
    uncovered: list[Region] = field(default_factory=list)

    def note(self) -> str:
        return (f"{self.lines_covered} of {self.lines_total} executable lines of the target run by the golden master "
                f"cases ({self.tool})")  # fmt: skip

    def as_json(self) -> dict[str, object]:
        return {"tool": self.tool, "linesTotal": self.lines_total, "linesCovered": self.lines_covered,
                "uncovered": [{"file": r.file, "lineStart": r.line_start, "lineEnd": r.line_end}
                              for r in self.uncovered]}  # fmt: skip


def _regions(lines: dict[str, dict[int, bool]]) -> list[Region]:
    """Consecutive executable lines no case ran, per file, as regions."""
    out: list[Region] = []
    for path in sorted(lines):
        run: list[int] = []  # lines without code between two missed lines do not break a region; a line run does
        for number in sorted(lines[path]):
            if lines[path][number]:
                if run:
                    out.append(Region(path, run[0], run[-1]))
                run = []
            else:
                run.append(number)
        if run:
            out.append(Region(path, run[0], run[-1]))
    return out[:REGIONS_AT_MOST]


def _coverage(tool: str, lines: dict[str, dict[int, bool]]) -> TargetCoverage:
    total = sum(len(v) for v in lines.values())
    covered = sum(1 for v in lines.values() for hit in v.values() if hit)
    return TargetCoverage(tool, total, covered, _regions(lines))


def from_jacoco(xml: str, source_root: str = "src/main/java") -> TargetCoverage:
    root = ET.fromstring(xml)  # noqa: S314 - see the import
    lines: dict[str, dict[int, bool]] = {}
    for package in root.iter("package"):
        for source in package.iter("sourcefile"):
            path = f"{source_root}/{package.get('name', '')}/{source.get('name', '')}".replace("//", "/")
            for line in source.iter("line"):
                lines.setdefault(path, {})[int(line.get("nr", "0"))] = int(line.get("ci", "0")) > 0
    return _coverage("jacoco", lines)


def from_cobertura(xml: str, prefix: str = "/work/p/", exclude: str = "/harness") -> TargetCoverage:
    root = ET.fromstring(xml)  # noqa: S314 - see the import
    lines: dict[str, dict[int, bool]] = {}
    for cls in root.iter("class"):
        name = (cls.get("filename") or "").replace("\\", "/")
        if not name or exclude.lower() in name.lower():
            continue
        path = name.split(prefix, 1)[-1]
        for line in cls.iter("line"):
            number = int(line.get("number", "0"))
            hit = int(line.get("hits", "0")) > 0
            known = lines.setdefault(path, {})
            known[number] = known.get(number, False) or hit
    return _coverage("dotnet-coverage", lines)


_GO_BLOCK = re.compile(r"^(?P<file>.+\.go):(?P<l1>\d+)\.\d+,(?P<l2>\d+)\.\d+ (?P<stmts>\d+) (?P<count>\d+)$")


def from_coverprofile(text: str, exclude: str = "cmd/nexti-equivalence/") -> TargetCoverage:
    lines: dict[str, dict[int, bool]] = {}
    for raw in text.splitlines():
        match = _GO_BLOCK.match(raw.strip())
        if not match or exclude in match["file"] or match["stmts"] == "0":
            continue
        known = lines.setdefault(match["file"], {})
        for n in range(int(match["l1"]), int(match["l2"]) + 1):
            known[n] = known.get(n, False) or int(match["count"]) > 0
    return _coverage("go cover", lines)


def target_coverage(after_output: str) -> TargetCoverage | None:
    """The coverage report a pack printed after its harness, or None when the image measured none."""
    found = START.search(after_output)
    if not found or END not in after_output[found.end() :]:
        return None
    payload = after_output[found.end() :].split(END, 1)[0].strip()
    try:
        text = gzip.decompress(base64.b64decode(payload)).decode("utf-8", "replace")
        if found.group(1) == "jacoco":
            return from_jacoco(text)
        if found.group(1) == "cobertura":
            return from_cobertura(text)
        return from_coverprofile(text)
    except (binascii.Error, OSError, EOFError, ET.ParseError, ValueError):
        return None
