"""OpenID Connect client for Keycloak: authorization code + PKCE, ID token validation, back-channel logout.

Browser redirects use the public URL of Keycloak; server-to-server calls use the back-channel URL. Both point
to the same realm, and tokens carry the public issuer.
"""

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from nexti_api.settings import Settings

JWKS_TTL_SECONDS = 3600
CLOCK_SKEW_SECONDS = 30


class OidcError(Exception):
    """The provider rejected the exchange or returned something that must not be trusted."""


@dataclass(frozen=True)
class LoginRequest:
    state: str
    nonce: str
    code_verifier: str
    authorization_url: str


@dataclass(frozen=True)
class IdentityClaims:
    sub: str
    email: str | None
    email_verified: bool
    name: str | None


@dataclass(frozen=True)
class TokenSet:
    claims: IdentityClaims
    refresh_token: str | None


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class OidcClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self.settings = settings
        self.http = http
        self._jwks: dict[str, Any] | None = None
        self._jwks_fetched_at = 0.0

    @property
    def redirect_uri(self) -> str:
        return f"{self.settings.web_origin.rstrip('/')}/auth/callback"

    def _endpoint(self, name: str) -> str:
        return f"{self.settings.keycloak_issuer}/protocol/openid-connect/{name}"

    def _client_auth(self) -> dict[str, str]:
        return {
            "client_id": self.settings.oidc_client_id,
            "client_secret": self.settings.oidc_client_secret.get_secret_value(),
        }

    def start_login(self) -> LoginRequest:
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        query = urlencode(
            {
                "client_id": self.settings.oidc_client_id,
                "response_type": "code",
                "scope": "openid email profile",
                "redirect_uri": self.redirect_uri,
                "state": state,
                "nonce": nonce,
                "code_challenge": _pkce_challenge(verifier),
                "code_challenge_method": "S256",
            }
        )
        url = f"{self.settings.keycloak_public_issuer}/protocol/openid-connect/auth?{query}"
        return LoginRequest(state=state, nonce=nonce, code_verifier=verifier, authorization_url=url)

    async def exchange_code(self, code: str, code_verifier: str, nonce: str) -> TokenSet:
        res = await self.http.post(
            self._endpoint("token"),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "code_verifier": code_verifier,
                **self._client_auth(),
            },
        )
        if res.status_code != 200:
            raise OidcError(f"token endpoint answered {res.status_code}")
        body = res.json()
        id_token = body.get("id_token")
        if not isinstance(id_token, str):
            raise OidcError("no id_token in the token response")
        claims = await self.validate_id_token(id_token, nonce)
        refresh = body.get("refresh_token")
        return TokenSet(claims=claims, refresh_token=refresh if isinstance(refresh, str) else None)

    async def _signing_key(self, kid: str | None) -> jwt.PyJWK:
        for force in (False, True):
            if force or self._jwks is None or time.monotonic() - self._jwks_fetched_at > JWKS_TTL_SECONDS:
                res = await self.http.get(self._endpoint("certs"))
                res.raise_for_status()
                self._jwks = res.json()
                self._jwks_fetched_at = time.monotonic()
            assert self._jwks is not None  # noqa: S101 (set just above)
            for key in self._jwks.get("keys", []):
                if key.get("kid") == kid and key.get("use", "sig") == "sig":
                    return jwt.PyJWK(key)
        raise OidcError("the ID token was signed with an unknown key")

    async def validate_id_token(self, id_token: str, nonce: str) -> IdentityClaims:
        try:
            header = jwt.get_unverified_header(id_token)
            key = await self._signing_key(header.get("kid"))
            claims = jwt.decode(
                id_token,
                key=key,
                algorithms=["RS256", "PS256", "ES256"],
                audience=self.settings.oidc_client_id,
                issuer=self.settings.keycloak_public_issuer,
                leeway=CLOCK_SKEW_SECONDS,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise OidcError(f"invalid ID token: {type(exc).__name__}") from exc
        if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise OidcError("ID token nonce does not match")
        azp = claims.get("azp")
        if azp is not None and azp != self.settings.oidc_client_id:
            raise OidcError("ID token was issued to another client")
        email = claims.get("email")
        return IdentityClaims(
            sub=str(claims["sub"]),
            email=str(email).lower() if email else None,
            email_verified=bool(claims.get("email_verified", False)),
            name=claims.get("name") or claims.get("preferred_username"),
        )

    async def logout(self, refresh_token: str) -> bool:
        """End the Keycloak session from the server (the browser is not redirected)."""
        res = await self.http.post(
            self._endpoint("logout"), data={"refresh_token": refresh_token, **self._client_auth()}
        )
        return res.status_code in (200, 204)
