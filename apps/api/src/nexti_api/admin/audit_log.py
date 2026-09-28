"""Audit log of the active tenant: browse, export (for regulatory audits, spec 15.6) and verify the chain."""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, select

from nexti_api.admin.common import audit, transaction
from nexti_api.audit import verify
from nexti_api.authz.require import Authorized, require_tenant
from nexti_api.db.models import AuditLog
from nexti_api.schemas import ApiModel

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])
AuditView = Annotated[Authorized, Depends(require_tenant("audit.view"))]
EXPORT_LIMIT = 100_000


class AuditEntryOut(ApiModel):
    id: int
    seq: int
    occurred_at: datetime
    actor_kind: Literal["user", "dev-auth", "system", "keycloak"]
    actor_id: uuid.UUID | None
    actor_label: str | None
    action: str
    target: str | None
    outcome: Literal["success", "failure", "allowed", "denied"]
    details: dict[str, Any]
    request_id: str | None


class AuditPage(ApiModel):
    items: list[AuditEntryOut]
    # Pass as `before` to get the next (older) page; null when there is none.
    next_before: int | None


class ChainOut(ApiModel):
    intact: bool
    checked: int
    first_broken_seq: int | None
    reason: str | None


COLUMNS = (
    AuditLog.id,
    AuditLog.seq,
    AuditLog.occurred_at,
    AuditLog.actor_kind,
    AuditLog.actor_id,
    AuditLog.actor_label,
    AuditLog.action,
    AuditLog.target,
    AuditLog.outcome,
    AuditLog.details,
    AuditLog.request_id,
)


def _filtered(
    tenant_id: uuid.UUID,
    action: str | None,
    actor_id: uuid.UUID | None,
    outcome: str | None,
    since: datetime | None,
    until: datetime | None,
) -> Select[Any]:
    # The tenant filter is explicit on top of RLS: a platform-scoped session must not mix chains here.
    query = select(*COLUMNS).where(AuditLog.tenant_id == tenant_id)
    if action:
        query = query.where(AuditLog.action.startswith(action))
    if actor_id:
        query = query.where(AuditLog.actor_id == actor_id)
    if outcome:
        query = query.where(AuditLog.outcome == outcome)
    if since:
        query = query.where(AuditLog.occurred_at >= since)
    if until:
        query = query.where(AuditLog.occurred_at < until)
    return query


@router.get("", response_model=AuditPage)
async def list_entries(
    request: Request,
    auth: AuditView,
    action: str | None = None,
    actor_id: Annotated[uuid.UUID | None, Query(alias="actorId")] = None,
    outcome: Literal["success", "failure", "allowed", "denied"] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    before: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuditPage:
    assert auth.tenant_id is not None  # noqa: S101
    query = _filtered(auth.tenant_id, action, actor_id, outcome, since, until)
    if before is not None:
        query = query.where(AuditLog.id < before)
    async with transaction(request, auth) as conn:
        rows = (await conn.execute(query.order_by(AuditLog.id.desc()).limit(limit + 1))).all()
    items = [AuditEntryOut.model_validate(r, from_attributes=True) for r in rows[:limit]]
    return AuditPage(items=items, next_before=items[-1].id if len(rows) > limit else None)


@router.get("/export", response_class=StreamingResponse, responses={200: {"content": {"application/x-ndjson": {}}}})
async def export(
    request: Request,
    auth: AuditView,
    since: datetime | None = None,
    until: datetime | None = None,
) -> StreamingResponse:
    """One JSON object per line, oldest first, with the hashes so the chain can be checked offline."""
    assert auth.tenant_id is not None  # noqa: S101
    query = (
        _filtered(auth.tenant_id, None, None, None, since, until)
        .add_columns(AuditLog.prev_hash, AuditLog.hash)
        .order_by(AuditLog.seq)
        .limit(EXPORT_LIMIT)
    )
    async with transaction(request, auth) as conn:
        rows = (await conn.execute(query)).all()
        await audit(conn, auth, "audit.export", f"tenant:{auth.tenant_id}", {"rows": len(rows)})

    async def lines() -> AsyncIterator[bytes]:
        for r in rows:
            entry = AuditEntryOut.model_validate(r, from_attributes=True).model_dump(mode="json")
            entry["prevHash"] = r.prev_hash.hex() if r.prev_hash else None
            entry["hash"] = r.hash.hex()
            yield (json.dumps(entry, ensure_ascii=False) + "\n").encode()

    filename = f"audit-{auth.tenant_id}.ndjson"
    return StreamingResponse(
        lines(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/verify", response_model=ChainOut)
async def verify_chain(request: Request, auth: AuditView) -> ChainOut:
    assert auth.tenant_id is not None  # noqa: S101
    async with transaction(request, auth) as conn:
        status = await verify(conn, auth.tenant_id)
    return ChainOut(
        intact=status.intact, checked=status.checked, first_broken_seq=status.first_broken_seq, reason=status.reason
    )
