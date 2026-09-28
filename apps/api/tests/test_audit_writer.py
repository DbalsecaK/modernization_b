import pytest

from nexti_api.audit.writer import _reject_secrets


@pytest.mark.parametrize(
    "details",
    [
        {"password": "x"},
        {"user": {"refresh_token": "x"}},
        {"items": [{"clientSecret": "x"}]},
        {"note": "Bearer eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxIn0.sig"},
        {"session_cookie": "abc"},
    ],
)
def test_credentials_are_refused(details: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="cannot be logged"):
        _reject_secrets(details)


def test_ordinary_details_are_accepted() -> None:
    _reject_secrets({"role": "architect", "project": "p1", "changes": [{"field": "status", "to": "active"}]})
