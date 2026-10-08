"""Validation of untrusted inputs (spec 15.4, M2 acceptance): path traversal, symlinks, zip bombs, fake types,
oversized images, Figma links, secrets and malware (EICAR against the real ClamAV of docker compose)."""

import io
import os
import stat
import struct
import zipfile
import zlib
from typing import BinaryIO

import pytest
from PIL import Image

from nexti_ingest import (
    ClamdScanner,
    Limits,
    Rejection,
    ScannerUnavailableError,
    ScanResult,
    figma_link,
    prototype_link,
    safe_name,
    validate,
)
from nexti_ingest.archive import unsafe_path

LIMITS = Limits(max_uncompressed_bytes=20 * 1024 * 1024, max_compression_ratio=100)
# The EICAR test signature, reversed so that no antivirus quarantines this source file; it only exists in memory.
EICAR = "*H+H$!ELIF-TSET-SURIVITNA-DRADNATS-RACIE$}7)CC7)^P(45XZP\\4[PA@%P!O5X"[::-1].encode()
CLAMD_HOST = os.environ.get("CLAMAV_HOST", "127.0.0.1")
CLAMD_PORT = int(os.environ.get("CLAMAV_PORT", "3310"))


class CleanScanner:
    """Stands in for ClamAV where the test is about the structure checks, not about malware."""

    def __init__(self) -> None:
        self.scanned = 0

    async def scan(self, stream: BinaryIO) -> ScanResult:
        self.scanned += 1
        return ScanResult(True)


def zip_bytes(entries: dict[str, bytes], infos: list[zipfile.ZipInfo] | None = None) -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
        for info in infos or []:
            archive.writestr(info, b"target")
    buffer.seek(0)
    return buffer


def png_bytes(width: int = 64, height: int = 32) -> io.BytesIO:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, "PNG")
    buffer.seek(0)
    return buffer


