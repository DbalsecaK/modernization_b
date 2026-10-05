"""Pack profiles of a tenant (ADR-0040): how the tenant wants the generated code of a backend pack shaped, without
writing a pack. A profile is data (a package root the design must respect and conventions the agents are told);
the pack, its sandbox image and its certification stay the platform's."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz.require import Authorized, require_tenant
from nexti_api.errors import ProblemError
from nexti_api.schemas import ApiModel
from nexti_core.db.models import TenantPackProfile

router = APIRouter(prefix="/api/v1/pack-profiles", tags=["admin"])
ManageCatalog = Annotated[Authorized, Depends(require_tenant("models.configure"))]
KEY = r"^[a-z][a-z0-9-]{1,40}$"
PACKAGE_ROOT = r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)*$"


class PackProfileIn(ApiModel):
    key: str = Field(pattern=KEY)
    name: str = Field(min_length=1, max_length=120)
    backend: str | None = Field(default=None, max_length=40, description="The backend pack it applies to, or any")
    package_root: str | None = Field(default=None, pattern=PACKAGE_ROOT, max_length=120,
                                     description="The design's base package must start with it")  # fmt: skip
    conventions: str = Field(default="", max_length=4000, description="Told to the architect, developer and reviewer")


class PackProfileOut(ApiModel):
    id: uuid.UUID
    key: str
    name: str
    backend: str | None
    package_root: str | None
    conventions: str
    created_at: datetime
    updated_at: datetime


def _out(row: Any) -> PackProfileOut:
    return PackProfileOut(
        id=row.id, key=row.key, name=row.name, backend=row.backend, package_root=row.package_root,
        conventions=row.conventions, created_at=row.created_at, updated_at=row.updated_at,
    )  # fmt: skip


async def _load(conn: AsyncConnection, profile_id: uuid.UUID) -> Any:
    row = (
        (await conn.execute(select(TenantPackProfile).where(TenantPackProfile.id == profile_id)))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise not_found("pack_profile")
    return row


@router.get("", response_model=list[PackProfileOut])
async def list_profiles(request: Request, auth: ManageCatalog) -> list[PackProfileOut]:
    async with transaction(request, auth) as conn:
        rows = (await conn.execute(select(TenantPackProfile).order_by(TenantPackProfile.created_at))).mappings().all()
    return [_out(r) for r in rows]


@router.post("", response_model=PackProfileOut, status_code=201)
async def create_profile(request: Request, body: PackProfileIn, auth: ManageCatalog) -> PackProfileOut:
    async with transaction(request, auth) as conn:
        try:
            profile_id = (
                await conn.execute(
                    insert(TenantPackProfile)
                    .values(tenant_id=auth.tenant_id, key=body.key, name=body.name, backend=body.backend,
                            package_root=body.package_root, conventions=body.conventions, created_by=auth.user_id)
                    .returning(TenantPackProfile.id)
                )
            ).scalar_one()  # fmt: skip
        except IntegrityError as exc:
            raise ProblemError(
                409, "pack_profile_exists", f"The tenant already has a pack profile {body.key}."
            ) from exc
        await audit(conn, auth, "pack_profile.create", f"pack_profile:{profile_id}", {"key": body.key})
        return _out(await _load(conn, profile_id))


@router.put("/{profile_id}", response_model=PackProfileOut)
async def update_profile(
    request: Request, profile_id: uuid.UUID, body: PackProfileIn, auth: ManageCatalog
) -> PackProfileOut:
    async with transaction(request, auth) as conn:
        row = await _load(conn, profile_id)
        if body.key != row.key:
            raise ProblemError(422, "pack_profile_key_fixed", "The key of a profile does not change; create another.")
        await conn.execute(
            update(TenantPackProfile)
            .where(TenantPackProfile.id == profile_id)
            .values(
                name=body.name,
                backend=body.backend,
                package_root=body.package_root,
                conventions=body.conventions,
                updated_at=datetime.now(UTC),
            )
        )
        await audit(conn, auth, "pack_profile.update", f"pack_profile:{profile_id}", {"key": body.key})
        return _out(await _load(conn, profile_id))


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(request: Request, profile_id: uuid.UUID, auth: ManageCatalog) -> None:
    async with transaction(request, auth) as conn:
        row = await _load(conn, profile_id)
        await conn.execute(delete(TenantPackProfile).where(TenantPackProfile.id == profile_id))
        await audit(conn, auth, "pack_profile.delete", f"pack_profile:{profile_id}", {"key": row.key})
