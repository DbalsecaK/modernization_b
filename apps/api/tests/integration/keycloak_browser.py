"""A minimal browser for Keycloak pages over http://localhost: keeps cookies by path, Secure ones included (browsers
treat localhost as a secure context; httpx's cookie jar does not)."""

import html
import json
import re
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


# Hidden fields the platform theme's pages post, read from the page's kcContext (the theme renders with React, so the
# server's HTML has no <form>): the TOTP set-up sends back the secret Keycloak generated.
_KC_HIDDEN = {"kc-totp-settings-form": ("totpSecret",)}


def kc_value(page: str, key: str) -> str | None:
    """A string of the page's kcContext (a JavaScript object, read value by value)."""
    found = re.search(rf'"{re.escape(key)}"\s*:\s*("(?:[^"\\]|\\.)*")', page)
    return str(json.loads(found.group(1))) if found else None


def keycloak_form(page: str, form_id: str) -> tuple[str, dict[str, str]]:
    """Where a Keycloak page posts and its hidden fields: the <form> of Keycloak's own theme (the test identity
    provider) or, for the platform theme (Keycloakify), the kcContext's login action."""
    found = re.search(rf'<form[^>]*id="{form_id}"[^>]*>.*?</form>', page, re.S)
    if found:
        action = html.unescape(re.search(r'action="([^"]+)"', found.group(0)).group(1))  # type: ignore[union-attr]
        fields = {m.group(1): html.unescape(m.group(2))
                  for m in re.finditer(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', found.group(0))}  # fmt: skip
        return action, fields
    login_action = kc_value(page, "loginAction")
    assert login_action, f"no form {form_id} and no kcContext in Keycloak's page (pageId {kc_value(page, 'pageId')})"
    hidden = {name: value for name in _KC_HIDDEN.get(form_id, ()) if (value := kc_value(page, name)) is not None}
    return login_action, hidden


def totp_secret(page: str) -> str:
    """The TOTP secret of the set-up page: Keycloak's manual-mode text, or the kcContext of the platform theme."""
    found = re.search(r'id="kc-totp-secret-key"[^>]*>([^<]+)<', page)
    if found:
        return html.unescape(found.group(1)).strip()
    secret = kc_value(page, "totpSecretEncoded")
    assert secret, f"no TOTP secret in Keycloak's page (pageId {kc_value(page, 'pageId')})"
    return secret
