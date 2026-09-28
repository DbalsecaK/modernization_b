"""Provider credentials in the secrets store (Vault KV v2 API; OpenBao in development, ADR-0007).

This is the only module that writes or reads provider credentials. The database keeps only the path.
"""

import uuid
from dataclasses import dataclass

import httpx


class SecretsError(RuntimeError):
    pass


@dataclass(frozen=True)
class SecretsConfig:
    url: str
    token: str
    mount: str = "secret"
    prefix: str = "nexti"


def connection_path(tenant_id: uuid.UUID, connection_id: uuid.UUID) -> str:
    """Where a connection's credential lives: one path per tenant and connection."""
    return f"tenants/{tenant_id}/connections/{connection_id}"


class SecretStore:
    def __init__(self, config: SecretsConfig, http: httpx.AsyncClient) -> None:
        self.config = config
        self.http = http

    def _url(self, kind: str, path: str) -> str:
        return f"{self.config.url.rstrip('/')}/v1/{self.config.mount}/{kind}/{self.config.prefix}/{path}"

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-Vault-Token": self.config.token}

    async def put(self, path: str, value: str) -> None:
        res = await self.http.post(self._url("data", path), json={"data": {"value": value}}, headers=self._headers)
        if res.status_code not in (200, 204):
            raise SecretsError(f"secrets store write failed: {res.status_code}")

    async def get(self, path: str) -> str | None:
        res = await self.http.get(self._url("data", path), headers=self._headers)
        if res.status_code == 404:
            return None
        if res.status_code != 200:
            raise SecretsError(f"secrets store read failed: {res.status_code}")
        value = res.json().get("data", {}).get("data", {}).get("value")
        return str(value) if value is not None else None

    async def delete(self, path: str) -> None:
        """Delete every version of the secret."""
        res = await self.http.delete(self._url("metadata", path), headers=self._headers)
        if res.status_code not in (200, 204, 404):
            raise SecretsError(f"secrets store delete failed: {res.status_code}")

    async def healthy(self) -> bool:
        res = await self.http.get(f"{self.config.url.rstrip('/')}/v1/sys/health")
        return res.status_code == 200
