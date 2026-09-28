"""Copies Keycloak events into the platform audit chain (spec 15.1: logins, failures, lockouts, MFA and admin events).

Polls the Admin REST API with the least-privilege service account (view-events). Only security-relevant user
events are kept, and only safe fields: Keycloak details include token ids, which never reach the log.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from nexti_api.audit import AuditEvent, record
from nexti_api.db.models import KeycloakEventCursor
from nexti_api.db.session import DbScope, scoped_connection
from nexti_api.keycloak_admin import KeycloakAdmin

PAGE = 100
FIRST_RUN_LOOKBACK = timedelta(days=1)
USER_EVENTS = {
    "LOGIN",
    "LOGOUT",
    "UPDATE_PASSWORD",
    "RESET_PASSWORD",
    "SEND_RESET_PASSWORD",
    "VERIFY_EMAIL",
    "SEND_VERIFY_EMAIL",
    "UPDATE_EMAIL",
    "UPDATE_PROFILE",
    "UPDATE_TOTP",
    "REMOVE_TOTP",
    "UPDATE_CREDENTIAL",
    "REMOVE_CREDENTIAL",
    "EXECUTE_ACTIONS",
    "EXECUTE_ACTION_TOKEN",
    "USER_DISABLED_BY_TEMPORARY_LOCKOUT",
    "USER_DISABLED_BY_PERMANENT_LOCKOUT",
    "IDENTITY_PROVIDER_LOGIN",
    "IDENTITY_PROVIDER_FIRST_LOGIN",
}


def _keep(event: dict[str, Any]) -> bool:
    kind = str(event.get("type", ""))
    return kind in USER_EVENTS or kind.endswith("_ERROR")


def _user_event(event: dict[str, Any]) -> AuditEvent:
    kind = str(event["type"])
    details = event.get("details") or {}
    return AuditEvent(
        action=f"keycloak.{kind.lower()}",
        outcome="failure" if kind.endswith("_ERROR") else "success",
        actor_kind="keycloak",
        actor_label=details.get("username") or event.get("userId"),
        target=f"keycloak-user:{event['userId']}" if event.get("userId") else None,
        details={
            "keycloak_event_id": event.get("id"),
            "client_id": event.get("clientId"),
            "ip_address": event.get("ipAddress"),
            "error": event.get("error"),
        },
        occurred_at=datetime.fromtimestamp(event["time"] / 1000, UTC),
    )


def _admin_event(event: dict[str, Any]) -> AuditEvent:
    auth = event.get("authDetails") or {}
    resource = str(event.get("resourceType", "unknown")).lower()
    operation = str(event.get("operationType", "unknown")).lower()
    return AuditEvent(
        action=f"keycloak.admin.{resource}_{operation}",
        outcome="failure" if event.get("error") else "success",
        actor_kind="keycloak",
        actor_label=auth.get("userId"),
        # The representation is never copied: it may carry credentials.
        target=str(event.get("resourcePath", "")) or None,
        details={
            "keycloak_event_id": event.get("id"),
            "auth_client_id": auth.get("clientId"),
            "ip_address": auth.get("ipAddress"),
            "error": event.get("error"),
        },
        occurred_at=datetime.fromtimestamp(event["time"] / 1000, UTC),
    )


def _key(event: dict[str, Any]) -> str:
    return str(event.get("id") or f"{event['time']}:{event.get('type')}:{event.get('userId')}:{uuid.uuid4()}")


async def _cursor(conn: AsyncConnection, kind: str) -> tuple[int, set[str]]:
    row = (
        await conn.execute(
            select(KeycloakEventCursor.last_time, KeycloakEventCursor.last_ids).where(KeycloakEventCursor.kind == kind)
        )
    ).one_or_none()
    if row is None:
        start = datetime.now(UTC) - FIRST_RUN_LOOKBACK
        return int(start.timestamp() * 1000), set()
    return row.last_time, set(row.last_ids)


async def _pull(engine: AsyncEngine, admin: KeycloakAdmin, kind: str) -> int:
    async with scoped_connection(engine, DbScope()) as conn:
        last_time, last_ids = await _cursor(conn, kind)
    date_from = datetime.fromtimestamp(last_time / 1000, UTC).strftime("%Y-%m-%d")

    # Keycloak returns newest first; page until reaching events older than the cursor.
    fresh: list[dict[str, Any]] = []
    first = 0
    while True:
        page = await admin.events(admin=kind == "admin", first=first, max_results=PAGE, date_from=date_from)
        fresh.extend(e for e in page if e["time"] > last_time or (e["time"] == last_time and _key(e) not in last_ids))
        if len(page) < PAGE or page[-1]["time"] < last_time:
            break
        first += PAGE
    if not fresh:
        return 0

    fresh.sort(key=lambda e: e["time"])
    newest = fresh[-1]["time"]
    ids_at_newest = {_key(e) for e in fresh if e["time"] == newest}
    if newest == last_time:
        ids_at_newest |= last_ids
    copied = 0
    async with scoped_connection(engine, DbScope()) as conn:
        for event in fresh:
            if kind == "admin":
                await record(conn, _admin_event(event))
                copied += 1
            elif _keep(event):
                await record(conn, _user_event(event))
                copied += 1
        await conn.execute(
            pg_insert(KeycloakEventCursor)
            .values(kind=kind, last_time=newest, last_ids=sorted(ids_at_newest))
            .on_conflict_do_update(
                index_elements=["kind"], set_={"last_time": newest, "last_ids": sorted(ids_at_newest)}
            )
        )
    return copied


async def pull_keycloak_events(engine: AsyncEngine, admin: KeycloakAdmin) -> int:
    """Copy new user and admin events to the audit log; returns how many were recorded."""
    return await _pull(engine, admin, "user") + await _pull(engine, admin, "admin")
