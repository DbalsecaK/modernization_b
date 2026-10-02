"""Provider connections of the tenant (spec 12.1). The API key is written to the secrets store once and never
returned; the database keeps only its path (ADR-0007).

An `openai-compatible` connection (ADR-0030) points to a server with the OpenAI chat API (vLLM, Ollama) at its own
base URL, with an optional API key; its models are entered by hand or listed from the server (`<base>/models`)."""

import ipaddress
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from pydantic import Field
from sqlalchemy import delete, exists, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.ai.common import ConfigureModels, gateway_service, require_openrouter
from nexti_api.errors import ProblemError
from nexti_api.projects import services
from nexti_api.schemas import ApiModel
from nexti_core.db.models import (
    EffortMapping,
    ModelOffering,
    ModelProfile,
    PriceVersion,
    ProviderConnection,
    UsageLedger,
)
from nexti_model_gateway.service import OPENAI_COMPATIBLE, LocalModel, Pricing, ServerUnavailableError

router = APIRouter(prefix="/api/v1/ai/connections", tags=["ai"])
Provider = Literal["openrouter", "openai-compatible"]
Capability = Literal["tools", "structured_output", "reasoning", "vision"]


class ConnectionOut(ApiModel):
    id: uuid.UUID
    provider: Provider
    name: str
    base_url: str | None
    status: Literal["untested", "ok", "failed"]
    has_credential: bool
    last_tested_at: datetime | None
    last_test_detail: str | None


class ConnectionCreate(ApiModel):
    provider: Provider = "openrouter"
    name: str = Field(min_length=1, max_length=200)
    # Required for OpenRouter; optional for an openai-compatible server.
    api_key: str | None = Field(default=None, min_length=8, max_length=500)
    # Required for an openai-compatible server, e.g. http://vllm.internal:8000/v1.
    base_url: str | None = Field(default=None, min_length=8, max_length=500)


class ConnectionUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    # Rotating the key: the new one replaces the old in the secrets store.
    api_key: str | None = Field(default=None, min_length=8, max_length=500)
    base_url: str | None = Field(default=None, min_length=8, max_length=500)


class ServedModelOut(ApiModel):
    slug: str
    context_window: int | None


class LocalModelIn(ApiModel):
    """A model the openai-compatible server serves, by its exact id there (e.g. `meta-llama/Llama-3.1-8B-Instruct`)."""

    slug: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    context_window: int | None = Field(default=None, ge=1, le=10_000_000)
    max_output_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    capabilities: list[Capability] = Field(default_factory=list, max_length=4)
    # The tenant declares whether its server retains data (spec 12.6, zero data retention).
    zdr: bool = False
    # USD per million tokens; zero by default (the tenant's own hardware).
    input_per_mtok: Decimal = Field(default=Decimal(0), ge=0, le=100_000)
    output_per_mtok: Decimal = Field(default=Decimal(0), ge=0, le=100_000)


class LocalModelOut(ApiModel):
    offering_id: uuid.UUID
    slug: str


COLUMNS = (
    ProviderConnection.id,
    ProviderConnection.provider,
    ProviderConnection.name,
    ProviderConnection.base_url,
    ProviderConnection.status,
    ProviderConnection.vault_path,
    ProviderConnection.last_tested_at,
    ProviderConnection.last_test_detail,
)


def _out(r: Any) -> ConnectionOut:
    return ConnectionOut(
        id=r.id,
        provider=r.provider,
        name=r.name,
        base_url=r.base_url,
        status=r.status,
        has_credential=r.vault_path is not None,
        last_tested_at=r.last_tested_at,
        last_test_detail=r.last_test_detail,
    )


