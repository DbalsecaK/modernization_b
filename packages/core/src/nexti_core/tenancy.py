"""Tenancy identifiers and supported languages (spec 14.1 and 18.6)."""

from typing import Literal, NewType, get_args
from uuid import UUID

TenantId = NewType("TenantId", UUID)
UserId = NewType("UserId", UUID)
ProjectId = NewType("ProjectId", UUID)

# English is the native language of the platform; Spanish is a full translation.
Language = Literal["en", "es"]
SUPPORTED_LANGUAGES: tuple[Language, ...] = get_args(Language)
DEFAULT_LANGUAGE: Language = "en"


def parse_language(value: str | None) -> Language:
    """Return a supported language, falling back to English for anything unknown."""
    for language in SUPPORTED_LANGUAGES:
        if value == language:
            return language
    return DEFAULT_LANGUAGE
