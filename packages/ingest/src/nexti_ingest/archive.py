"""Zip archives are hostile input (spec 15.4): every entry is checked from the central directory and then really
decompressed with caps, because the sizes a zip declares can lie."""

import io
import stat
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import BinaryIO

from nexti_ingest.errors import Rejection
from nexti_ingest.limits import Limits
from nexti_ingest.secrets import SecretFindings

CHUNK = 64 * 1024
# Text we look into for credentials (configuration and source code of the legacy stacks).
TEXT_SUFFIXES = {
    ".cbl", ".cob", ".cpy", ".jcl", ".bms", ".mac", ".asm", ".sql", ".sp", ".prc", ".cs", ".vb", ".aspx", ".ascx",
    ".master", ".config", ".xml", ".json", ".properties", ".yaml", ".yml", ".ini", ".env", ".txt", ".md", ".java",
    ".js", ".ts", ".py", ".sh", ".bat", ".ps1", ".cfg", ".conf",
}  # fmt: skip


@dataclass(frozen=True)
class ArchiveReport:
    entries: int
    uncompressed_bytes: int


def unsafe_path(name: str) -> str | None:
    """Why an entry name could escape the extraction folder, or None if it is safe."""
    if "\x00" in name:
        return "contains a NUL byte"
    if "\\" in name:
        return "uses backslashes"
    if name.startswith("/"):
        return "is an absolute path"
    if len(name) >= 2 and name[1] == ":":
        return "starts with a drive letter"
    if ".." in PurePosixPath(name).parts:
        return "goes up with '..'"
    return None


def inspect_zip(stream: BinaryIO, limits: Limits, findings: SecretFindings | None = None) -> ArchiveReport:
    stream.seek(0)
    try:
        archive = zipfile.ZipFile(stream)
    except zipfile.BadZipFile as exc:
        raise Rejection("corrupt_archive", "The file is not a readable zip archive.") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > limits.max_entries:
            raise Rejection("too_many_entries", f"The archive has more than {limits.max_entries} entries.")
        for info in infos:
            reason = unsafe_path(info.filename)
            if reason:
                raise Rejection("path_traversal", f"The entry {info.filename!r} {reason}.")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise Rejection("symlink", f"The entry {info.filename!r} is a symbolic link.")
            if info.flag_bits & 0x1:
                raise Rejection("encrypted_entry", f"The entry {info.filename!r} is encrypted and cannot be checked.")
        total = 0
        for info in infos:
            if info.is_dir():
                continue
            scan_text = findings is not None and PurePosixPath(info.filename).suffix.lower() in TEXT_SUFFIXES
            kept = bytearray()
            entry_bytes = 0
            try:
                with archive.open(info) as member:
                    while chunk := member.read(CHUNK):
                        entry_bytes += len(chunk)
                        total += len(chunk)
                        if total > limits.max_uncompressed_bytes:
                            raise Rejection(
                                "archive_too_large",
                                f"The archive expands beyond {limits.max_uncompressed_bytes // (1024 * 1024)} MB.",
                            )
                        compressed = max(info.compress_size, 1)
                        if entry_bytes > 1024 * 1024 and entry_bytes / compressed > limits.max_compression_ratio:
                            raise Rejection(
                                "compression_bomb",
                                f"The entry {info.filename!r} expands more than {limits.max_compression_ratio} times.",
                            )
                        if scan_text and len(kept) < limits.max_scanned_text_bytes:
                            kept += chunk[: limits.max_scanned_text_bytes - len(kept)]
            except (zipfile.BadZipFile, EOFError, ValueError, NotImplementedError) as exc:
                raise Rejection("corrupt_archive", f"The entry {info.filename!r} cannot be read.") from exc
            if scan_text and findings is not None:
                findings.scan(bytes(kept), info.filename)
    stream.seek(0)
    return ArchiveReport(entries=len(infos), uncompressed_bytes=total)


# The legacy code the pipeline reads from an accepted archive (already inspected at upload by `inspect_zip`): Sybase
# procedures (M4), BMS maps (M5), COBOL programs, copybooks, CICS definitions and traces (M6), ASP.NET WebForms pages,
# code-behind and configuration (M8); each source adapter adds its languages.
SOURCE_SUFFIXES = (".sp", ".sql", ".prc", ".proc", ".tsql", ".syb", ".txt", ".bms", ".cbl", ".cob", ".cobol", ".cpy",
                   ".copy", ".csd", ".json", ".aspx", ".ascx", ".master", ".cs", ".config")  # fmt: skip
MAX_SOURCE_FILE_BYTES = 5 * 1024 * 1024
MAX_SOURCE_TOTAL_BYTES = 50 * 1024 * 1024


def read_text_files(data: bytes, prefix: str = "") -> list[tuple[str, str]]:
    """(path, text) of the source files of an accepted archive, with size caps; binary entries are skipped."""
    files: list[tuple[str, str]] = []
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if info.is_dir() or not name.lower().endswith(SOURCE_SUFFIXES) or info.file_size > MAX_SOURCE_FILE_BYTES:
                continue
            total += info.file_size
            if total > MAX_SOURCE_TOTAL_BYTES:
                break
            raw = archive.read(info)
            if b"\x00" in raw[:4096]:
                continue
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                content = raw.decode("latin-1")
            files.append((f"{prefix}{name}", content.replace("\r\n", "\n")))
    return files


MAX_TARGET_TOTAL_BYTES = 200 * 1024 * 1024


def read_all_files(data: bytes) -> dict[str, bytes]:
    """Every file of an accepted archive, binary included (a third party's target with its jars, ADR-0025)."""
    files: dict[str, bytes] = {}
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if info.is_dir() or unsafe_path(name):
                continue
            total += info.file_size
            if total > MAX_TARGET_TOTAL_BYTES:
                raise ValueError("the archive is larger than the target limit")
            files[name] = archive.read(info)
    return files
