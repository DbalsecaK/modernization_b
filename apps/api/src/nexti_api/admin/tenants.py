"""Tenants (platform administration). Only NexTI super administrators."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz.require import Authorized, require_platform
from nexti_api.authz.sync import enqueue
from nexti_api.authz.tuples import expected_tuples
from nexti_api.errors import ProblemError
from nexti_api.schemas import ApiModel
from nexti_api.tenancy import create_tenant
from nexti_core.db.models import Tenant

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])
SuperAdmin = Annotated[Authorized, Depends(require_platform("superAdmin"))]
Deployment = Literal["sharedSaas", "dedicatedSaas", "customerCloud", "onPrem"]
Language = Literal["en", "es"]


class TenantOut(ApiModel):
    id: uuid.UUID
    slug: str
    name: str
    status: Literal["active", "suspended"]
    deployment_model: Deployment
    default_language: Language
    created_at: datetime


class TenantCreate(ApiModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str = Field(min_length=1, max_length=200)
    deployment_model: Deployment = "sharedSaas"
    default_language: Language = "en"


class TenantUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["active", "suspended"] | None = None
    deployment_model: Deployment | None = None
    default_language: Language | None = None


COLUMNS = (
    Tenant.id,
    Tenant.slug,
    Tenant.name,
    Tenant.status,
    Tenant.deployment_model,
    Tenant.default_language,
    Tenant.created_at,
)


def _out(row: object) -> TenantOut:
    return TenantOut.model_validate(row, from_attributes=True)


@router.get("", response_model=list[TenantOut])
async def list_tenants(request: Request, auth: SuperAdmin) -> list[TenantOut]:
    async with transaction(request, auth) as conn:
        rows = (await conn.execute(select(*COLUMNS).order_by(Tenant.name))).all()
    return [_out(r) for r in rows]


@router.post("", response_model=TenantOut, status_code=201)
async def create(request: Request, body: TenantCreate, auth: SuperAdmin) -> TenantOut:
    try:
        async with transaction(request, auth) as conn:
            tenant_id = await create_tenant(
                conn,
                slug=body.slug,
                name=body.name,
                deployment_model=body.deployment_model,
                default_language=body.default_language,
            )
            await enqueue(conn, tenant_id, writes=await expected_tuples(conn, tenant_id), deletes=set())
            await audit(conn, auth, "tenant.create", f"tenant:{tenant_id}", {"slug": body.slug}, platform=True)
            row = (await conn.execute(select(*COLUMNS).where(Tenant.id == tenant_id))).one()
    except IntegrityError as exc:
        raise ProblemError(409, "tenant_slug_taken", "The tenant slug is already in use.") from exc
    return _out(row)


@router.get("/{tenant_id}", response_model=TenantOut)
async def get_tenant(request: Request, tenant_id: uuid.UUID, auth: SuperAdmin) -> TenantOut:
    async with transaction(request, auth) as conn:
        row = (await conn.execute(select(*COLUMNS).where(Tenant.id == tenant_id))).one_or_none()
    if row is None:
        raise not_found("tenant")
    return _out(row)


@router.patch("/{tenant_id}", response_model=TenantOut)
async def update_tenant(request: Request, tenant_id: uuid.UUID, body: TenantUpdate, auth: SuperAdmin) -> TenantOut:
    changes = body.model_dump(exclude_none=True, by_alias=False)
    async with transaction(request, auth) as conn:
        if changes:
            result = await conn.execute(update(Tenant).where(Tenant.id == tenant_id).values(**changes))
            if result.rowcount == 0:
                raise not_found("tenant")
            await audit(conn, auth, "tenant.update", f"tenant:{tenant_id}", {"changes": changes}, platform=True)
        row = (await conn.execute(select(*COLUMNS).where(Tenant.id == tenant_id))).one_or_none()
    if row is None:
        raise not_found("tenant")
    return _out(row)
