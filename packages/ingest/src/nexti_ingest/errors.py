"""Outcomes of a validation that are not an acceptance."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Rejection(Exception):
    """The input is not acceptable. `code` is stable (the API returns it); `detail` is safe to show."""

    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


class ScannerUnavailableError(RuntimeError):
    """The malware scanner did not answer: the upload fails closed (ADR-0008)."""
