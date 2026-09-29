"""Services the input endpoints need, built once at startup from the settings (object store, malware scanner and the
validation limits). Missing configuration leaves them as None and the endpoints answer 503 (fail closed)."""

from dataclasses import dataclass

from fastapi import Request

from nexti_api.errors import ProblemError
from nexti_api.settings import Settings
from nexti_core.object_store import ObjectStore, ObjectStoreConfig
from nexti_ingest import ClamdScanner, Limits
from nexti_ingest.git import Resolver, resolve

MB = 1024 * 1024


@dataclass
class InputServices:
    store: ObjectStore | None
    scanner: ClamdScanner | None
    limits: Limits
    # Replaceable in tests, where the Git server is simulated.
    git_resolver: Resolver = resolve


def build(settings: Settings) -> InputServices:
    store = (
        ObjectStore(
            ObjectStoreConfig(
                settings.object_store_url,
                settings.object_store_access_key,
                settings.object_store_secret_key.get_secret_value(),
                settings.object_store_bucket,
            )
        )
        if settings.object_store_url
        else None
    )
    scanner = (
        ClamdScanner(settings.malware_scanner_host, settings.malware_scanner_port)
        if settings.malware_scanner_host
        else None
    )
    limits = Limits(
        max_archive_bytes=settings.max_archive_mb * MB,
        max_document_bytes=settings.max_document_mb * MB,
        max_screenshot_bytes=settings.max_screenshot_mb * MB,
    )
    return InputServices(store, scanner, limits)


def services(request: Request) -> InputServices:
    found: InputServices | None = getattr(request.app.state, "inputs", None)
    if found is None:
        raise ProblemError(503, "inputs_unavailable", "Input storage is not configured.")
    return found


def store(request: Request) -> ObjectStore:
    found = services(request).store
    if found is None:
        raise ProblemError(503, "inputs_unavailable", "Input storage is not configured.")
    return found


def scanner(request: Request) -> ClamdScanner:
    found = services(request).scanner
    if found is None:
        raise ProblemError(503, "malware_scanner_unavailable", "The malware scanner is not configured.")
    return found
