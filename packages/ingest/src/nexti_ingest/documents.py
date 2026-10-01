"""Documents as citable text (spec 7.1, ADR-0018): every accepted document becomes lines that rules, stories and
screens cite as `file:line`, like the code of Flow 1. Markdown and plain text are decoded here; Word, Excel and PDF are
untrusted binaries (rule 5), so they are converted inside the sandbox without network: Word and Excel with the Python
standard library (they are ZIP files with XML), PDF with pypdf in the image nexti-sandbox-docs."""

import json
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from nexti_sandbox import Limits, Sandbox

IMAGE = "nexti-sandbox-docs:1"
TEXT_SUFFIXES = (".md", ".markdown", ".txt")
SANDBOX_SUFFIXES = (".docx", ".xlsx", ".pdf")
MAX_LINES = 20_000
LIMITS = Limits(cpus=1.0, memory_mb=512, pids=64, timeout_seconds=120, work_mb=64, max_output_bytes=8 * 1024 * 1024)


@dataclass(frozen=True)
class Document:
    """A converted document: its citable path (`docs/<name>`), its text and what the conversion could not keep."""

    path: str
    text: str
    warnings: tuple[str, ...] = field(default=())

    @property
    def lines(self) -> list[str]:
        return self.text.split("\n")


def citable_path(name: str) -> str:
    return f"docs/{PurePosixPath(name).name}"


