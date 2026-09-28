"""Writes audit events and verifies their hash chains.

The chain itself (seq, prev_hash, hash) is computed by the database; this module only inserts the event,
inside the caller's transaction, so the event is recorded if and only if the action commits.
"""

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import structlog
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_core.db.models import AuditLog

ActorKind = Literal["user", "dev-auth", "system", "keycloak"]
Outcome = Literal["success", "failure", "allowed", "denied"]

# The log is immutable: a secret written by mistake could never be removed, so it is refused up front.
_SECRET_KEY = re.compile(r"pass(word|wd)?|pwd|secret|otp|totp|recovery|credential|token|api_?key|cookie", re.I)
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.")


@dataclass(frozen=True)
class AuditEvent:
    action: str
    outcome: Outcome
    actor_kind: ActorKind
    actor_id: uuid.UUID | None = None
    actor_label: str | None = None
    target: str | None = None
    # None = platform chain (sign-in, Keycloak events, tenant administration by the platform).
    tenant_id: uuid.UUID | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    occurred_at: datetime | None = None


@dataclass(frozen=True)
class ChainStatus:
    checked: int
    first_broken_seq: int | None
    reason: str | None

    @property
    def intact(self) -> bool:
        return self.first_broken_seq is None


def _reject_secrets(value: Any, path: str = "details") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _SECRET_KEY.search(str(key)):
                raise ValueError(f"audit {path}.{key}: looks like a credential and cannot be logged")
            _reject_secrets(item, f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _reject_secrets(item, f"{path}[{index}]")
    elif isinstance(value, str) and _JWT.search(value):
        raise ValueError(f"audit {path}: contains a token and cannot be logged")


async def record(conn: AsyncConnection, event: AuditEvent) -> int | None:
    """Insert the event in the caller's transaction and return its position in the chain.

    Platform events return None: the caller usually cannot read the platform chain, and RETURNING would
    require the new row to be readable.
    """
    _reject_secrets(dict(event.details))
    if event.target:
        _reject_secrets(event.target, "target")
    values: dict[str, Any] = {
        "tenant_id": event.tenant_id,
        "actor_kind": event.actor_kind,
        "actor_id": event.actor_id,
        "actor_label": event.actor_label,
        "action": event.action,
        "target": event.target,
        "outcome": event.outcome,
        "details": dict(event.details),
        "request_id": structlog.contextvars.get_contextvars().get("request_id"),
    }
    if event.occurred_at is not None:
        values["occurred_at"] = event.occurred_at
    if event.tenant_id is None:
        # inline(): no RETURNING at all (not even the primary key SQLAlchemy would fetch by default).
        await conn.execute(insert(AuditLog).values(**values).inline())
        return None
    seq: int = (await conn.execute(insert(AuditLog).values(**values).returning(AuditLog.seq))).scalar_one()
    return seq


async def verify(conn: AsyncConnection, tenant_id: uuid.UUID | None) -> ChainStatus:
    """Walk one chain (the active tenant's, or any with platform scope) and report the first broken row."""
    row = (
        await conn.execute(text("SELECT checked, first_broken_seq, reason FROM audit_verify(:t)"), {"t": tenant_id})
    ).one()
    return ChainStatus(checked=row.checked, first_broken_seq=row.first_broken_seq, reason=row.reason)
