"""/scim/v2: the SCIM 2.0 endpoint of each tenant (spec 13, ADR-0031).

The customer's identity provider authenticates with the tenant's bearer (Administration -> Authentication). Only its
SHA-256 digest is stored; the tenant it belongs to is the RLS scope of every operation, so a provider reaches its own
tenant and no other. These routes have no session and no OpenFGA check: the bearer is their authorization, and it can
only manage the tenant's users and groups. Every change is audited (actor `system`, label `scim`).
"""

import hashlib
import hmac
import json
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.audit import AuditEvent, record
from nexti_api.authz.sync import authz_change
from nexti_api.observability import log
from nexti_api.scim import protocol, service
from nexti_api.scim.protocol import ScimError
from nexti_api.scim.service import Scim
from nexti_api.settings import Settings
from nexti_core.db.models import ScimGroup, ScimUser
from nexti_core.db.session import DbScope, scoped_connection

PREFIX = "/scim/v2"
MAX_BODY = 1_000_000
router = APIRouter(prefix=PREFIX, tags=["scim"])


def scim_base(settings: Settings) -> str:
    """The public URL of the endpoint (through the web origin, like the sign-in callback)."""
    return f"{settings.web_origin.rstrip('/')}{PREFIX}"


def digest(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def _engine(request: Request) -> Any:
    engine = request.app.state.resources.engine
    if engine is None:
        raise ScimError(503, "The database is not configured.")
    return engine


async def scim_auth(request: Request) -> Scim:
    """The tenant of the bearer; 401 for a missing, unknown or revoked one (always the same answer)."""
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    value = value.strip()
    if scheme.lower() != "bearer" or not value or len(value) > 200:
        raise ScimError(401, "A valid SCIM bearer is required.")
    presented = digest(value)
    async with scoped_connection(_engine(request), DbScope()) as conn:
        row = (await conn.execute(text("SELECT * FROM scim_access_tenant(:d)"), {"d": presented})).first()
    if row is None or not hmac.compare_digest(bytes(row.access_digest), presented):
        log.warning("scim_unauthorized")
        raise ScimError(401, "A valid SCIM bearer is required.")
    state = request.app.state
    return Scim(tenant_id=row.tenant_id, access_id=row.access_id, base=scim_base(state.settings),
                admin=getattr(state, "keycloak_admin", None), sessions=getattr(state, "sessions", None))  # fmt: skip


ScimAuth = Annotated[Scim, Depends(scim_auth)]


@asynccontextmanager
async def transaction(request: Request, scim: Scim) -> AsyncIterator[AsyncConnection]:
    """A transaction scoped to the bearer's tenant; wakes the OpenFGA relay after commit."""
    async with scoped_connection(_engine(request), DbScope(tenant_id=scim.tenant_id)) as conn:
        await conn.execute(
            text("UPDATE scim_access SET last_used_at = now() WHERE id = :i "
                 "AND (last_used_at IS NULL OR last_used_at < now() - interval '1 minute')"),
            {"i": scim.access_id},
        )  # fmt: skip
        yield conn
    relay = getattr(request.app.state, "relay", None)
    if relay is not None:
        relay.wake()


async def audit(conn: AsyncConnection, scim: Scim, action: str, target: str, details: Mapping[str, Any]) -> None:
    await record(conn, AuditEvent(action=action, outcome="success", actor_kind="system", actor_label="scim",
                                  tenant_id=scim.tenant_id, target=target,
                                  details={"access": str(scim.access_id), **details}))  # fmt: skip


async def _body(request: Request) -> Any:
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        raise ScimError(413, "The request is too large.", "tooMany")
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise ScimError(413, "The request is too large.", "tooMany")
    try:
        return json.loads(raw)
    except ValueError:
        raise ScimError(400, "The body is not valid JSON.", "invalidSyntax") from None


# -- Discovery ----------------------------------------------------------------------------------------------------
@router.get("/ServiceProviderConfig")
async def service_provider_config(scim: ScimAuth) -> JSONResponse:
    return protocol.response(protocol.service_provider_config(scim.base))


@router.get("/ResourceTypes")
async def resource_types(scim: ScimAuth) -> JSONResponse:
    found = protocol.resource_types(scim.base)
    return protocol.response(protocol.list_response(found, len(found), 0))


@router.get("/Schemas")
async def schemas(scim: ScimAuth) -> JSONResponse:
    found = protocol.schemas(scim.base)
    return protocol.response(protocol.list_response(found, len(found), 0))


# -- Users --------------------------------------------------------------------------------------------------------
async def _user_out(conn: AsyncConnection, scim: Scim, scim_id: uuid.UUID) -> dict[str, Any]:
    row = (await conn.execute(select(ScimUser).where(ScimUser.id == scim_id))).one()
    return service.user_resource(row, scim.base, await service.user_groups(conn, scim_id))


@router.post("/Users")
async def create_user(request: Request, scim: ScimAuth) -> JSONResponse:
    fields = protocol.user_fields(await _body(request))
    async with transaction(request, scim) as conn:
        async with authz_change(conn, scim.tenant_id):
            scim_id = await service.create_user(conn, scim, fields)
        await audit(conn, scim, "scim.user_create", f"scim_user:{scim_id}",
                    {"user_name": fields.user_name, "active": fields.active is not False})  # fmt: skip
        body = await _user_out(conn, scim, scim_id)
    return protocol.response(body, 201, body["meta"]["location"])


@router.get("/Users")
async def list_users(request: Request, scim: ScimAuth) -> JSONResponse:
    params = request.query_params
    found = protocol.parse_filter(params.get("filter"), ("userName", "externalId"))
    offset, limit = protocol.paging(params.get("startIndex"), params.get("count"))
    query = select(ScimUser)
    if found is not None and found.attribute == "userName":
        query = query.where(func.lower(ScimUser.user_name) == found.value.lower())
    elif found is not None:
        query = query.where(ScimUser.external_id == found.value)
    async with transaction(request, scim) as conn:
        total = (await conn.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
        rows = (await conn.execute(query.order_by(ScimUser.created_at, ScimUser.id).offset(offset).limit(limit))).all()
        resources = [service.user_resource(r, scim.base, await service.user_groups(conn, r.id)) for r in rows]
    return protocol.response(protocol.list_response(resources, total, offset))


@router.get("/Users/{scim_id}")
async def get_user(request: Request, scim_id: str, scim: ScimAuth) -> JSONResponse:
    async with transaction(request, scim) as conn:
        row = await service.load_user(conn, scim_id)
        return protocol.response(await _user_out(conn, scim, row.id))


async def _change_user(
    request: Request, scim: Scim, scim_id: str, changes: dict[str, Any], action: str
) -> JSONResponse:
    async with transaction(request, scim) as conn:
        row = await service.load_user(conn, scim_id)
        async with authz_change(conn, scim.tenant_id):
            active = await service.update_user(conn, scim, row.id, changes)
        details: dict[str, Any] = {"changed": sorted(changes)}
        if active is not None:
            details["active"] = active
        await audit(conn, scim, action, f"scim_user:{row.id}", details)
        if active is False:
            await audit(conn, scim, "scim.user_deactivate", f"scim_user:{row.id}", {"user_name": row.user_name})
        return protocol.response(await _user_out(conn, scim, row.id))


@router.put("/Users/{scim_id}")
async def replace_user(request: Request, scim_id: str, scim: ScimAuth) -> JSONResponse:
    fields = protocol.user_fields(await _body(request))
    changes = {k: getattr(fields, k) for k in ("user_name", "external_id", "given_name", "family_name",
                                                "display_name", "email", "active")}  # fmt: skip
    return await _change_user(request, scim, scim_id, changes, "scim.user_replace")


@router.patch("/Users/{scim_id}")
async def patch_user(request: Request, scim_id: str, scim: ScimAuth) -> JSONResponse:
    changes = protocol.user_patch(await _body(request))
    return await _change_user(request, scim, scim_id, changes, "scim.user_update")


@router.delete("/Users/{scim_id}", status_code=204)
async def delete_user(request: Request, scim_id: str, scim: ScimAuth) -> Response:
    """Deactivates (the person and their history stay); the identity provider sees `active: false`."""
    async with transaction(request, scim) as conn:
        row = await service.load_user(conn, scim_id)
        if row.active:
            async with authz_change(conn, scim.tenant_id):
                await service.set_active(conn, scim, row.id, False)
        await audit(conn, scim, "scim.user_deactivate", f"scim_user:{row.id}", {"user_name": row.user_name})
    return Response(status_code=204)


# -- Groups -------------------------------------------------------------------------------------------------------
@router.post("/Groups")
async def create_group(request: Request, scim: ScimAuth) -> JSONResponse:
    body = await _body(request)
    if not isinstance(body, dict):
        raise ScimError(400, "The body must be a JSON object.", "invalidSyntax")
    async with transaction(request, scim) as conn:
        async with authz_change(conn, scim.tenant_id):
            group_id, added = await service.create_group(conn, scim, body)
        row = await service.load_group(conn, str(group_id))
        await audit(conn, scim, "scim.group_create", f"scim_group:{group_id}",
                    {"display_name": row.display_name, "added": added})  # fmt: skip
        out = await service.group_resource(conn, row, scim.base)
    return protocol.response(out, 201, out["meta"]["location"])


@router.get("/Groups")
async def list_groups(request: Request, scim: ScimAuth) -> JSONResponse:
    params = request.query_params
    found = protocol.parse_filter(params.get("filter"), ("displayName", "externalId"))
    offset, limit = protocol.paging(params.get("startIndex"), params.get("count"))
    query = select(ScimGroup)
    if found is not None and found.attribute == "displayName":
        query = query.where(func.lower(ScimGroup.display_name) == found.value.lower())
    elif found is not None:
        query = query.where(ScimGroup.external_id == found.value)
    excluded = "members" in (params.get("excludedAttributes") or "").lower()
    async with transaction(request, scim) as conn:
        total = (await conn.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
        rows = (
            await conn.execute(query.order_by(ScimGroup.created_at, ScimGroup.id).offset(offset).limit(limit))
        ).all()
        resources = []
        for r in rows:
            out = await service.group_resource(conn, r, scim.base)
            if excluded:
                out.pop("members")
            resources.append(out)
    return protocol.response(protocol.list_response(resources, total, offset))


@router.get("/Groups/{scim_id}")
async def get_group(request: Request, scim_id: str, scim: ScimAuth) -> JSONResponse:
    async with transaction(request, scim) as conn:
        row = await service.load_group(conn, scim_id)
        return protocol.response(await service.group_resource(conn, row, scim.base))


@router.put("/Groups/{scim_id}")
async def replace_group(request: Request, scim_id: str, scim: ScimAuth) -> JSONResponse:
    body = await _body(request)
    if not isinstance(body, dict):
        raise ScimError(400, "The body must be a JSON object.", "invalidSyntax")
    name = protocol.text(body.get("displayName"), "displayName", 256, required=True)
    external_id = protocol.text(body.get("externalId"), "externalId", 320)
    async with transaction(request, scim) as conn:
        row = await service.load_group(conn, scim_id)
        members = await service.member_keys(conn, protocol.member_ids(body.get("members")))
        async with authz_change(conn, scim.tenant_id):
            added, removed = await service.replace_group(conn, scim, row.id, name, external_id, members, True)
        await audit(conn, scim, "scim.group_replace", f"scim_group:{row.id}",
                    {"display_name": name, "added": added, "removed": removed})  # fmt: skip
        return protocol.response(await service.group_resource(conn, await service.load_group(conn, scim_id),
                                                              scim.base))  # fmt: skip


@router.patch("/Groups/{scim_id}")
async def patch_group(request: Request, scim_id: str, scim: ScimAuth) -> Response:
    patch = protocol.group_patch(await _body(request))
    async with transaction(request, scim) as conn:
        row = await service.load_group(conn, scim_id)
        current = await service.current_members(conn, row.id)
        if patch.replace_members is not None:
            wanted = await service.member_keys(conn, patch.replace_members)
        elif patch.remove_all:
            wanted = set()
        else:
            # Removing someone who is not a member (or no longer exists) is nothing to do.
            gone = {uuid.UUID(r) for r in patch.remove if _is_uuid(r)}
            wanted = (current | await service.member_keys(conn, patch.add)) - gone
        members = None if wanted == current else wanted
        async with authz_change(conn, scim.tenant_id):
            added, removed = await service.replace_group(conn, scim, row.id, patch.display_name, patch.external_id,
                                                         members, patch.external_id is not None)  # fmt: skip
        await audit(conn, scim, "scim.group_update", f"scim_group:{row.id}",
                    {"display_name": patch.display_name or row.display_name, "added": added,
                     "removed": removed})  # fmt: skip
        return protocol.response(await service.group_resource(conn, await service.load_group(conn, scim_id),
                                                              scim.base))  # fmt: skip


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


@router.delete("/Groups/{scim_id}", status_code=204)
async def delete_group(request: Request, scim_id: str, scim: ScimAuth) -> Response:
    async with transaction(request, scim) as conn:
        row = await service.load_group(conn, scim_id)
        async with authz_change(conn, scim.tenant_id):
            members = await service.delete_group(conn, scim, row.id)
        await audit(conn, scim, "scim.group_delete", f"scim_group:{row.id}",
                    {"display_name": row.display_name, "removed": members})  # fmt: skip
    return Response(status_code=204)


def install(app: FastAPI) -> None:
    """The SCIM routes, their error format, and the bearer's administration (Identity)."""
    from nexti_api.scim import admin

    @app.exception_handler(ScimError)
    async def handle_scim(request: Request, exc: ScimError) -> JSONResponse:
        return protocol.error_response(exc)

    app.include_router(router)
    app.include_router(admin.router)