def _decode(data: bytes) -> str:
    text = data.decode("utf-8-sig", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _limited(lines: list[str], warnings: list[str]) -> str:
    if len(lines) > MAX_LINES:
        warnings.append(f"only the first {MAX_LINES} lines are read")
        lines = lines[:MAX_LINES]
    return "\n".join(line.rstrip() for line in lines)


async def convert(sandbox: Sandbox | None, documents: list[tuple[str, bytes]]) -> list[Document]:
    """The documents as text, in the order given. A format this version does not read stays out with a warning; a
    document the sandbox could not convert comes back empty with the reason."""
    converted: dict[str, Document] = {}
    binaries: dict[str, bytes] = {}
    for name, data in documents:
        suffix = PurePosixPath(name).suffix.lower()
        path = citable_path(name)
        if suffix in TEXT_SUFFIXES:
            warnings: list[str] = []
            converted[path] = Document(path, _limited(_decode(data).split("\n"), warnings), tuple(warnings))
        elif suffix in SANDBOX_SUFFIXES:
            binaries[path] = data
        else:
            converted[path] = Document(path, "", (f"{suffix or 'this'} documents are not read in this version",))
    if binaries:
        if sandbox is None:
            raise RuntimeError("Word, Excel and PDF documents are converted in the sandbox, and there is none")
        files = {"extract.py": SCRIPT.encode("utf-8"), **binaries}
        result = await sandbox.run(["python", "/input/extract.py"], files, LIMITS)
        try:
            found = json.loads(result.stdout) if result.ok else {}
        except json.JSONDecodeError:
            found = {}
        for path in binaries:
            item = found.get(path.removeprefix("docs/"))
            if not isinstance(item, dict) or "lines" not in item:
                reason = (item or {}).get("error") if isinstance(item, dict) else None
                detail = reason or (result.stderr.strip()[-300:] if not result.ok else "no text came back")
                converted[path] = Document(path, "", (f"could not be converted: {detail}",))
                continue
            warnings = [str(w) for w in item.get("warnings", [])]
            converted[path] = Document(path, _limited([str(x) for x in item["lines"]], warnings), tuple(warnings))
    return [converted[citable_path(name)] for name, _ in documents if citable_path(name) in converted]


# The converter that runs in the sandbox (no network, read-only inputs). Word: a paragraph per line, headings as
# Markdown, each table row in one line with " | ". Excel: each sheet with its header and a line per row. PDF: each
# page marked, then its text lines. XML with a DTD is refused (no entity expansion).
SCRIPT = r"""
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
P = "{http://schemas.openxmlformats.org/package/2006/relationships}"
MAX_XML = 32 * 1024 * 1024


def xml(archive, name):
    if archive.getinfo(name).file_size > MAX_XML:
        raise ValueError(name + " is too large")
    data = archive.read(name)
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError("XML with a DTD is not accepted")
    return ET.fromstring(data)


def paragraph(p):
    out = []
    for node in p.iter():
        if node.tag == W + "t":
            out.append(node.text or "")
        elif node.tag == W + "tab":
            out.append("\t")
        elif node.tag in (W + "br", W + "cr"):
            out.append(" ")
    text = "".join(out).strip()
    style = p.find(W + "pPr/" + W + "pStyle")
    level = re.match(r"(?i)^(?:heading|t\w?tulo)\s*(\d)$", style.get(W + "val", "")) if style is not None else None
    return ("#" * int(level.group(1)) + " " + text) if level and text else text


def docx(path):
    with zipfile.ZipFile(path) as archive:
        body = xml(archive, "word/document.xml").find(W + "body")
    lines = []
    for block in body if body is not None else []:
        if block.tag == W + "p":
            lines.append(paragraph(block))
        elif block.tag == W + "tbl":
            for row in block.iter(W + "tr"):
                cells = [" ".join(paragraph(p) for p in cell.iter(W + "p")).strip() for cell in row.findall(W + "tc")]
                lines.append(" | ".join(cells))
    return lines, []


def column(ref):
    letters = re.match(r"[A-Z]+", ref or "A").group(0)
    number = 0
    for ch in letters:
        number = number * 26 + ord(ch) - 64
    return number - 1


def xlsx(path):
    lines = []
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            for item in xml(archive, "xl/sharedStrings.xml").findall(S + "si"):
                shared.append("".join(t.text or "" for t in item.iter(S + "t")))
        relations = xml(archive, "xl/_rels/workbook.xml.rels").findall(P + "Relationship")
        targets = {r.get("Id"): r.get("Target") for r in relations}
        for sheet in xml(archive, "xl/workbook.xml").iter(S + "sheet"):
            target = targets.get(sheet.get(R + "id"), "")
            member = target.lstrip("/") if target.startswith("/") else "xl/" + target
            if member not in names:
                continue
            lines.append("# Sheet: " + sheet.get("name", ""))
            for row in xml(archive, member).iter(S + "row"):
                values = {}
                for cell in row.findall(S + "c"):
                    kind = cell.get("t")
                    if kind == "s":
                        v = cell.find(S + "v")
                        value = shared[int(v.text)] if v is not None and v.text else ""
                    elif kind == "inlineStr":
                        value = "".join(t.text or "" for t in cell.iter(S + "t"))
                    else:
                        v = cell.find(S + "v")
                        value = v.text if v is not None and v.text else ""
                    values[column(cell.get("r"))] = value.strip()
                if any(values.values()):
                    lines.append(" | ".join(values.get(i, "") for i in range(max(values) + 1)))
    return lines, []


def pdf(path):
    from pypdf import PdfReader

    lines, warnings = [], []
    reader = PdfReader(str(path))
    for number, page in enumerate(reader.pages, start=1):
        lines.append("# Page " + str(number))
        text = page.extract_text() or ""
        if not text.strip():
            warnings.append("page " + str(number) + " has no text that can be extracted (a scan?)")
        lines += [line.rstrip() for line in text.splitlines()]
    return lines, warnings


READERS = {".docx": docx, ".xlsx": xlsx, ".pdf": pdf}
found = {}
for path in sorted(Path("/input/docs").iterdir()):
    try:
        lines, warnings = READERS[path.suffix.lower()](path)
        found[path.name] = {"lines": lines, "warnings": warnings}
    except Exception as exc:  # one broken document never hides the others
        found[path.name] = {"error": (type(exc).__name__ + ": " + str(exc))[:300]}
json.dump(found, sys.stdout)
"""
