"""Checking a project's Git repository without SSRF (spec 7.1, 15.4): only https, no host that resolves to a private,
loopback, link-local or reserved address, no redirects, and the smart-HTTP `info/refs` endpoint read with httpx (the
`git` binary never runs on the API). Cloning happens in the preflight of the pipeline (M3), inside the sandbox.

Residual risk, documented: the name is resolved again by the HTTP client after the check (DNS rebinding). The
sandbox of M3 has no route to internal networks, which closes it for the clone itself.
"""

import asyncio
import base64
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from nexti_ingest.errors import Rejection

Resolver = Callable[[str, int], Awaitable[list[str]]]
MAX_ADVERTISEMENT = 5 * 1024 * 1024


async def resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def _forbidden(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or not ip.is_global
    )


async def ensure_public_host(url: str, resolver: Resolver = resolve, allow_private_hosts: bool = False) -> None:
    """A tool the platform calls on behalf of a tenant (Jira, Azure DevOps) must be https on a public host: never an
    internal address (SSRF). Raises Rejection otherwise."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise Rejection("invalid_url", "Only https URLs without credentials are accepted.")
    try:
        addresses = await resolver(parts.hostname, parts.port or 443)
    except OSError:
        raise Rejection("host_unresolved", "The host cannot be resolved.") from None
    if not addresses:
        raise Rejection("host_unresolved", "The host cannot be resolved.")
    if not allow_private_hosts and any(_forbidden(a) for a in addresses):
        raise Rejection("host_not_allowed", "The host resolves to a private or internal address.")


def validate_repository_url(url: str) -> str:
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise Rejection("invalid_repository_url", "Only https repository URLs are accepted.")
    if parts.username or parts.password:
        raise Rejection("invalid_repository_url", "Put the token in its own field, not in the URL.")
    if not parts.hostname or parts.query or parts.fragment:
        raise Rejection("invalid_repository_url", "The repository URL is not valid.")
    if len(url) > 500:
        raise Rejection("invalid_repository_url", "The repository URL is too long.")
    return url.rstrip("/")


@dataclass(frozen=True)
class GitCheck:
    ok: bool
    detail: str
    branches: list[str] = field(default_factory=list)
    default_branch_found: bool = False


def _branches(advertisement: bytes) -> list[str]:
    """refs/heads/* from a pkt-line ref advertisement."""
    out = []
    i = 0
    while i + 4 <= len(advertisement):
        try:
            length = int(advertisement[i : i + 4], 16)
        except ValueError:
            break
        if length == 0:
            i += 4
            continue
        line = advertisement[i + 4 : i + length].split(b"\0", 1)[0].strip()
        i += length
        parts = line.split(b" ", 1)
        if len(parts) == 2 and parts[1].startswith(b"refs/heads/"):
            out.append(parts[1].removeprefix(b"refs/heads/").decode("utf-8", errors="replace"))
    return sorted(out)


async def check_repository(
    url: str,
    branch: str,
    token: str | None,
    http: httpx.AsyncClient,
    resolver: Resolver = resolve,
    allow_private_hosts: bool = False,
) -> GitCheck:
    """Can the platform read the repository with this token, and does the branch exist? Raises Rejection for URLs
    that are not allowed; network and authorization failures are a GitCheck with ok=False."""
    url = validate_repository_url(url)
    parts = urlsplit(url)
    host = parts.hostname or ""
    try:
        addresses = await resolver(host, parts.port or 443)
    except OSError:
        return GitCheck(False, "The repository host cannot be resolved.")
    if not addresses:
        return GitCheck(False, "The repository host cannot be resolved.")
    if not allow_private_hosts and any(_forbidden(a) for a in addresses):
        raise Rejection("repository_host_not_allowed", "The repository host resolves to a private or internal address.")

    headers = {"User-Agent": "nexti-platform", "Git-Protocol": "version=1"}
    if token:
        headers["Authorization"] = "Basic " + base64.b64encode(f"nexti:{token}".encode()).decode()
    try:
        res = await http.get(
            f"{url}/info/refs", params={"service": "git-upload-pack"}, headers=headers, follow_redirects=False,
            timeout=15,
        )  # fmt: skip
    except httpx.HTTPError as exc:
        return GitCheck(False, f"The repository could not be reached ({type(exc).__name__}).")
    if 300 <= res.status_code < 400:
        return GitCheck(False, "The repository answered with a redirect, which is not followed; use the final URL.")
    if res.status_code in (401, 403):
        return GitCheck(False, "The repository rejected the credentials (or they are needed).")
    if res.status_code == 404:
        return GitCheck(False, "The repository was not found.")
    content_type = res.headers.get("content-type", "")
    if res.status_code != 200 or "git-upload-pack-advertisement" not in content_type:
        return GitCheck(False, f"The URL does not answer as a Git repository ({res.status_code}).")
    branches = _branches(res.content[:MAX_ADVERTISEMENT])
    found = branch in branches
    detail = (
        f"Repository reachable; branch {branch!r} found."
        if found
        else f"Repository reachable, but {branch!r} is missing."
    )
    return GitCheck(found, detail, branches[:200], found)
