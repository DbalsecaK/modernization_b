import pytest

from nexti_api.auth.routes import safe_return_path


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/projects/p1?tab=spec", "/projects/p1?tab=spec"),
        ("/", "/"),
        (None, "/"),
        ("", "/"),
        ("https://evil.example/", "/"),
        ("//evil.example/x", "/"),
        (r"/\evil.example", "/"),
        ("projects", "/"),
        ("/redirect?to=https://evil.example", "/"),
    ],
)
def test_return_path_only_allows_same_origin_paths(value: str | None, expected: str) -> None:
    assert safe_return_path(value) == expected
