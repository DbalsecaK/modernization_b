"""The one validation every uploaded file goes through before it is stored (spec 7.1, 15.4; ADR-0008): size, type
by content, archive or image structure, secrets, malware and hash, in that order. A screenshot uploaded from the
wizard and one added later from the Inputs tab take exactly the same path."""

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Protocol

from nexti_ingest.archive import inspect_zip
from nexti_ingest.errors import Rejection
from nexti_ingest.image import inspect_image
from nexti_ingest.limits import Limits
from nexti_ingest.scanner import ScanResult
from nexti_ingest.secrets import SecretFindings
from nexti_ingest.sniff import ALLOWED, DOCX, MARKDOWN, TEXT, XLSX, ZIP, sniff

KINDS = tuple(ALLOWED)


class Scanner(Protocol):
    async def scan(self, stream: BinaryIO) -> ScanResult: ...


@dataclass(frozen=True)
class Accepted:
    content_type: str
    size_bytes: int
    sha256: str
    findings: dict[str, Any] = field(default_factory=dict)


def safe_name(filename: str) -> str:
    """The logical name of an upload: the last path component, without control characters, at most 255 long."""
    base = re.split(r"[\\/]", filename or "")[-1]
    base = "".join(c for c in unicodedata.normalize("NFC", base) if unicodedata.category(c)[0] != "C").strip()
    return base[:255] or "unnamed"


def _size(stream: BinaryIO) -> int:
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(0)
    return size


def _sha256(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    stream.seek(0)
    while chunk := stream.read(64 * 1024):
        digest.update(chunk)
    stream.seek(0)
    return digest.hexdigest()


async def validate(stream: BinaryIO, filename: str, kind: str, limits: Limits, scanner: Scanner) -> Accepted:
    """Accept the file or raise Rejection. ScannerUnavailableError propagates: the caller fails closed."""
    if kind not in ALLOWED:
        raise Rejection("unknown_kind", f"Unknown kind of input: {kind}.")
    size = _size(stream)
    if size == 0:
        raise Rejection("empty_file", "The file is empty.")
    if size > limits.max_bytes(kind):
        raise Rejection("file_too_large", f"The file is larger than {limits.max_bytes(kind) // (1024 * 1024)} MB.")
    content_type = sniff(stream, filename)
    if content_type is None or content_type not in ALLOWED[kind]:
        raise Rejection("type_not_allowed", "The content of the file is not an accepted type for this input.")

    findings: dict[str, Any] = {}
    secrets = SecretFindings()
    if content_type in (ZIP, DOCX, XLSX):
        report = inspect_zip(stream, limits, secrets if content_type == ZIP else None)
        findings["archive"] = {"entries": report.entries, "uncompressed_bytes": report.uncompressed_bytes}
    elif content_type in ALLOWED["screenshot"]:
        image = inspect_image(stream, content_type, limits)
        findings["image"] = {"width": image.width, "height": image.height}
    elif content_type in (TEXT, MARKDOWN):
        secrets.scan(stream.read(limits.max_scanned_text_bytes), safe_name(filename))
        stream.seek(0)
    if secrets.counts:
        findings["secrets"] = secrets.summary()

    result = await scanner.scan(stream)
    if not result.clean:
        raise Rejection("malware_detected", f"The malware scanner flagged the file ({result.signature}).")
    return Accepted(content_type=content_type, size_bytes=size, sha256=_sha256(stream), findings=findings)
