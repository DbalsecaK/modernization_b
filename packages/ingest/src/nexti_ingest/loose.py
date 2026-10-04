"""Loose code files as a code input: one or more source files (a stored procedure, a few COBOL programs) are packed
into a zip here, so they go through exactly the same validation as an uploaded archive (size, zip safety, secrets,
malware) and the rest of the platform keeps reading one archive per input."""

import io
import tempfile
import zipfile
from collections.abc import Sequence
from typing import BinaryIO

from nexti_ingest.archive import SOURCE_SUFFIXES, TEXT_SUFFIXES, unsafe_path
from nexti_ingest.errors import Rejection
from nexti_ingest.limits import Limits

CODE_KINDS = ("source_archive", "target_archive")
# Text files a code input may bring loose: the legacy stacks, the targets and their build and configuration files.
CODE_SUFFIXES = frozenset(TEXT_SUFFIXES) | frozenset(SOURCE_SUFFIXES) | {
    ".go", ".mod", ".sum", ".kt", ".kts", ".gradle", ".csproj", ".sln", ".vbproj", ".cshtml", ".razor", ".tsx",
    ".jsx", ".html", ".css", ".scss", ".mjs", ".cjs", ".tf", ".pli", ".rpg", ".cl", ".copy", ".cobol",
}  # fmt: skip
SPOOL_BYTES = 8 * 1024 * 1024


def is_zip(stream: BinaryIO) -> bool:
    start = stream.tell()
    head = stream.read(4)
    stream.seek(start)
    return head in (b"PK\x03\x04", b"PK\x05\x06")


def archive_name(names: Sequence[str]) -> str:
    """The input's name: the file's own name for one file (re-uploading it makes a new version), else the first one
    and how many more."""
    return names[0] if len(names) == 1 else f"{names[0]} (+{len(names) - 1}).zip"


def pack(files: Sequence[tuple[str, BinaryIO]], limits: Limits, kind: str = "source_archive") -> BinaryIO:
    """A zip with the loose files at its root. Refused: a name that is not a plain file name, a repeated name, a
    suffix that is not code, binary content, or more than the archive limit."""
    if not files:
        raise Rejection("no_files", "Choose at least one file.")
    seen: set[str] = set()
    total = 0
    out = tempfile.SpooledTemporaryFile(max_size=SPOOL_BYTES)  # noqa: SIM115 - returned open to the caller
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, stream in files:
            if not name or "/" in name or unsafe_path(name):
                raise Rejection("unsafe_name", f"{name!r} is not a plain file name.")
            if name.lower() in seen:
                raise Rejection("duplicate_file", f"{name} was chosen twice.")
            seen.add(name.lower())
            suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if suffix not in CODE_SUFFIXES:
                raise Rejection("unsupported_code_file", f"{name} is not a code file this input accepts "
                                "(upload a zip for other files).")  # fmt: skip
            data = stream.read(limits.max_bytes(kind) + 1)
            total += len(data)
            if total > limits.max_bytes(kind):
                raise Rejection("too_large", "The files are larger than the limit of a code input.")
            if b"\x00" in data[:8192]:
                raise Rejection("binary_file", f"{name} is not a text file.")
            archive.writestr(name, data)
    out.seek(0)
    return out  # type: ignore[return-value]


def as_upload(files: Sequence[tuple[str, BinaryIO]], limits: Limits, kind: str) -> tuple[BinaryIO, str]:
    """What a code input stores for what was chosen: a single zip as it came; loose files packed. Returns the stream
    and the input's name."""
    names = [name for name, _ in files]
    if len(files) == 1 and is_zip(files[0][1]):
        return files[0][1], names[0]
    if any(is_zip(stream) for _, stream in files):
        raise Rejection("mixed_upload", "Upload either one zip or loose code files, not both.")
    packed = pack(files, limits, kind)
    return packed, archive_name(names)


def read_back(stream: BinaryIO) -> list[str]:
    """The names inside a packed upload (tests and logs)."""
    data = stream.read()
    stream.seek(0)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.namelist()
