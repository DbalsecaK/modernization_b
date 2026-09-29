"""The Git repository check (spec 7.1, 15.4): no SSRF (https only, no internal addresses, no redirects), and the
branch is read from the smart-HTTP ref advertisement. The Git server is simulated; the resolver is injected."""

from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from nexti_ingest import Rejection
from nexti_ingest.git import check_repository, validate_repository_url

REPO = "https://git.bank.example/cards/card-system.git"
PUBLIC_IP = "203.0.113.10"  # documentation range, treated as public only through the injected resolver


def pkt(line: str) -> bytes:
    data = line.encode() + b"\n"
    return f"{len(data) + 4:04x}".encode() + data


ADVERTISEMENT = (
    pkt("# service=git-upload-pack")
    + b"0000"
    + pkt("1111111111111111111111111111111111111111 HEAD\0multi_ack symref=HEAD:refs/heads/main")
    + pkt("1111111111111111111111111111111111111111 refs/heads/main")
    + pkt("2222222222222222222222222222222222222222 refs/heads/release/2026.09")
    + pkt("3333333333333333333333333333333333333333 refs/tags/v1.0")
    + b"0000"
)


def resolver_to(*addresses: str):  # type: ignore[no-untyped-def]
    async def resolve(host: str, port: int) -> list[str]:
        return list(addresses)

    return resolve


# Global documentation ranges are "not global" for ipaddress; the check treats them as public here by patching.
@pytest.fixture(autouse=True)
def documentation_range_is_public(monkeypatch: pytest.MonkeyPatch) -> None:
    import nexti_ingest.git as git

    original = git._forbidden
    monkeypatch.setattr(git, "_forbidden", lambda a: False if a == PUBLIC_IP else original(a))


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


async def test_a_reachable_repository_lists_its_branches(http: httpx.AsyncClient) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(f"{REPO}/info/refs", params={"service": "git-upload-pack"}).respond(
            200, content=ADVERTISEMENT, headers={"content-type": "application/x-git-upload-pack-advertisement"}
        )
        check = await check_repository(REPO, "main", "tok3n", http, resolver_to(PUBLIC_IP))
    assert check.ok
    assert check.branches == ["main", "release/2026.09"]
    # The token goes in the Authorization header, never in the URL.
    assert route.calls.last.request.headers["authorization"].startswith("Basic ")
    assert "tok3n" not in str(route.calls.last.request.url)


async def test_a_missing_branch_is_reported(http: httpx.AsyncClient) -> None:
    with respx.mock() as router:
        router.get(f"{REPO}/info/refs").respond(
            200, content=ADVERTISEMENT, headers={"content-type": "application/x-git-upload-pack-advertisement"}
        )
        check = await check_repository(REPO, "develop", None, http, resolver_to(PUBLIC_IP))
    assert not check.ok
    assert "develop" in check.detail


@pytest.mark.parametrize(
    ("status", "text"), [(401, "credentials"), (403, "credentials"), (404, "not found"), (302, "redirect")]
)
async def test_failures_are_explained(http: httpx.AsyncClient, status: int, text: str) -> None:
    with respx.mock() as router:
        router.get(f"{REPO}/info/refs").respond(status, headers={"location": "http://169.254.169.254/"})
        check = await check_repository(REPO, "main", None, http, resolver_to(PUBLIC_IP))
    assert not check.ok
    assert text in check.detail


async def test_an_html_page_is_not_a_repository(http: httpx.AsyncClient) -> None:
    with respx.mock() as router:
        router.get(f"{REPO}/info/refs").respond(200, text="<html>login</html>", headers={"content-type": "text/html"})
        check = await check_repository(REPO, "main", None, http, resolver_to(PUBLIC_IP))
    assert not check.ok


@pytest.mark.parametrize(
    "address",
    ["10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.10", "::1", "fd00::1", "::ffff:10.0.0.1", "0.0.0.0"],  # noqa: S104
)
async def test_hosts_that_resolve_to_internal_addresses_are_refused(http: httpx.AsyncClient, address: str) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{REPO}/info/refs").respond(200)
        with pytest.raises(Rejection) as caught:
            await check_repository(REPO, "main", None, http, resolver_to(PUBLIC_IP, address))
    assert caught.value.code == "repository_host_not_allowed"
    assert not route.called  # refused before any request


@pytest.mark.parametrize(
    "url",
    [
        "http://git.bank.example/cards/card-system.git",
        "ssh://git@git.bank.example/cards.git",
        "https://user:secret@git.bank.example/cards.git",
        "https://git.bank.example/cards.git?x=1",
        "file:///etc/passwd",
    ],
)
def test_repository_urls_that_are_not_accepted(url: str) -> None:
    with pytest.raises(Rejection) as caught:
        validate_repository_url(url)
    assert caught.value.code == "invalid_repository_url"


async def test_an_unresolvable_host_is_a_failed_check(http: httpx.AsyncClient) -> None:
    async def fail(host: str, port: int) -> list[str]:
        raise OSError("no such host")

    check = await check_repository(REPO, "main", None, http, fail)
    assert not check.ok
    assert "resolved" in check.detail
