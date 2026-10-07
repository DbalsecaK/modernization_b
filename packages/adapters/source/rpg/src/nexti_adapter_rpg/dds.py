"""DDS of IBM i files (spec 8.2, ADR-0051): physical files (PF), logical files (LF), display files (DSPF) and printer
files (PRTF), read from their A specs. A PF is a table with its fields and key; an LF a view over its PFILE; a DSPF a
set of screen records with their fields, positions and function keys; a PRTF a set of report records.

Columns (1-based): 6 A, 7-16 conditioning, 17 type (R record, K key, J join, S/O select/omit, H help), 19-28 name,
29 reference, 30-34 length, 35 data type, 36-37 decimals, 38 usage (I/O/B/H/P), 39-41 line, 42-44 position,
45-80 keywords (continued on the next A spec when the line ends with + or -)."""

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

EXTENSIONS = {".pf": "PF", ".lf": "LF", ".dspf": "DSPF", ".prtf": "PRTF", ".dds": "", ".pf38": "PF", ".lf38": "LF"}
_KEYWORD = re.compile(r"([A-Z][A-Z0-9]*)(?:\(([^)]*)\))?")


@dataclass
class DdsField:
    name: str
    length: int | None
    kind: str  # data type letter (A, P, S, B, L, T, Z...); blank: A for character, S for numeric in a PF
    decimals: int | None
    usage: str  # I O B (display), blank in PF/LF
    line: int
    row: int | None = None
    column: int | None = None
    keywords: str = ""
    reference: bool = False


@dataclass
class DdsRecord:
    name: str
    line: int
    fields: list[DdsField] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    keywords: str = ""
    texts: list[tuple[int, int, str]] = field(default_factory=list)  # constants on a screen: row, column, text


@dataclass
class DdsFile:
    name: str
    kind: str  # PF, LF, DSPF, PRTF
    file: str
    line_end: int
    records: list[DdsRecord] = field(default_factory=list)
    keywords: str = ""  # file-level keywords (UNIQUE, DSPSIZ, REF...)
    based_on: list[str] = field(default_factory=list)  # PFILE of a logical file
    problems: list[str] = field(default_factory=list)

    @property
    def fields(self) -> list[DdsField]:
        return [f for r in self.records for f in r.fields]


def is_dds(path: str, text: str) -> bool:
    if PurePosixPath(path).suffix.lower() in EXTENSIONS:
        return True
    lines = [line for line in text.splitlines() if line.strip()]
    return bool(lines) and sum(1 for line in lines if len(line) > 5 and line[5:6].upper() == "A") >= max(
        1, len(lines) * 0.8)  # fmt: skip


def _col(line: str, start: int, end: int) -> str:
    return line[start - 1 : end].strip() if len(line) >= start else ""


def _int(text: str) -> int | None:
    return int(text) if text.strip().isdigit() else None


def parse(path: str, text: str) -> DdsFile:
    name = PurePosixPath(path).stem.upper()
    lines = text.replace("\r\n", "\n").split("\n")
    dds = DdsFile(name, EXTENSIONS.get(PurePosixPath(path).suffix.lower(), ""), path, len(lines))
    record: DdsRecord | None = None
    last: DdsField | DdsRecord | DdsFile = dds
    continuing = False
    for number, raw in enumerate(lines, start=1):
        line = raw.rstrip()
        if len(line) < 6 or line[5:6].upper() != "A" or line[6:7] == "*":
            continue
        keywords = _col(line, 45, 80)
        if continuing:
            _append_keywords(last, keywords)
            continuing = keywords.endswith(("+", "-"))
            continue
        kind = _col(line, 17, 17).upper()
        fname = _col(line, 19, 28).upper()
        continuing = keywords.endswith(("+", "-"))
        if kind == "R":
            record = DdsRecord(fname, number, keywords=keywords)
            dds.records.append(record)
            last = record
            if "PFILE(" in keywords.upper():
                dds.based_on += _args(keywords, "PFILE")
            continue
        if kind == "K":
            if record is not None:
                record.keys.append(fname)
            continue
        if kind in ("J", "S", "O", "H"):
            continue
        if not fname:
            row, column = _int(_col(line, 39, 41)), _int(_col(line, 42, 44))
            constant = re.match(r"'((?:[^']|'')*)'", keywords)
            if record is not None and row is not None and column is not None and constant:
                record.texts.append((row, column, constant.group(1).replace("''", "'")))
            elif record is None:
                dds.keywords = f"{dds.keywords} {keywords}".strip()
                last = dds
            else:
                _append_keywords(record if last is record else last, keywords)
            continue
        if record is None:
            dds.problems.append(f"{path}:{number}: field {fname} before any record format")
            continue
        found = DdsField(fname, _int(_col(line, 30, 34)), _col(line, 35, 35).upper(), _int(_col(line, 36, 37)),
                         _col(line, 38, 38).upper(), number, _int(_col(line, 39, 41)), _int(_col(line, 42, 44)),
                         keywords, _col(line, 29, 29).upper() == "R")  # fmt: skip
        record.fields.append(found)
        last = found
    if not dds.kind:
        dds.kind = _infer_kind(dds)
    return dds


def _append_keywords(target: "DdsField | DdsRecord | DdsFile", keywords: str) -> None:
    target.keywords = f"{target.keywords.rstrip('+-')} {keywords}".strip()


def _args(keywords: str, name: str) -> list[str]:
    match = re.search(rf"\b{name}\(([^)]*)\)", keywords, re.I)
    return [a.split("/")[-1].upper() for a in match.group(1).split()] if match else []


def _infer_kind(dds: DdsFile) -> str:
    text = " ".join([dds.keywords, *(r.keywords for r in dds.records), *(f.keywords for f in dds.fields)]).upper()
    if dds.based_on:
        return "LF"
    if any(f.row is not None for f in dds.fields) or "DSPSIZ" in text or re.search(r"\bC[AF]\d\d\b", text):
        return "DSPF" if "SPACE" not in text and "SKIP" not in text else "PRTF"
    if "SPACEA" in text or "SKIPB" in text or "SPACEB" in text:
        return "PRTF"
    return "PF"


def function_keys(record: DdsRecord) -> list[str]:
    """CF03, CA12... declared on a display record: the actions of the screen."""
    return sorted(set(re.findall(r"\bC[AF]\d\d\b", record.keywords.upper())))
