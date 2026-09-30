"""The gateway as the rest of the platform sees it. The API and, in M3, the workers use only this facade: they
never touch the provider client or the secrets store directly (test in apps/api/tests/test_architecture.py)."""

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from nexti_model_gateway import catalog
from nexti_model_gateway.cassettes import MissingRecordingError, Mode, RecordingClient
from nexti_model_gateway.gateway import CallContext, Completion, ModelGateway
from nexti_model_gateway.openrouter import BASE_URL, OpenRouterClient, Pricing, ProviderError
from nexti_model_gateway.secrets import SecretsConfig, SecretStore, connection_path

__all__ = ["ConnectionCheck", "GatewayService", "MissingRecordingError", "Pricing", "SecretsConfig"]


@dataclass(frozen=True)
class ConnectionCheck:
    ok: bool
    detail: str


class GatewayService:
    def __init__(
        self,
        engine: AsyncEngine,
        http: httpx.AsyncClient,
        secrets: SecretsConfig,
        openrouter_url: str | None = None,
        *,
        cassettes: tuple[Path, Mode] | None = None,
    ) -> None:
        """`cassettes` (development and test only, ADR-0012): a folder of recorded responses and the mode."""
        self._secrets = SecretStore(secrets, http)
        client = OpenRouterClient(http, openrouter_url or BASE_URL)
        self._client = RecordingClient(client, *cassettes) if cassettes else client
        self.gateway = ModelGateway(engine, self._secrets, self._client)

    async def complete(self, ctx: CallContext, messages: list[dict[str, Any]], **extra: Any) -> Completion:
        return await self.gateway.complete(ctx, messages, **extra)

    # Credentials: written once, never read back outside the gateway (ADR-0007).
    async def store_credential(self, tenant_id: uuid.UUID, connection_id: uuid.UUID, api_key: str) -> str:
        path = connection_path(tenant_id, connection_id)
        await self._secrets.put(path, api_key)
        return path

    async def delete_credential(self, path: str) -> None:
        await self._secrets.delete(path)

    async def check_connection(self, path: str | None) -> ConnectionCheck:
        """Validate the stored key with the provider without calling a model (free)."""
        api_key = await self._secrets.get(path) if path else None
        if not api_key:
            return ConnectionCheck(False, "No credential is stored for this connection.")
        try:
            info = await self._client.key_info(api_key)
        except ProviderError as exc:
            return ConnectionCheck(False, f"The provider rejected the credential ({exc.status}).")
        except httpx.HTTPError as exc:
            return ConnectionCheck(False, f"The provider could not be reached ({type(exc).__name__}).")
        remaining = info.get("limit_remaining")
        limit = "no spending limit" if remaining is None else f"{remaining} USD of limit remaining"
        tier = "free tier" if info.get("is_free_tier") else "paid account"
        return ConnectionCheck(True, f"Credential accepted: {tier}, {limit}.")

    async def secrets_healthy(self) -> bool:
        try:
            return await self._secrets.healthy()
        except httpx.HTTPError:
            return False

    # Catalog (global data from the provider).
    async def sync_catalog(self, conn: AsyncConnection) -> catalog.SyncReport:
        return await catalog.sync_catalog(conn, self._client)

    async def load_offerings(self, conn: AsyncConnection, version_id: uuid.UUID) -> int:
        return await catalog.load_offerings(conn, self._client, version_id)

    @staticmethod
    async def record_manual_price(
        conn: AsyncConnection, offering_id: uuid.UUID, price: Pricing, by: uuid.UUID
    ) -> uuid.UUID:
        return await catalog.record_price(conn, offering_id, price, "manual", by)