def png_header_only(width: int, height: int) -> io.BytesIO:
    """A PNG whose header declares huge dimensions (no pixel data needed to be dangerous)."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    data = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + chunk + struct.pack(">I", zlib.crc32(chunk))
    iend = b"IEND"
    data += struct.pack(">I", 0) + iend + struct.pack(">I", zlib.crc32(iend))
    return io.BytesIO(data)


async def rejected(stream: BinaryIO, name: str, kind: str, limits: Limits = LIMITS) -> Rejection:
    with pytest.raises(Rejection) as caught:
        await validate(stream, name, kind, limits, CleanScanner())
    return caught.value


async def test_a_clean_code_zip_is_accepted_with_hash_and_stats() -> None:
    stream = zip_bytes({"src/CARD01.cbl": b"       IDENTIFICATION DIVISION.\n", "maps/CARDM.bms": b"CARDM DFHMSD\n"})
    scanner = CleanScanner()
    accepted = await validate(stream, "card-system.zip", "source_archive", LIMITS, scanner)
    assert accepted.content_type == "application/zip"
    assert len(accepted.sha256) == 64
    assert accepted.findings["archive"]["entries"] == 2
    assert "secrets" not in accepted.findings
    assert scanner.scanned == 1


async def test_a_target_archive_follows_the_rules_of_the_source_archive() -> None:
    # Flow 4 (ADR-0025): the third party's code and its runnable jar, a zip like the legacy code.
    stream = zip_bytes({"src/main/java/App.java": b"class App {}\n", "target/app.jar": b"PK\x03\x04jar"})
    accepted = await validate(stream, "third-party.zip", "target_archive", LIMITS, CleanScanner())
    assert accepted.content_type == "application/zip"
    assert LIMITS.max_bytes("target_archive") == LIMITS.max_bytes("source_archive")
    pdf = io.BytesIO(b"%PDF-1.7\n1 0 obj\n")
    assert (await rejected(pdf, "target.pdf", "target_archive")).code == "type_not_allowed"


@pytest.mark.parametrize(
    "entry",
    ["../../etc/passwd", "src/../../escape.cbl", "/etc/cron.d/job", "C:/Windows/evil.dll", "src\\..\\evil.cbl"],
)
async def test_a_zip_with_path_traversal_is_rejected(entry: str) -> None:
    stream = zip_bytes({"ok.cbl": b"ok", entry: b"evil"})
    assert (await rejected(stream, "legacy.zip", "source_archive")).code == "path_traversal"


def test_safe_entry_names_pass() -> None:
    assert unsafe_path("src/programs/CARD01.cbl") is None
    assert unsafe_path("dir.with.dots/..hidden-file") is None


async def test_a_zip_with_a_symbolic_link_is_rejected() -> None:
    link = zipfile.ZipInfo("src/link-to-etc")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    stream = zip_bytes({"ok.cbl": b"ok"}, [link])
    assert (await rejected(stream, "legacy.zip", "source_archive")).code == "symlink"


async def test_a_compression_bomb_is_rejected() -> None:
    stream = zip_bytes({"zeros.bin": b"\0" * (8 * 1024 * 1024)})  # ~8 KB compressed: ratio ~1000
    assert (await rejected(stream, "legacy.zip", "source_archive")).code == "compression_bomb"


async def test_an_archive_that_expands_beyond_the_limit_is_rejected() -> None:
    random_part = os.urandom(3 * 1024 * 1024)  # incompressible, so the ratio check does not fire first
    stream = zip_bytes({f"part{i}.bin": random_part for i in range(8)})
    limits = Limits(max_uncompressed_bytes=10 * 1024 * 1024)
    assert (await rejected(stream, "legacy.zip", "source_archive", limits)).code == "archive_too_large"


async def test_too_many_entries_are_rejected() -> None:
    stream = zip_bytes({f"f{i}.txt": b"x" for i in range(30)})
    assert (await rejected(stream, "legacy.zip", "source_archive", Limits(max_entries=20))).code == "too_many_entries"


async def test_an_encrypted_entry_is_rejected() -> None:
    buffer = zip_bytes({"secret.cbl": b"x"})
    raw = bytearray(buffer.getvalue())
    # Set the "encrypted" flag in both the local header and the central directory entry.
    raw[6] |= 0x1
    central = raw.find(b"PK\x01\x02")
    raw[central + 8] |= 0x1
    assert (await rejected(io.BytesIO(bytes(raw)), "legacy.zip", "source_archive")).code == "encrypted_entry"


async def test_a_file_whose_content_does_not_match_the_kind_is_rejected() -> None:
    assert (await rejected(png_bytes(), "legacy.zip", "source_archive")).code == "type_not_allowed"
    assert (await rejected(io.BytesIO(b"\x7fELF\x02\x01\x01\x00" + b"\0" * 64), "shot.png", "screenshot")).code == (
        "type_not_allowed"
    )
    # A text file renamed to .png is still text: not a screenshot.
    assert (await rejected(io.BytesIO(b"just some text"), "fake.png", "screenshot")).code == "type_not_allowed"


async def test_a_screenshot_is_accepted_with_its_dimensions() -> None:
    accepted = await validate(png_bytes(640, 480), "login.png", "screenshot", LIMITS, CleanScanner())
    assert accepted.content_type == "image/png"
    assert accepted.findings["image"] == {"width": 640, "height": 480}


async def test_a_screenshot_declaring_too_many_pixels_is_rejected() -> None:
    assert (await rejected(png_header_only(60_000, 60_000), "huge.png", "screenshot")).code == "image_too_large"


async def test_a_truncated_image_is_rejected() -> None:
    data = png_bytes().getvalue()
    assert (await rejected(io.BytesIO(data[: len(data) // 2]), "cut.png", "screenshot")).code == "corrupt_image"


async def test_size_limits_by_kind() -> None:
    limits = Limits(max_screenshot_bytes=100)
    assert (await rejected(png_bytes(200, 200), "big.png", "screenshot", limits)).code == "file_too_large"
    assert (await rejected(io.BytesIO(b""), "empty.pdf", "document")).code == "empty_file"


async def test_documents_by_content() -> None:
    pdf = io.BytesIO(b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n")
    assert (await validate(pdf, "manual.pdf", "document", LIMITS, CleanScanner())).content_type == "application/pdf"
    docx = zip_bytes({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w:document/>"})
    accepted = await validate(docx, "spec.docx", "document", LIMITS, CleanScanner())
    assert accepted.content_type.endswith("wordprocessingml.document")
    md = io.BytesIO("# User stories\n\nAs a teller… ".encode())
    assert (await validate(md, "stories.md", "document", LIMITS, CleanScanner())).content_type == "text/markdown"
    # A plain zip of code is not a document.
    assert (await rejected(zip_bytes({"a.cbl": b"x"}), "code.zip", "document")).code == "type_not_allowed"


async def test_credentials_in_the_code_are_counted_but_never_reported() -> None:
    config = b'<add name="db" connectionString="Server=db;User Id=sa;Password=Sup3rS3cret;" />\n'
    key = b"aws_key = 'AKIA" + b"ABCDEFGHIJKLMNOP'\n"
    stream = zip_bytes({"web.config": config, "deploy/settings.ini": key, "CARD01.cbl": b"MOVE 1 TO X."})
    accepted = await validate(stream, "legacy.zip", "source_archive", LIMITS, CleanScanner())
    secrets = accepted.findings["secrets"]
    assert secrets["total"] == 2
    assert secrets["by_rule"] == {"aws_access_key": 1, "connection_string_password": 1}
    assert secrets["files"] == ["web.config", "deploy/settings.ini"]
    assert "Sup3rS3cret" not in repr(accepted.findings)


def test_upload_names_keep_only_the_file_name() -> None:
    assert safe_name("../../etc/passwd") == "passwd"
    assert safe_name("C:\\Users\\x\\card system.zip") == "card system.zip"
    assert safe_name("evil\x00name\x1f.zip") == "evilname.zip"
    assert safe_name("") == "unnamed"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.figma.com/file/AbCdEf1234567890/Card-Management",
        "https://figma.com/design/AbCdEf1234567890/Onboarding?node-id=1-2",
        "https://www.figma.com/proto/AbCdEf1234567890/Flow",
    ],
)
def test_figma_links_that_are_accepted(url: str) -> None:
    assert figma_link(url).url == url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.figma.com/community/file/1234567890",  # not file|design|proto at the root
        "https://www.figma.com/files/recent",
        "https://figma.com.evil.example/file/AbCdEf1234567890/x",
        "https://evil.example/figma.com/file/AbCdEf1234567890/x",
        "http://www.figma.com/file/AbCdEf1234567890/x",  # not https
        "https://user:pass@www.figma.com/file/AbCdEf1234567890/x",
        "javascript:alert(1)//figma.com/file/AbCdEf1234567890",
        "https://www.figma.com/file/short/x",
    ],
)
def test_figma_links_that_are_rejected(url: str) -> None:
    with pytest.raises(Rejection) as caught:
        figma_link(url)
    assert caught.value.code in {"invalid_figma_link", "invalid_url"}


def test_prototype_links() -> None:
    assert prototype_link("https://proto.andesbank.example/cards/v2").name == "proto.andesbank.example/cards/v2"
    for bad in ("ftp://proto.example/x", "data:text/html,<script>", "https://localhost-without-dot/"):
        with pytest.raises(Rejection):
            prototype_link(bad)


# --- Malware, against the real ClamAV (docker compose). ----------------------------------------------------------


async def _clamd() -> ClamdScanner:
    scanner = ClamdScanner(CLAMD_HOST, CLAMD_PORT, timeout_seconds=30)
    try:
        if await scanner.ping():
            return scanner
    except ScannerUnavailableError:
        pass
    pytest.skip("ClamAV is not running (docker compose up clamav)")


async def test_clamav_flags_the_eicar_test_file() -> None:
    scanner = await _clamd()
    result = await scanner.scan_chunks([EICAR])
    assert not result.clean
    assert "Eicar" in (result.signature or "")
    assert (await scanner.scan_chunks([b"MOVE ZERO TO WS-TOTAL."])).clean


async def test_malware_inside_an_upload_is_rejected_by_the_same_pipeline() -> None:
    scanner = await _clamd()
    for stream, name, kind in (
        (io.BytesIO(EICAR), "notes.txt", "document"),
        (zip_bytes({"src/readme.txt": EICAR}), "legacy.zip", "source_archive"),
    ):
        with pytest.raises(Rejection) as caught:
            await validate(stream, name, kind, LIMITS, scanner)
        assert caught.value.code == "malware_detected"
    # A clean screenshot goes through the same scanner and is accepted.
    assert (await validate(png_bytes(), "login.png", "screenshot", LIMITS, scanner)).content_type == "image/png"


async def test_without_the_scanner_the_upload_fails_closed() -> None:
    scanner = ClamdScanner("127.0.0.1", 1, timeout_seconds=2)  # nothing listens on port 1
    with pytest.raises(ScannerUnavailableError):
        await validate(png_bytes(), "login.png", "screenshot", LIMITS, scanner)


def test_the_source_of_an_ibm_i_archive_is_read() -> None:
    # ADR-0051: RPG programs, their DDS and the CL reach the source adapter (an accepted zip read none of them).
    from nexti_ingest.archive import read_text_files

    names = ["qrpglesrc/ACTSALDO.rpgle", "qrpgsrc/CALCINT.rpg", "qrpglesrc/VALCTA.sqlrpgle", "qddssrc/CUENTAS.pf",
             "qddssrc/CUENTASL1.lf", "qddssrc/CONSCTAD.dspf", "qddssrc/REPINT.prtf", "qclsrc/CIERRE.clle"]  # fmt: skip
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, "     A          R RECORD\n")
    assert [path for path, _ in read_text_files(buffer.getvalue())] == names


def test_a_target_archive_is_read_whole_with_its_binaries() -> None:
    from nexti_ingest.archive import read_all_files

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("app/Main.java", "class Main {}")
        archive.writestr("lib/app.jar", b"PK\x03\x04\x00binary")
        archive.writestr("app/", "")
    assert read_all_files(buffer.getvalue()) == {
        "app/Main.java": b"class Main {}",
        "lib/app.jar": b"PK\x03\x04\x00binary",
    }
