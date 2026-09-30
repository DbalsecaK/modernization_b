"""The prototype change chat in the worker (spec 7.4, D-24): a person asks for a change of a screen through the API,
which records it and enqueues this job (the API never runs agents). The UX/UI designer applies it; code checks the
result like any prototype. A change that stays within the spec is a new prototype version; one that adds fields the
spec does not have is only proposed, with its prototype built, until a person accepts it. The chat never approves C2.
"""

import hashlib
import io
import json
import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_core.db.session import DbScope, scoped_connection
from nexti_core.object_store import ObjectStore
from nexti_core.spec.screens import ScreenSpec
from nexti_model_gateway.gateway import CallContext
from nexti_model_gateway.service import GatewayService
from nexti_orchestration.extraction import ModelReply
from nexti_orchestration.store import Usage
from nexti_orchestration.ui import change_prototype
from nexti_ui import IMAGE, PrototypeBuild, page

log = structlog.get_logger("nexti_worker")


class ChatCaller:
    """ModelCaller for the chat: labelled with the project and the UI phase (no run)."""

    def __init__(self, gateway: GatewayService, tenant_id: uuid.UUID, project_id: uuid.UUID) -> None:
        self.gateway = gateway
        self.tenant_id = tenant_id
        self.project_id = project_id

    async def complete(
        self, agent: str, phase: str, messages: list[dict[str, str]], *, iteration: int = 1, judge: int = 0
    ) -> ModelReply:
        ctx = CallContext(self.tenant_id, self.project_id, phase, agent, None, iteration)
        completion = await self.gateway.complete(ctx, list(messages))
        usage = Usage(completion.model or None, completion.usage.input_tokens, completion.usage.output_tokens,
                      completion.cost_usd)  # fmt: skip
        return ModelReply(completion.content, usage)


def prototype_prefix(tenant_id: uuid.UUID, project_id: uuid.UUID, screen: str, label: str) -> str:
    return f"tenants/{tenant_id}/projects/{project_id}/prototypes/{screen}/{label}"


async def put_text(objects: ObjectStore, key: str, content: str, content_type: str) -> None:
    data = content.encode("utf-8")
    await objects.put(key, io.BytesIO(data), len(data), content_type)


async def store_draft(
    objects: ObjectStore, tenant_id: uuid.UUID, project_id: uuid.UUID, screen: str, label: str, source: str,
    built: PrototypeBuild,
) -> dict[str, str]:  # fmt: skip
    """The code and the page of a prototype in the object store; returns their keys and the page's hash."""
    document = page(built, screen)
    prefix = prototype_prefix(tenant_id, project_id, screen, label)
    await put_text(objects, f"{prefix}/Screen.tsx", source, "text/plain; charset=utf-8")
    await put_text(objects, f"{prefix}/index.html", document, "text/html; charset=utf-8")
    return {"source_key": f"{prefix}/Screen.tsx", "bundle_key": f"{prefix}/index.html",
            "bundle_sha256": hashlib.sha256(document.encode("utf-8")).hexdigest()}  # fmt: skip


async def insert_prototype(
    conn: Any, tenant_id: uuid.UUID, project_id: uuid.UUID, screen: str, keys: dict[str, str], origin: str,
    notes: str, run_id: uuid.UUID | None = None,
) -> int:  # fmt: skip
    version = int(
        (
            await conn.execute(
                text("SELECT COALESCE(max(version), 0) + 1 FROM prototype WHERE project_id = :p AND screen_key = :s"),
                {"p": project_id, "s": screen},
            )
        ).scalar_one()
    )
    await conn.execute(
        text("INSERT INTO prototype (tenant_id, project_id, screen_key, version, origin, source_key, bundle_key, "
             "bundle_sha256, notes, run_id) VALUES (:t, :p, :s, :v, :o, :sk, :bk, :h, :n, :r)"),
        {"t": tenant_id, "p": project_id, "s": screen, "v": version, "o": origin, "sk": keys["source_key"],
         "bk": keys["bundle_key"], "h": keys["bundle_sha256"], "n": notes[:2000], "r": run_id},
    )  # fmt: skip
    return version


