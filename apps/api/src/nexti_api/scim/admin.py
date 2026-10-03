"""Administration -> Authentication -> SCIM (ADR-0031): the tenant's SCIM bearer, created, rotated and revoked.

The value is high-entropy (256 bits) and returned once, when created; only its SHA-256 digest and a four-character
hint are kept. Creating a new one revokes the previous one (rotation). Every change is audited without the value.
"""

import secrets
import uuid
from datetime import datetime

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, insert, select, update

from nexti_api.admin.common import audit, transaction
from nexti_api.admin.identity import ManageIdentity
from nexti_api.errors import ProblemError
from nexti_api.schemas import ApiModel
from nexti_api.scim.routes import digest, scim_base
from nexti_core.db.models import ScimAccess

router = APIRouter(prefix="/api/v1/identity/scim", tags=["admin"])
PREFIX = "nxscim_"


class ScimAccessOut(ApiModel):
    enabled: bool
    base_url: str
    hint: str | None
    created_at: datetime | None
    last_used_at: datetime | None


class ScimAccessCreated(ScimAccessOut):
    # Shown once: the platform keeps only its digest.
    token: str
    rotated: bool


@router.get("", response_model=ScimAccessOut)
async def get_scim_access(request: Request, auth: ManageIdentity) -> ScimAccessOut:
    async with transaction(request, auth) as conn:
        row = (await conn.execute(select(ScimAccess).where(ScimAccess.revoked_at.is_(None)))).first()
    base = scim_base(request.app.state.settings)
    if row is None:
        return ScimAccessOut(enabled=False, base_url=base, hint=None, created_at=None, last_used_at=None)
    return ScimAccessOut(enabled=True, base_url=base, hint=row.hint, created_at=row.created_at,
                         last_used_at=row.last_used_at)  # fmt: skip


@router.post("", response_model=ScimAccessCreated, status_code=201)
async def create_scim_access(request: Request, response: Response, auth: ManageIdentity) -> ScimAccessCreated:
    """A new bearer for the tenant's identity provider; the current one (if any) stops working."""
    value = PREFIX + secrets.token_urlsafe(32)
    async with transaction(request, auth) as conn:
        revoked = (
            await conn.execute(update(ScimAccess).where(ScimAccess.revoked_at.is_(None))
                               .values(revoked_at=func.now(), revoked_by=auth.user_id).returning(ScimAccess.id))
        ).scalars().all()  # fmt: skip
        row = (
            await conn.execute(insert(ScimAccess).values(
                tenant_id=auth.tenant_id, access_digest=digest(value), hint=value[-4:], created_by=auth.user_id,
            ).returning(ScimAccess.id, ScimAccess.created_at))
        ).one()  # fmt: skip
        await audit(conn, auth, "identity.scim_access_rotate" if revoked else "identity.scim_access_create",
                    f"scim_access:{row.id}", {"replaced": [str(r) for r in revoked]})  # fmt: skip
    response.headers["Cache-Control"] = "no-store"
    return ScimAccessCreated(enabled=True, base_url=scim_base(request.app.state.settings), hint=value[-4:],
                             created_at=row.created_at, last_used_at=None, token=value,
                             rotated=bool(revoked))  # fmt: skip


@router.delete("", status_code=204)
async def revoke_scim_access(request: Request, auth: ManageIdentity) -> None:
    """The tenant's identity provider can no longer provision anyone (users and groups stay as they are)."""
    async with transaction(request, auth) as conn:
        revoked: list[uuid.UUID] = list(
            (await conn.execute(update(ScimAccess).where(ScimAccess.revoked_at.is_(None))
                                .values(revoked_at=func.now(), revoked_by=auth.user_id)
                                .returning(ScimAccess.id))).scalars()
        )  # fmt: skip
        if not revoked:
            raise ProblemError(404, "scim_access_not_found", "The tenant has no active SCIM bearer.")
        await audit(conn, auth, "identity.scim_access_revoke", f"scim_access:{revoked[0]}")
