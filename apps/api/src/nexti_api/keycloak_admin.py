"""Keycloak Admin REST API with the least-privilege service account `nexti-admin` (spec 15.1).

M0 uses it to create invited accounts (Keycloak e-mails the password set-up) and to read events. M0b (ADR-0022) adds
the Organization of each tenant and its identity providers.
"""

import time
from dataclasses import dataclass
from typing import Any

import httpx

from nexti_api.settings import Settings

# The invitee sets a password and proves the e-mail is theirs through the link Keycloak sends.
INVITATION_ACTIONS = ["UPDATE_PASSWORD", "VERIFY_EMAIL"]


class KeycloakAdminError(RuntimeError):
    pass


@dataclass(frozen=True)
class KeycloakUser:
    id: str
    email: str
    required_actions: tuple[str, ...]


class KeycloakAdmin:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self.settings = settings
        self.http = http
        self.base = f"{settings.keycloak_url.rstrip('/')}/admin/realms/{settings.keycloak_realm}"
        self._token = ""
        self._expires = 0.0

    async def _headers(self) -> dict[str, str]:
        if time.monotonic() >= self._expires:
            res = await self.http.post(
                f"{self.settings.keycloak_issuer}/protocol/openid-connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.settings.keycloak_admin_client_id,
                    "client_secret": self.settings.keycloak_admin_client_secret.get_secret_value(),
                },
            )
            if res.status_code != 200:
                raise KeycloakAdminError(f"service account token: {res.status_code}")
            body = res.json()
            self._token = body["access_token"]
            self._expires = time.monotonic() + max(10, int(body.get("expires_in", 60)) - 30)
        return {"Authorization": f"Bearer {self._token}"}

    async def _request(self, method: str, path: str, ok: tuple[int, ...] = (404,), **kwargs: Any) -> httpx.Response:
        res = await self.http.request(method, f"{self.base}{path}", headers=await self._headers(), **kwargs)
        if res.status_code >= 400 and res.status_code not in ok:
            raise KeycloakAdminError(f"{method} {path}: {res.status_code} {_reason(res)}")
        return res

    async def find_user(self, email: str) -> KeycloakUser | None:
        res = await self._request(
            "GET", "/users", params={"email": email, "exact": "true", "briefRepresentation": "false"}
        )
        for u in res.json():
            if str(u.get("email", "")).lower() == email.lower():
                return KeycloakUser(u["id"], u["email"], tuple(u.get("requiredActions", [])))
        return None

    async def create_user(self, email: str, first_name: str | None = None) -> KeycloakUser:
        body: dict[str, Any] = {
            "username": email,
            "email": email,
            "enabled": True,
            "emailVerified": False,
            "requiredActions": INVITATION_ACTIONS,
        }
        if first_name:
            body["firstName"] = first_name
        await self._request("POST", "/users", json=body)
        created = await self.find_user(email)
        if created is None:
            raise KeycloakAdminError("the user was created but cannot be found")
        return created

    async def send_invitation_email(self, user_id: str, lifespan_seconds: int) -> None:
        await self._request(
            "PUT",
            f"/users/{user_id}/execute-actions-email",
            params={"lifespan": lifespan_seconds},
            json=INVITATION_ACTIONS,
        )

    async def events(self, *, admin: bool, first: int, max_results: int, date_from: str) -> list[dict[str, Any]]:
        path = "/admin-events" if admin else "/events"
        res = await self._request("GET", path, params={"first": first, "max": max_results, "dateFrom": date_from})
        data: list[dict[str, Any]] = res.json()
        return data

    # -- Organizations (ADR-0022): one per tenant, its alias is the tenant's slug -----------------------------------
    async def find_organization(self, alias: str, known_id: str | None = None) -> dict[str, Any] | None:
        """By the id the platform keeps, else by alias (Keycloak's search looks at names and domains, not aliases)."""
        if known_id:
            res = await self._request("GET", f"/organizations/{known_id}")
            if res.status_code == 200 and res.json().get("alias") == alias:
                return res.json()  # type: ignore[no-any-return]
        first = 0
        while True:
            page: list[dict[str, Any]] = (
                await self._request("GET", "/organizations", params={"first": first, "max": 100})
            ).json()  # fmt: skip
            found = next((o for o in page if o.get("alias") == alias), None)
            if found is not None or len(page) < 100:
                return found
            first += 100

    async def save_organization(self, alias: str, name: str, domains: list[str], known_id: str | None = None) -> str:
        """Creates or updates the Organization; returns its id."""
        body: dict[str, Any] = {"name": name, "alias": alias, "enabled": True,
                                "domains": [{"name": d} for d in sorted(set(domains))]}  # fmt: skip
        current = await self.find_organization(alias, known_id)
        if current is None:
            res = await self._request("POST", "/organizations", json=body)
            return str(res.headers["location"]).rstrip("/").rsplit("/", 1)[1]
        await self._request("PUT", f"/organizations/{current['id']}", json={**current, **body})
        return str(current["id"])

    async def add_organization_member(self, organization_id: str, user_id: str) -> None:
        await self._request("POST", f"/organizations/{organization_id}/members", ok=(409,), json=user_id)

    async def organization_members(self, organization_id: str) -> set[str]:
        res = await self._request("GET", f"/organizations/{organization_id}/members", params={"max": 1000})
        return {m["id"] for m in res.json()} if res.status_code == 200 else set()

    # -- Identity providers (ADR-0022): the secret is sent to Keycloak and never read back -------------------------
    async def identity_provider(self, alias: str) -> dict[str, Any] | None:
        res = await self._request("GET", f"/identity-provider/instances/{alias}")
        return res.json() if res.status_code == 200 else None

    async def save_identity_provider(self, representation: dict[str, Any], mappers: list[dict[str, Any]]) -> None:
        alias = representation["alias"]
        if await self.identity_provider(alias) is None:
            await self._request("POST", "/identity-provider/instances", json=representation)
        else:
            await self._request("PUT", f"/identity-provider/instances/{alias}", json=representation)
        current = (await self._request("GET", f"/identity-provider/instances/{alias}/mappers")).json()
        for mapper in current:
            await self._request("DELETE", f"/identity-provider/instances/{alias}/mappers/{mapper['id']}")
        for mapper in mappers:
            await self._request("POST", f"/identity-provider/instances/{alias}/mappers",
                                json={**mapper, "identityProviderAlias": alias})  # fmt: skip

    async def delete_identity_provider(self, alias: str) -> None:
        await self._request("DELETE", f"/identity-provider/instances/{alias}")

    async def link_identity_provider(self, organization_id: str, alias: str) -> None:
        await self._request("POST", f"/organizations/{organization_id}/identity-providers", ok=(409,), json=alias)

    async def import_saml_metadata(self, metadata_url: str) -> dict[str, str]:
        """Keycloak reads the SAML metadata of the provider and returns the configuration it implies."""
        res = await self._request("POST", "/identity-provider/import-config",
                                  json={"providerId": "saml", "fromUrl": metadata_url})  # fmt: skip
        return {str(k): str(v) for k, v in res.json().items()}


def _reason(res: httpx.Response) -> str:
    """Keycloak's short error message, if any (never a request body)."""
    try:
        body = res.json()
    except ValueError:
        return ""
    if isinstance(body, dict):
        return str(body.get("errorMessage") or body.get("error") or "")[:200]
    return ""
