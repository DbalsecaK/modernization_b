"""The real type of a file from its content, never from its name or the declared content type."""

import zipfile
from typing import BinaryIO

ZIP = "application/zip"
PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PNG = "image/png"
JPEG = "image/jpeg"
WEBP = "image/webp"
TEXT = "text/plain"
MARKDOWN = "text/markdown"

# What each kind of input may be.
ALLOWED = {
    "source_archive": {ZIP},
    "document": {PDF, DOCX, XLSX, TEXT, MARKDOWN},
    "screenshot": {PNG, JPEG, WEBP},
}


def _is_text(sample: bytes) -> bool:
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError as exc:
        # A multi-byte character cut at the end of the sample is still text.
        return exc.start >= len(sample) - 3
    return True


def sniff(stream: BinaryIO, filename: str) -> str | None:
    """The content type, or None when it is none of the accepted types."""
    stream.seek(0)
    head = stream.read(4096)
    stream.seek(0)
    if head.startswith(b"%PDF-"):
        return PDF
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if head.startswith(b"\xff\xd8\xff"):
        return JPEG
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return WEBP
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        try:
            with zipfile.ZipFile(stream) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile:
            return None
        finally:
            stream.seek(0)
        if "[Content_Types].xml" in names and "word/document.xml" in names:
            return DOCX
        if "[Content_Types].xml" in names and "xl/workbook.xml" in names:
            return XLSX
        return ZIP
    if head and _is_text(head):
        return MARKDOWN if filename.lower().endswith((".md", ".markdown")) else TEXT
    return None
