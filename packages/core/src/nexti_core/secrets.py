"""The secrets store (Vault KV v2 API; OpenBao in development, ADR-0007).

This is the only module that talks to the secrets store. Provider credentials are used only by the model gateway
(`nexti_model_gateway.secrets` adds their paths); a project's Git token is written and read by the repository module
of the API. The database keeps only the path.
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


def repository_path(tenant_id: uuid.UUID, project_id: uuid.UUID) -> str:
    """Where the Git token of a project lives."""
    return f"tenants/{tenant_id}/repositories/{project_id}"


def legacy_path(tenant_id: uuid.UUID, project_id: uuid.UUID) -> str:
    """Where the credentials of the system a project's legacy runs on live (ADR-0052): a JSON {user, password}."""
    return f"tenants/{tenant_id}/legacy/{project_id}"


def integration_path(tenant_id: uuid.UUID, integration_id: uuid.UUID) -> str:
    """Where the token of a tenant integration (Figma, Jira, Azure DevOps) lives (ADR-0018)."""
    return f"tenants/{tenant_id}/integrations/{integration_id}"


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
