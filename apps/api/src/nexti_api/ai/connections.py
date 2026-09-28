"""Provider connections of the tenant (spec 12.1). The API key is written to the secrets store once and never
returned; the database keeps only its path (ADR-0007)."""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import Field
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.ai.common import ConfigureModels, gateway_service
from nexti_api.errors import ProblemError
from nexti_api.schemas import ApiModel
from nexti_core.db.models import ModelProfile, ProviderConnection

router = APIRouter(prefix="/api/v1/ai/connections", tags=["ai"])


class ConnectionOut(ApiModel):
    id: uuid.UUID
    provider: Literal["openrouter"]
    name: str
    status: Literal["untested", "ok", "failed"]
    has_credential: bool
    last_tested_at: datetime | None
    last_test_detail: str | None


class ConnectionCreate(ApiModel):
    provider: Literal["openrouter"] = "openrouter"
    name: str = Field(min_length=1, max_length=200)
    api_key: str = Field(min_length=8, max_length=500)


class ConnectionUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    # Rotating the key: the new one replaces the old in the secrets store.
    api_key: str | None = Field(default=None, min_length=8, max_length=500)


COLUMNS = (
    ProviderConnection.id,
    ProviderConnection.provider,
    ProviderConnection.name,
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
        status=r.status,
        has_credential=r.vault_path is not None,
        last_tested_at=r.last_tested_at,
        last_test_detail=r.last_test_detail,
    )


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
    connection_id = uuid.uuid4()
    path = await service.store_credential(auth.tenant_id, connection_id, body.api_key)
    try:
        async with transaction(request, auth) as conn:
            await conn.execute(
                insert(ProviderConnection).values(
                    id=connection_id,
                    tenant_id=auth.tenant_id,
                    provider=body.provider,
                    name=body.name,
                    vault_path=path,
                    created_by=auth.user_id,
                )
            )
            await audit(conn, auth, "ai.connection_create", f"connection:{connection_id}", {"name": body.name})
            return _out(await _load(conn, connection_id))
    except IntegrityError as exc:
        await service.delete_credential(path)
        raise ProblemError(409, "connection_name_taken", "A connection with that name already exists.") from exc


@router.patch("/{connection_id}", response_model=ConnectionOut)
async def update_connection(
    request: Request, connection_id: uuid.UUID, body: ConnectionUpdate, auth: ConfigureModels
) -> ConnectionOut:
    assert auth.tenant_id is not None  # noqa: S101
    async with transaction(request, auth) as conn:
        await _load(conn, connection_id)
        changes: dict[str, object] = {}
        if body.name is not None:
            changes["name"] = body.name
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
                {"renamed": body.name is not None, "key_rotated": body.api_key is not None},
            )
        return _out(await _load(conn, connection_id))


@router.delete("/{connection_id}", status_code=204)
async def delete_connection(request: Request, connection_id: uuid.UUID, auth: ConfigureModels) -> None:
    async with transaction(request, auth) as conn:
        row = await _load(conn, connection_id)
        used = (await conn.execute(select(ModelProfile.id).where(ModelProfile.connection_id == connection_id))).first()
        if used is not None:
            raise ProblemError(409, "connection_in_use", "Profiles use this connection; change them first.")
        await conn.execute(delete(ProviderConnection).where(ProviderConnection.id == connection_id))
        await audit(conn, auth, "ai.connection_delete", f"connection:{connection_id}")
    if row.vault_path:
        await gateway_service(request).delete_credential(row.vault_path)


@router.post("/{connection_id}:test", response_model=ConnectionOut)
async def test_connection(request: Request, connection_id: uuid.UUID, auth: ConfigureModels) -> ConnectionOut:
    """Check the stored credential with the provider (no model is called, so it costs nothing)."""
    async with transaction(request, auth) as conn:
        row = await _load(conn, connection_id)
    check = await gateway_service(request).check_connection(row.vault_path)
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