async def _agent_message(conn: Any, message: Any, body: str, status: str, **extra: Any) -> None:
    await conn.execute(
        text("INSERT INTO ui_chat_message (tenant_id, project_id, screen_key, role, body, status, proposal, "
             "prototype_version) VALUES (:t, :p, :s, 'agent', :b, :st, CAST(:pr AS jsonb), :v)"),
        {"t": message.tenant_id, "p": message.project_id, "s": message.screen_key, "b": body[:4000], "st": status,
         "pr": json.dumps(extra.get("proposal", {})), "v": extra.get("version")},
    )  # fmt: skip


async def apply_ui_change(
    engine: AsyncEngine, gateway: GatewayService, objects: ObjectStore, sandboxes: Any, message_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> str:  # fmt: skip
    scope = DbScope(tenant_id=tenant_id)
    async with scoped_connection(engine, scope) as conn:
        message = (
            await conn.execute(
                text("SELECT id, tenant_id, project_id, screen_key, body, status FROM ui_chat_message WHERE id = :m"),
                {"m": message_id},
            )
        ).one_or_none()
        if message is None or message.status != "pending":
            return "nothing to do"
        rows = (
            await conn.execute(
                text(
                    "SELECT DISTINCT ON (key) key, data FROM spec_element WHERE project_id = :p "
                    "AND element_type = 'screen' ORDER BY key, version DESC"
                ),
                {"p": message.project_id},
            )
        ).all()
        current = (
            await conn.execute(
                text("SELECT version, source_key FROM prototype WHERE project_id = :p AND screen_key = :s "
                     "ORDER BY version DESC LIMIT 1"),
                {"p": message.project_id, "s": message.screen_key},
            )
        ).one_or_none()  # fmt: skip
    screens = [ScreenSpec.model_validate(r.data) for r in rows]
    screen = next((s for s in screens if s.id == message.screen_key), None)
    if screen is None or current is None:
        async with scoped_connection(engine, scope) as conn:
            await _agent_message(conn, message, "This screen has no prototype yet: run the UI phase first.", "failed")
            await conn.execute(text("UPDATE ui_chat_message SET status = 'failed' WHERE id = :m"), {"m": message.id})
        return "no prototype"
    previous = b"".join(await objects.read(current.source_key)).decode("utf-8")
    caller = ChatCaller(gateway, tenant_id, message.project_id)
    outcome = await change_prototype(caller, sandboxes(IMAGE), screen, screens, previous, message.body)
    async with scoped_connection(engine, scope) as conn:
        if outcome.kind == "version" and outcome.built is not None:
            label = f"chat-{message.id}"
            keys = await store_draft(objects, tenant_id, message.project_id, screen.id, label, outcome.source,
                                     outcome.built)  # fmt: skip
            version = await insert_prototype(conn, tenant_id, message.project_id, screen.id, keys, "chat",
                                             message.body)  # fmt: skip
            await _agent_message(conn, message, f"Version {version} applies the change.", "done", version=version)
        elif outcome.kind == "proposal" and outcome.built is not None:
            keys = await store_draft(objects, tenant_id, message.project_id, screen.id, f"proposal-{message.id}",
                                     outcome.source, outcome.built)  # fmt: skip
            fields = ", ".join(outcome.new_fields)
            await _agent_message(
                conn, message,
                f"The change adds fields the screen spec does not have ({fields}). Accept it to update the spec and "
                "keep this prototype as a new version, or reject it.",
                "proposal", proposal={"fields": outcome.new_fields, "change": message.body, **keys},
            )  # fmt: skip
        else:
            await _agent_message(conn, message, f"The change could not be applied: {outcome.detail[:1500]}", "failed")
        status = "failed" if outcome.kind == "failed" else "done"
        await conn.execute(text("UPDATE ui_chat_message SET status = :s WHERE id = :m"), {"s": status, "m": message.id})
    log.info("ui_change.done", outcome=outcome.kind, screen=message.screen_key)
    return outcome.kind