def _internal(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


async def checked_base_url(request: Request, url: str) -> str:
    """The base URL of an openai-compatible server, without SSRF: https on a public host; private or loopback hosts
    (and http, only there) when the deployment allows them (`model_servers_allow_private_hosts`)."""
    clean = url.strip().rstrip("/")
    parts = urlsplit(clean)
    if (
        parts.scheme not in ("https", "http")
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ProblemError(422, "invalid_base_url", "Use an http(s) URL without credentials, query or fragment.")
    allow_private = bool(request.app.state.settings.model_servers_allow_private_hosts)
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        addresses = await services.services(request).git_resolver(parts.hostname, port)
    except (OSError, ValueError):
        addresses = []
    if not addresses:
        raise ProblemError(422, "host_unresolved", "The host of the base URL cannot be resolved.")
    internal = [_internal(a) for a in addresses]
    if any(internal) and not allow_private:
        raise ProblemError(422, "host_not_allowed", "The host resolves to a private or internal address.")
    if parts.scheme == "http" and not (allow_private and all(internal)):
        raise ProblemError(422, "base_url_not_https", "Plain http is only accepted for private or loopback hosts.")
    return clean


async def _load(conn: AsyncConnection, connection_id: uuid.UUID) -> Any:
    row = (await conn.execute(select(*COLUMNS).where(ProviderConnection.id == connection_id))).one_or_none()
    if row is None:
        raise not_found("connection")
    return row


@router.get("", response_model=list[ConnectionOut])
async def list_connections(request: Request, auth: ConfigureModels) -> list[ConnectionOut]:
    async with transaction(request, auth) as conn:
        rows = (await conn.execute(select(*COLUMNS).order_by(ProviderConnection.name))).all()
    return [_out(r) for r in rows]


@router.post("", response_model=ConnectionOut, status_code=201)
async def create_connection(request: Request, body: ConnectionCreate, auth: ConfigureModels) -> ConnectionOut:
    assert auth.tenant_id is not None  # noqa: S101
    service = gateway_service(request)
    base_url: str | None = None
    if body.provider == OPENAI_COMPATIBLE:
        if not body.base_url:
            raise ProblemError(422, "base_url_required", "An openai-compatible connection needs the server's base URL.")
        base_url = await checked_base_url(request, body.base_url)
    else:
        require_openrouter(request)
        if not body.api_key:
            raise ProblemError(422, "api_key_required", "An OpenRouter connection needs an API key.")
    connection_id = uuid.uuid4()
    path = await service.store_credential(auth.tenant_id, connection_id, body.api_key) if body.api_key else None
    try:
        async with transaction(request, auth) as conn:
            await conn.execute(
                insert(ProviderConnection).values(
                    id=connection_id,
                    tenant_id=auth.tenant_id,
                    provider=body.provider,
                    name=body.name,
                    base_url=base_url,
                    vault_path=path,
                    created_by=auth.user_id,
                )
            )
            await audit(
                conn, auth, "ai.connection_create", f"connection:{connection_id}",
                {"name": body.name, "provider": body.provider, "base_url": base_url},
            )  # fmt: skip
            return _out(await _load(conn, connection_id))
    except IntegrityError as exc:
        if path:
            await service.delete_credential(path)
        raise ProblemError(409, "connection_name_taken", "A connection with that name already exists.") from exc


@router.patch("/{connection_id}", response_model=ConnectionOut)
async def update_connection(
    request: Request, connection_id: uuid.UUID, body: ConnectionUpdate, auth: ConfigureModels
) -> ConnectionOut:
    assert auth.tenant_id is not None  # noqa: S101
    async with transaction(request, auth) as conn:
        row = await _load(conn, connection_id)
        changes: dict[str, object] = {}
        if body.name is not None:
            changes["name"] = body.name
        if body.base_url is not None:
            if row.provider != OPENAI_COMPATIBLE:
                raise ProblemError(422, "base_url_not_applicable", "Only openai-compatible servers have a base URL.")
            changes["base_url"] = await checked_base_url(request, body.base_url)
            changes["status"] = "untested"
        if body.api_key is not None:
            changes["vault_path"] = await gateway_service(request).store_credential(
                auth.tenant_id, connection_id, body.api_key
            )
            changes["status"] = "untested"
        if changes:
            await conn.execute(
                update(ProviderConnection).where(ProviderConnection.id == connection_id).values(**changes)
            )
            await audit(
                conn,
                auth,
                "ai.connection_update",
                f"connection:{connection_id}",
                {
                    "renamed": body.name is not None,
                    "key_rotated": body.api_key is not None,
                    "base_url": changes.get("base_url"),
                },
            )
        return _out(await _load(conn, connection_id))


@router.delete("/{connection_id}", status_code=204)
async def delete_connection(request: Request, connection_id: uuid.UUID, auth: ConfigureModels) -> None:
    async with transaction(request, auth) as conn:
        row = await _load(conn, connection_id)
        used = (await conn.execute(select(ModelProfile.id).where(ModelProfile.connection_id == connection_id))).first()
        if used is not None:
            raise ProblemError(409, "connection_in_use", "Profiles use this connection; change them first.")
        await _release_models(conn, connection_id)
        await conn.execute(delete(ProviderConnection).where(ProviderConnection.id == connection_id))
        await audit(conn, auth, "ai.connection_delete", f"connection:{connection_id}")
    if row.vault_path:
        await gateway_service(request).delete_credential(row.vault_path)


@router.post("/{connection_id}:test", response_model=ConnectionOut)
async def test_connection(request: Request, connection_id: uuid.UUID, auth: ConfigureModels) -> ConnectionOut:
    """Check the stored credential with the provider (no model is called, so it costs nothing). An openai-compatible
    server is asked for its models."""
    async with transaction(request, auth) as conn:
        row = await _load(conn, connection_id)
    if row.provider != OPENAI_COMPATIBLE:
        require_openrouter(request)
    check = await gateway_service(request).check_connection(row.vault_path, row.base_url)
    async with transaction(request, auth) as conn:
        await conn.execute(
            update(ProviderConnection)
            .where(ProviderConnection.id == connection_id)
            .values(
                status="ok" if check.ok else "failed", last_tested_at=datetime.now(UTC), last_test_detail=check.detail
            )
        )
        await audit(
            conn,
            auth,
            "ai.connection_test",
            f"connection:{connection_id}",
            {"ok": check.ok},
            outcome="success" if check.ok else "failure",
        )
        return _out(await _load(conn, connection_id))


async def _release_models(conn: AsyncConnection, connection_id: uuid.UUID) -> None:
    """The connection's own models go with it; those the usage ledger references stay, unavailable and detached, so
    past costs keep their offering and price (spec 13.3)."""
    used = exists().where(UsageLedger.offering_id == ModelOffering.id)
    unused = select(ModelOffering.id).where(ModelOffering.connection_id == connection_id, ~used)
    await conn.execute(delete(EffortMapping).where(EffortMapping.offering_id.in_(unused)))
    await conn.execute(delete(PriceVersion).where(PriceVersion.offering_id.in_(unused)))
    await conn.execute(delete(ModelOffering).where(ModelOffering.id.in_(unused)))
    await conn.execute(
        update(ModelOffering)
        .where(ModelOffering.connection_id == connection_id)
        .values(connection_id=None, status="unavailable", updated_at=datetime.now(UTC))
    )


async def _local(conn: AsyncConnection, connection_id: uuid.UUID) -> Any:
    row = await _load(conn, connection_id)
    if row.provider != OPENAI_COMPATIBLE:
        raise ProblemError(
            422, "not_openai_compatible", "Models are entered by hand only for openai-compatible connections."
        )
    return row


@router.get("/{connection_id}/served-models", response_model=list[ServedModelOut])
async def list_served_models(request: Request, connection_id: uuid.UUID, auth: ConfigureModels) -> list[ServedModelOut]:
    """What the server lists at `<base>/models`, when it does (vLLM and Ollama do)."""
    async with transaction(request, auth) as conn:
        row = await _local(conn, connection_id)
    try:
        models = await gateway_service(request).served_models(row.vault_path, row.base_url)
    except ServerUnavailableError as exc:
        raise ProblemError(502, "model_server_unavailable", exc.detail) from exc
    return [ServedModelOut(slug=m.slug, context_window=m.context_window) for m in models]


@router.post("/{connection_id}/models", response_model=LocalModelOut, status_code=201)
async def add_model(
    request: Request, connection_id: uuid.UUID, body: LocalModelIn, auth: ConfigureModels
) -> LocalModelOut:
    """Add (or refresh) a model of an openai-compatible connection, with the price the tenant declares (zero by
    default). It is visible only to this tenant."""
    assert auth.tenant_id is not None  # noqa: S101
    if "latest" in body.slug:  # fixed versions only (rule 10)
        raise ProblemError(422, "alias_not_allowed", "Only fixed model versions can be used, not aliases.")
    model = LocalModel(
        slug=body.slug,
        name=body.name or body.slug,
        context_window=body.context_window,
        max_output_tokens=body.max_output_tokens,
        capabilities=tuple(sorted(set(body.capabilities))),
        zdr=body.zdr,
        price=Pricing(body.input_per_mtok, body.output_per_mtok),
    )
    service = gateway_service(request)
    async with transaction(request, auth) as conn:
        await _local(conn, connection_id)
        offering_id = await service.add_local_model(conn, auth.tenant_id, connection_id, model, auth.user_id)
        await audit(
            conn, auth, "ai.local_model_add", f"offering:{offering_id}",
            {"connection_id": str(connection_id),
             **body.model_dump(mode="json", include={"slug", "zdr", "input_per_mtok", "output_per_mtok"})},
        )  # fmt: skip
    return LocalModelOut(offering_id=offering_id, slug=body.slug)
