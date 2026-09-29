"""Limits of the validation (configurable per deployment)."""

from dataclasses import dataclass

MB = 1024 * 1024


@dataclass(frozen=True)
class Limits:
    # Size of the uploaded file, per kind of input.
    max_archive_bytes: int = 200 * MB
    max_document_bytes: int = 25 * MB
    max_screenshot_bytes: int = 10 * MB
    # Archives (the code zip and Office documents, which are zips too).
    max_entries: int = 50_000
    max_uncompressed_bytes: int = 2_000 * MB
    max_compression_ratio: int = 200
    # Images: the header decides; nothing is decoded beyond it.
    max_image_pixels: int = 40_000_000
    max_image_side: int = 16_384
    # Secret counting only reads text entries up to this size.
    max_scanned_text_bytes: int = 2 * MB

    def max_bytes(self, kind: str) -> int:
        return {
            "source_archive": self.max_archive_bytes,
            "document": self.max_document_bytes,
            "screenshot": self.max_screenshot_bytes,
        }[kind]
