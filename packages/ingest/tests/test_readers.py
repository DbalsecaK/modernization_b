"""Inputs as citable text (ADR-0018): documents become lines, Figma becomes one line per node, and the prototype's
buttons that navigate nowhere are found by code. Word, Excel and PDF are converted in the sandbox; those tests skip
without Docker or the image nexti-sandbox-docs:1."""

import asyncio
import io
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest

from nexti_ingest import documents, figma
from nexti_sandbox import DockerSandbox

EXAMPLE = Path(__file__).parent / "fixtures" / "simulador_credito"
FIGMA_FILE = "FicSimCred2026abc"
FIGMA: dict[str, Any] = json.loads((EXAMPLE / "figma" / f"{FIGMA_FILE}.json").read_text(encoding="utf-8"))
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def docx(body: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", f"<w:document {W}><w:body>{body}</w:body></w:document>")
    return buffer.getvalue()


def xlsx(rows: list[list[str]]) -> bytes:
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    shared = [v for row in rows for v in row]
    cells = "".join(
        f'<row r="{r + 1}">' + "".join(f'<c r="{chr(65 + c)}{r + 1}" t="s"><v>{shared.index(v)}</v></c>'
                                       for c, v in enumerate(row)) + "</row>"
        for r, row in enumerate(rows)
    )  # fmt: skip
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", f'<workbook {ns} {rel}><sheets><sheet name="Tasas" sheetId="1" '
                                            'r:id="rId1"/></sheets></workbook>')  # fmt: skip
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/'
                         'package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
                         "</Relationships>")  # fmt: skip
        archive.writestr("xl/sharedStrings.xml", f"<sst {ns}>" + "".join(f"<si><t>{v}</t></si>" for v in shared)
                         + "</sst>")  # fmt: skip
        archive.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{cells}</sheetData></worksheet>")
    return buffer.getvalue()


def pdf(lines: list[str]) -> bytes:
    """A one-page PDF with Helvetica text, its cross-reference table computed."""
    stream = "BT /F1 12 Tf 72 720 Td 14 TL " + " ".join(f"({line}) Tj T*" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def test_markdown_is_read_as_lines_with_a_citable_path() -> None:
    data = (EXAMPLE / "requisitos.md").read_bytes()
    (doc,) = asyncio.run(documents.convert(None, [("requisitos.md", data)]))
    assert doc.path == "docs/requisitos.md"
    assert doc.lines[0] == "# Simulador de crédito de consumo — Requisitos"
    assert any("RN-3." in line for line in doc.lines)
    assert doc.warnings == ()


def test_an_unread_format_stays_out_with_a_warning() -> None:
    (doc,) = asyncio.run(documents.convert(None, [("notas.rtf", b"{\\rtf1}")]))
    assert doc.text == ""
    assert "not read" in doc.warnings[0]


def test_figma_becomes_one_line_per_visible_node() -> None:
    text = figma.render(FIGMA_FILE, FIGMA)
    lines = text.split("\n")
    assert lines[0].startswith('# Figma file "Simulador de crédito')
    assert '  FRAME "Simulador" #1:2' in lines
    assert any('INSTANCE "Botón Calcular" #1:7 -> "Resultado"' in line for line in lines)
    assert not any("Notas del diseñador" in line for line in lines)  # invisible
    node = next(n for n in figma.nodes(FIGMA) if n.id == "2:5")
    assert lines[node.line - 1].strip().startswith('TEXT "Cuota mensual"')
    assert node.frame == "Resultado"


def test_a_button_that_navigates_nowhere_is_a_gap() -> None:
    assert [(n.name, n.frame) for n in figma.dead_buttons(FIGMA)] == [("Botón Descargar PDF", "Resultado")]


def test_the_file_key_comes_from_any_figma_link() -> None:
    assert figma.file_key(f"https://www.figma.com/design/{FIGMA_FILE}/Simulador?node-id=1-2") == FIGMA_FILE
    assert figma.file_key(f"https://www.figma.com/proto/{FIGMA_FILE}/x") == FIGMA_FILE
    assert figma.file_key("https://example.com/design/abc") is None


def test_the_client_sends_the_token_and_never_says_it() -> None:
    seen: dict[str, str] = {}

    def answer(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers["X-Figma-Token"]
        if request.url.path.endswith(f"/files/{FIGMA_FILE}"):
            return httpx.Response(200, json=FIGMA)
        return httpx.Response(403, json={"err": "Invalid token"})

    async def go() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as http:
            client = figma.FigmaClient(http, "figd_fake-token")
            assert (await client.file(FIGMA_FILE))["name"] == FIGMA["name"]
            with pytest.raises(figma.FigmaError) as refused:
                await client.me()
            assert "figd_fake-token" not in str(refused.value)

    asyncio.run(go())
    assert seen["token"] == "figd_fake-token"  # noqa: S105 - a fake token for the mock


def _image_available() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", documents.IMAGE], capture_output=True, check=False,  # noqa: S603, S607
                               timeout=30)  # fmt: skip
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


@pytest.fixture(scope="module")
def docs_sandbox() -> DockerSandbox:
    box = DockerSandbox(image=documents.IMAGE)
    if not asyncio.run(box.available()) or not _image_available():
        pytest.skip(f"Docker or the image {documents.IMAGE} is not available")
    return box


def test_word_excel_and_pdf_are_converted_in_the_sandbox(docs_sandbox: DockerSandbox) -> None:
    word = docx(
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Tasas</w:t></w:r></w:p>'
        "<w:p><w:r><w:t>El plazo va de 6 a 60 meses.</w:t></w:r></w:p>"
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Plazo</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Tasa</w:t></w:r></w:p>"
        "</w:tc></w:tr></w:tbl>"
    )
    sheet = xlsx([["Plazo", "Tasa"], ["12", "12.00"]])
    found = asyncio.run(documents.convert(docs_sandbox, [
        ("tasas.docx", word), ("tasas.xlsx", sheet), ("manual.pdf", pdf(["Manual del simulador", "Paso 1"])),
        ("roto.docx", b"PK not a zip"), ("requisitos.md", b"# Requisitos\n"),
    ]))  # fmt: skip
    by = {d.path: d for d in found}
    assert by["docs/tasas.docx"].lines == ["# Tasas", "El plazo va de 6 a 60 meses.", "Plazo | Tasa"]
    assert by["docs/tasas.xlsx"].lines == ["# Sheet: Tasas", "Plazo | Tasa", "12 | 12.00"]
    assert by["docs/manual.pdf"].lines[0] == "# Page 1"
    assert "Manual del simulador" in by["docs/manual.pdf"].text
    assert by["docs/roto.docx"].text == ""
    assert "could not be converted" in by["docs/roto.docx"].warnings[0]
    assert by["docs/requisitos.md"].lines == ["# Requisitos", ""]
    assert [d.path for d in found][-1] == "docs/requisitos.md"  # the order given


def test_xml_with_a_dtd_is_refused(docs_sandbox: DockerSandbox) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", '<!DOCTYPE d [<!ENTITY a "aaaa">]><d>&a;</d>')
    (doc,) = asyncio.run(documents.convert(docs_sandbox, [("dtd.docx", buffer.getvalue())]))
    assert "DTD" in doc.warnings[0]
