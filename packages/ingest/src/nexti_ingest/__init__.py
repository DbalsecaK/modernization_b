"""Validation of untrusted inputs before they are stored (spec 7.1, 15.4; ADR-0008)."""

from nexti_ingest.errors import Rejection, ScannerUnavailableError
from nexti_ingest.limits import Limits
from nexti_ingest.links import Link, figma_link, prototype_link
from nexti_ingest.scanner import ClamdScanner, ScanResult
from nexti_ingest.validate import KINDS, Accepted, safe_name, validate

__all__ = [
    "KINDS",
    "Accepted",
    "ClamdScanner",
    "Limits",
    "Link",
    "Rejection",
    "ScanResult",
    "ScannerUnavailableError",
    "figma_link",
    "prototype_link",
    "safe_name",
    "validate",
]
