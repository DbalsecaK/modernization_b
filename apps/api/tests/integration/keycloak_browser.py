"""A minimal browser for Keycloak pages over http://localhost: keeps cookies by path, Secure ones included (browsers
treat localhost as a secure context; httpx's cookie jar does not)."""

from http.cookies import SimpleCookie
from urllib.parse import urljoin, urlsplit

import httpx


class Browser:
    def __init__(self) -> None:
        self.client = httpx.Client(follow_redirects=False, timeout=30)
        self.cookies: dict[tuple[str, str, str], str] = {}  # (host, path, name) -> value

    def _header(self, url: str) -> str:
        parts = urlsplit(url)
        found = sorted(
            ((p, n, v) for (h, p, n), v in self.cookies.items() if h == parts.netloc and parts.path.startswith(p)),
            key=lambda c: -len(c[0]),
        )
        seen: dict[str, str] = {}
        for _, name, value in found:
            seen.setdefault(name, value)
        return "; ".join(f"{n}={v}" for n, v in seen.items())

    def _store(self, response: httpx.Response) -> None:
        host = response.url.netloc.decode() if isinstance(response.url.netloc, bytes) else response.url.netloc
        for raw in response.headers.get_list("set-cookie"):
            cookie = SimpleCookie()
            cookie.load(raw)
            for name, morsel in cookie.items():
                path = morsel["path"] or "/"
                if morsel["max-age"] == "0" or not morsel.value:
                    self.cookies.pop((host, path, name), None)
                else:
                    self.cookies[(host, path, name)] = morsel.value

    def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}) or {})  # type: ignore[call-overload]
        if cookie := self._header(url):
            headers["Cookie"] = cookie
        response = self.client.request(method, url, headers=headers, **kwargs)  # type: ignore[arg-type]
        self._store(response)
        return response

    def get(self, url: str, **kwargs: object) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def follow(self, response: httpx.Response, stop: str) -> httpx.Response:
        """Follows redirects until a page or a redirect to `stop` (the application's callback)."""
        while response.is_redirect:
            location = urljoin(str(response.url), response.headers["location"])
            if location.startswith(stop):
                return response
            response = self.get(location)
        return response

    def __enter__(self) -> "Browser":
        return self

    def __exit__(self, *_: object) -> None:
        self.client.close()
