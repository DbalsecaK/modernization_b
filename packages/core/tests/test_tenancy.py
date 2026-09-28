import pytest

from nexti_core.tenancy import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, parse_language


def test_english_is_the_default_language() -> None:
    assert DEFAULT_LANGUAGE == "en"
    assert SUPPORTED_LANGUAGES == ("en", "es")


@pytest.mark.parametrize(("value", "expected"), [("en", "en"), ("es", "es"), ("fr", "en"), (None, "en"), ("", "en")])
def test_parse_language_falls_back_to_english(value: str | None, expected: str) -> None:
    assert parse_language(value) == expected
