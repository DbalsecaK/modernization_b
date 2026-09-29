"""UI references given as links (spec 7.1, 18.3): Figma links must be figma.com/file|design|proto; prototype links
are any https page. Links are only stored in M2: nothing fetches them yet (Figma API reading arrives in M7)."""

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from nexti_ingest.errors import Rejection

MAX_URL = 2000
FIGMA_HOSTS = {"figma.com", "www.figma.com"}
FIGMA_PATH = re.compile(r"^/(file|design|proto)/([A-Za-z0-9]{10,64})(?:/([^/?#]*))?")


@dataclass(frozen=True)
class Link:
    url: str
    name: str


def _common(url: str) -> tuple[str, str, str]:
    url = url.strip()
    if len(url) > MAX_URL:
        raise Rejection("url_too_long", f"The link is longer than {MAX_URL} characters.")
    if any(ord(c) < 32 for c in url):
        raise Rejection("invalid_url", "The link contains control characters.")
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise Rejection("invalid_url", "Only https links are accepted.")
    if parts.username or parts.password:
        raise Rejection("invalid_url", "Links with credentials are not accepted.")
    host = (parts.hostname or "").lower()
    if not host or "." not in host:
        raise Rejection("invalid_url", "The link has no valid host.")
    return url, host, parts.path


def figma_link(url: str) -> Link:
    url, host, path = _common(url)
    match = FIGMA_PATH.match(path)
    if host not in FIGMA_HOSTS or not match:
        raise Rejection("invalid_figma_link", "A Figma link must be figma.com/file/…, /design/… or /proto/….")
    kind, key, title = match.groups()
    name = unquote(title).replace("-", " ").strip() if title else f"Figma {kind} {key}"
    return Link(url, name[:255] or f"Figma {kind} {key}")


def prototype_link(url: str) -> Link:
    url, host, path = _common(url)
    return Link(url, f"{host}{path}"[:255].rstrip("/") or host)
