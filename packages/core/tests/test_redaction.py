"""Credentials never reach the activity panel, the errors of invocations or the exported JSON (spec 18.8). The
test values are built in memory so no credential-looking literal lives in the repository."""

from nexti_core.redaction import REDACTED, redact, redact_text

FAKE = "Zx" * 12  # 24 harmless characters


def test_provider_keys_and_tokens_are_redacted() -> None:
    samples = [
        "sk-or-v1-" + FAKE,
        "ghp_" + FAKE * 2,
        "AKIA" + "Q" * 16,
        "Bearer " + FAKE,
        "eyJ" + FAKE + "." + FAKE + "." + FAKE,
    ]
    for sample in samples:
        text = redact_text(f"call failed with {sample} at step 3")
        assert sample not in text
        assert REDACTED in text
        assert text.startswith("call failed with ")


def test_url_credentials_keep_the_user_and_the_host() -> None:
    url = "postgresql://platform_app:" + FAKE + "@db.internal:5432/platform"
    assert redact_text(url) == f"postgresql://platform_app:{REDACTED}@db.internal:5432/platform"


def test_assignments_of_credentials_are_redacted() -> None:
    text = redact_text(f'password={FAKE}; api_key: "{FAKE}" user=ana')
    assert FAKE not in text
    assert "user=ana" in text


def test_nested_payloads_are_redacted_by_value_and_by_key() -> None:
    payload = {
        "error": {"message": f"401 for token {FAKE}", "authorization": "x"},
        "items": [f"sk-or-v1-{FAKE}", 3, None],
        "apiKey": FAKE,
        "phase": "generation",
    }
    clean = redact(payload)
    assert FAKE not in str(clean)
    assert clean["apiKey"] == REDACTED
    assert clean["error"]["authorization"] == REDACTED
    assert clean["items"][1:] == [3, None]
    assert clean["phase"] == "generation"


def test_ordinary_text_is_untouched() -> None:
    text = "Generation of module_a: corrected and verified (2 attempts, 1 passed)"
    assert redact_text(text) == text
