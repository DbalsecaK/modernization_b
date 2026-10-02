"""Screens and prototypes of a project (spec 4.1, 7.4, ADR-0013): the screen specs (versioned, editable by people),
the design system, the prototype versions of each screen and the comments on them.

A prototype page is code written by a model: it is served with a strict CSP for an iframe without the same origin
(no cookies, storage, network or access to the page around it). Its TSX source is code and needs `code.view`.

The screens can also leave as a generated Figma plugin (ADR-0030): the same specs any project viewer already reads,
with the design tokens, so the export needs `project.view` and is audited."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api import license_gate
from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz.require import Authorized, require_project
from nexti_api.errors import ProblemError
from nexti_api.projects import services
from nexti_api.spec.schemas import (
    ChatIn,
    ChatMessageOut,
    CommentIn,
    CommentOut,
    DesignSystemOut,
    PrototypeOut,
    ResolveIn,
    RuleOut,
)
from nexti_core.jobs import defer_ui_change
from nexti_core.spec.screens import ScreenSpec
from nexti_ui.figma_export import export_zip

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["screens"])
ViewProject = Annotated[Authorized, Depends(require_project("project.view"))]
ViewCode = Annotated[Authorized, Depends(require_project("code.view"))]
EditPrototypes = Annotated[Authorized, Depends(require_project("prototype.edit"))]
CommentPrototypes = Annotated[Authorized, Depends(require_project("prototype.comment"))]

# The frame may run its own inline bundle and nothing else: no network, no forms, no framing by anyone but the
# platform, and a sandbox without allow-same-origin (an opaque origin even if opened outside the iframe).
PROTOTYPE_CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; "
    "connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'; sandbox allow-scripts"
)


async def _screens(conn: AsyncConnection, project_id: uuid.UUID, key: str | None = None) -> list[dict[str, Any]]:
    rows = await conn.execute(
        text(
            "SELECT DISTINCT ON (key) key, version, status, data, origin, created_at FROM spec_element "
            "WHERE project_id = :p AND element_type = 'screen' AND (CAST(:k AS text) IS NULL OR key = :k) "
            "ORDER BY key, version DESC"
        ),
        {"p": project_id, "k": key},
    )
    return [dict(r) for r in rows.mappings()]


@router.get("/screens", response_model=list[RuleOut])
async def list_screens(request: Request, project_id: uuid.UUID, auth: ViewProject) -> list[RuleOut]:
    async with transaction(request, auth) as conn:
        return [RuleOut.model_validate(r) for r in await _screens(conn, project_id)]


@router.get("/screens/{key}/versions", response_model=list[RuleOut])
async def screen_versions(request: Request, project_id: uuid.UUID, key: str, auth: ViewProject) -> list[RuleOut]:
    async with transaction(request, auth) as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT key, version, status, data, origin, created_at FROM spec_element WHERE project_id = :p "
                        "AND element_type = 'screen' AND key = :k ORDER BY version DESC"
                    ),
                    {"p": project_id, "k": key},
                )
            )
            .mappings()
            .all()
        )
    if not rows:
        raise not_found("screen")
    return [RuleOut.model_validate(dict(r)) for r in rows]


@router.put("/screens/{key}", response_model=RuleOut)
async def edit_screen(
    request: Request, project_id: uuid.UUID, key: str, body: dict[str, Any], auth: EditPrototypes
) -> RuleOut:
    """A new version of a screen spec written by a person (a field, a validation, an action...)."""
    try:
        screen = ScreenSpec.model_validate({**body, "id": key})
    except ValidationError as exc:
        raise ProblemError(
            422,
            "invalid_screen",
            "The screen spec is not valid.",
            problems=[{"loc": list(e["loc"]), "message": e["msg"]} for e in exc.errors()[:20]],
        ) from exc
    async with transaction(request, auth) as conn:
        current = await _screens(conn, project_id, key)
        if not current:
            raise not_found("screen")
        version = current[0]["version"] + 1
        await conn.execute(
            text(
                "INSERT INTO spec_element (tenant_id, project_id, element_type, key, version, status, data, origin, "
                "created_by) VALUES (:t, :p, 'screen', :k, :v, 'review', CAST(:d AS jsonb), 'person', :u)"
            ),
            {
                "t": auth.tenant_id,
                "p": project_id,
                "k": key,
                "v": version,
                "d": screen.model_dump_json(),
                "u": auth.user_id,
            },
        )
        await audit(conn, auth, "screen.edit", f"project:{project_id}", {"screen": key, "version": version})
        return RuleOut.model_validate((await _screens(conn, project_id, key))[0])


@router.get("/design-system", response_model=DesignSystemOut)
async def design_system(request: Request, project_id: uuid.UUID, auth: ViewProject) -> DesignSystemOut:
    async with transaction(request, auth) as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT version, source, tokens, status, created_at FROM design_system WHERE project_id = :p "
                        "ORDER BY version DESC LIMIT 1"
                    ),
                    {"p": project_id},
                )
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        raise not_found("design system")
    return DesignSystemOut.model_validate(dict(row))


@router.get("/screens:figma-export")
async def figma_export(request: Request, project_id: uuid.UUID, auth: ViewProject) -> Response:
    """The newest version of every screen as a Figma development plugin (manifest.json and code.js) in a zip."""
    async with transaction(request, auth) as conn:
        screens = await _screens(conn, project_id)
        if not screens:
            raise not_found("screens")
        tokens = (
            await conn.execute(
                text("SELECT tokens FROM design_system WHERE project_id = :p ORDER BY version DESC LIMIT 1"),
                {"p": project_id},
            )
        ).scalar_one_or_none()
        await audit(conn, auth, "screens.figma_export", f"project:{project_id}", {"screens": len(screens)})
    data = export_zip([s["data"] for s in screens], tokens)
    headers = {
        "Content-Disposition": f'attachment; filename="figma-screens-{project_id}.zip"',
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "private, no-store",
    }
    return Response(data, media_type="application/zip", headers=headers)


async def _prototype(conn: AsyncConnection, project_id: uuid.UUID, key: str, version: int) -> dict[str, Any]:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT id, screen_key, version, origin, status, notes, source_key, bundle_key, created_at "
                    "FROM prototype WHERE project_id = :p AND screen_key = :k AND version = :v"
                ),
                {"p": project_id, "k": key, "v": version},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise not_found("prototype")
    return dict(row)


@router.get("/screens/{key}/prototypes", response_model=list[PrototypeOut])
async def prototypes(request: Request, project_id: uuid.UUID, key: str, auth: ViewProject) -> list[PrototypeOut]:
    async with transaction(request, auth) as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT p.id, p.screen_key, p.version, p.origin, p.status, p.notes, p.created_at, "
                        "(SELECT count(*) FROM prototype_comment c WHERE c.prototype_id = p.id AND NOT c.resolved) "
                        "AS open_comments FROM prototype p WHERE p.project_id = :p AND p.screen_key = :k "
                        "ORDER BY p.version DESC"
                    ),
                    {"p": project_id, "k": key},
                )
            )
            .mappings()
            .all()
        )
    return [PrototypeOut.model_validate(dict(r)) for r in rows]


@router.get("/screens/{key}/prototypes/{version}/page")
async def prototype_page(
    request: Request, project_id: uuid.UUID, key: str, version: int, auth: ViewProject
) -> Response:
    """The prototype for its isolated iframe (ADR-0013)."""
    async with transaction(request, auth) as conn:
        found = await _prototype(conn, project_id, key, version)
    document = b"".join(await services.store(request).read(found["bundle_key"]))
    headers = {
        "Content-Security-Policy": PROTOTYPE_CSP,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Cache-Control": "private, max-age=300",
    }
    return Response(document, media_type="text/html; charset=utf-8", headers=headers)


@router.get("/screens/{key}/prototypes/{version}/source", response_class=PlainTextResponse)
async def prototype_source(request: Request, project_id: uuid.UUID, key: str, version: int, auth: ViewCode) -> str:
    async with transaction(request, auth) as conn:
        found = await _prototype(conn, project_id, key, version)
    return b"".join(await services.store(request).read(found["source_key"])).decode("utf-8")


@router.get("/screens/{key}/prototypes/{version}/comments", response_model=list[CommentOut])
async def comments(
    request: Request, project_id: uuid.UUID, key: str, version: int, auth: ViewProject
) -> list[CommentOut]:
    async with transaction(request, auth) as conn:
        found = await _prototype(conn, project_id, key, version)
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT c.id, c.body, c.anchor, c.resolved, c.created_at, u.display_name AS author "
                        "FROM prototype_comment c LEFT JOIN app_user u ON u.id = c.created_by "
                        "WHERE c.prototype_id = :id ORDER BY c.created_at"
                    ),
                    {"id": found["id"]},
                )
            )
            .mappings()
            .all()
        )
    return [CommentOut.model_validate(dict(r)) for r in rows]


@router.post("/screens/{key}/prototypes/{version}/comments", response_model=CommentOut, status_code=201)
async def add_comment(
    request: Request, project_id: uuid.UUID, key: str, version: int, body: CommentIn, auth: CommentPrototypes
) -> CommentOut:
    async with transaction(request, auth) as conn:
        found = await _prototype(conn, project_id, key, version)
        row = (
            (
                await conn.execute(
                    text(
                        "INSERT INTO prototype_comment (tenant_id, project_id, prototype_id, body, anchor, created_by) "
                        "VALUES (:t, :p, :id, :b, CAST(:a AS jsonb), :u) "
                        "RETURNING id, body, anchor, resolved, created_at"
                    ),
                    {
                        "t": auth.tenant_id,
                        "p": project_id,
                        "id": found["id"],
                        "b": body.body,
                        "a": body.anchor.model_dump_json(exclude_none=True),
                        "u": auth.user_id,
                    },
                )
            )
            .mappings()
            .one()
        )
        await audit(
            conn,
            auth,
            "prototype.comment",
            f"project:{project_id}",
            {"screen": key, "version": version, "comment": str(row["id"])},
        )
    return CommentOut.model_validate({**dict(row), "author": None})


@router.post("/screens/{key}/prototypes/{version}/comments/{comment_id}:resolve", response_model=CommentOut)
async def resolve_comment(
    request: Request,
    project_id: uuid.UUID,
    key: str,
    version: int,
    comment_id: uuid.UUID,
    body: ResolveIn,
    auth: CommentPrototypes,
) -> CommentOut:
    async with transaction(request, auth) as conn:
        found = await _prototype(conn, project_id, key, version)
        row = (
            (
                await conn.execute(
                    text(
                        "UPDATE prototype_comment SET resolved = :r WHERE id = :c AND prototype_id = :id "
                        "RETURNING id, body, anchor, resolved, created_at"
                    ),
                    {"r": body.resolved, "c": comment_id, "id": found["id"]},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise not_found("comment")
        await audit(
            conn,
            auth,
            "prototype.comment_resolve",
            f"project:{project_id}",
            {"comment": str(comment_id), "resolved": body.resolved},
        )
    return CommentOut.model_validate({**dict(row), "author": None})


# -- the change chat (D-24) --------------------------------------------------------------------------------------
async def _messages(conn: AsyncConnection, project_id: uuid.UUID, key: str) -> list[ChatMessageOut]:
    rows = await conn.execute(
        text(
            "SELECT m.id, m.role, m.body, m.status, m.proposal, m.prototype_version, m.created_at, "
            "u.display_name AS author FROM ui_chat_message m LEFT JOIN app_user u ON u.id = m.created_by "
            "WHERE m.project_id = :p AND m.screen_key = :k ORDER BY m.created_at, m.role DESC"
        ),
        {"p": project_id, "k": key},
    )
    return [
        ChatMessageOut.model_validate({**dict(r), "proposal_fields": list((r["proposal"] or {}).get("fields", []))})
        for r in rows.mappings()
    ]


@router.get("/screens/{key}/chat", response_model=list[ChatMessageOut])
async def chat(request: Request, project_id: uuid.UUID, key: str, auth: ViewProject) -> list[ChatMessageOut]:
    async with transaction(request, auth) as conn:
        return await _messages(conn, project_id, key)


@router.post("/screens/{key}/chat", response_model=list[ChatMessageOut], status_code=202)
async def ask_change(
    request: Request, project_id: uuid.UUID, key: str, body: ChatIn, auth: EditPrototypes
) -> list[ChatMessageOut]:
    """Records the change and enqueues it for the UX/UI designer (the API never runs agents)."""
    await license_gate.ensure_writable(request, auth, "ui_change.request", f"project:{project_id}")
    async with transaction(request, auth) as conn:
        if not await _screens(conn, project_id, key):
            raise not_found("screen")
        message = (
            await conn.execute(
                text(
                    "INSERT INTO ui_chat_message (tenant_id, project_id, screen_key, role, body, status, created_by) "
                    "VALUES (:t, :p, :k, 'user', :b, 'pending', :u) RETURNING id, tenant_id"
                ),
                {"t": auth.tenant_id, "p": project_id, "k": key, "b": body.body, "u": auth.user_id},
            )
        ).one()
        await defer_ui_change(conn, message.id, message.tenant_id, project_id, key)
        details = {"screen": key, "message": str(message.id)}
        await audit(conn, auth, "prototype.change_request", f"project:{project_id}", details)
        return await _messages(conn, project_id, key)


async def _proposal(conn: AsyncConnection, project_id: uuid.UUID, key: str, message_id: uuid.UUID) -> dict[str, Any]:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT id, status, proposal FROM ui_chat_message WHERE id = :m AND project_id = :p "
                    "AND screen_key = :k AND role = 'agent'"
                ),
                {"m": message_id, "p": project_id, "k": key},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise not_found("proposal")
    if row["status"] != "proposal":
        raise ProblemError(409, "not_a_proposal", "This message is not a pending proposal.")
    return dict(row)


@router.post("/screens/{key}/chat/{message_id}:accept", response_model=list[ChatMessageOut])
async def accept_proposal(
    request: Request, project_id: uuid.UUID, key: str, message_id: uuid.UUID, auth: EditPrototypes
) -> list[ChatMessageOut]:
    """A person accepts a change of spec proposed by the designer: the screen spec gets the new fields (a new
    version) and the proposed prototype becomes a new version."""
    async with transaction(request, auth) as conn:
        proposal = (await _proposal(conn, project_id, key, message_id))["proposal"]
        current = await _screens(conn, project_id, key)
        if not current:
            raise not_found("screen")
        data = dict(current[0]["data"])
        known = {f["name"] for f in data["fields"]}
        added = [
            {"name": name, "kind": "input", "label": name.replace("_", " ").title(), "length": 40}
            for name in proposal.get("fields", [])
            if name not in known
        ]
        screen = ScreenSpec.model_validate({**data, "fields": [*data["fields"], *added]})
        version = current[0]["version"] + 1
        await conn.execute(
            text(
                "INSERT INTO spec_element (tenant_id, project_id, element_type, key, version, status, data, origin, "
                "change_note, created_by) VALUES (:t, :p, 'screen', :k, :v, 'review', CAST(:d AS jsonb), 'person', "
                ":n, :u)"
            ),
            {
                "t": auth.tenant_id,
                "p": project_id,
                "k": key,
                "v": version,
                "d": screen.model_dump_json(),
                "n": proposal.get("change", "")[:2000],
                "u": auth.user_id,
            },
        )
        prototype_version = int(
            (
                await conn.execute(
                    text(
                        "SELECT COALESCE(max(version), 0) + 1 FROM prototype WHERE project_id = :p AND screen_key = :k"
                    ),
                    {"p": project_id, "k": key},
                )
            ).scalar_one()
        )
        await conn.execute(
            text(
                "INSERT INTO prototype (tenant_id, project_id, screen_key, version, origin, source_key, bundle_key, "
                "bundle_sha256, notes, created_by) VALUES (:t, :p, :k, :v, 'chat', :sk, :bk, :h, :n, :u)"
            ),
            {
                "t": auth.tenant_id,
                "p": project_id,
                "k": key,
                "v": prototype_version,
                "sk": proposal["source_key"],
                "bk": proposal["bundle_key"],
                "h": proposal["bundle_sha256"],
                "n": proposal.get("change", "")[:2000],
                "u": auth.user_id,
            },
        )
        await conn.execute(
            text("UPDATE ui_chat_message SET status = 'done', prototype_version = :v WHERE id = :m"),
            {"v": prototype_version, "m": message_id},
        )
        details = {"screen": key, "spec_version": version, "prototype_version": prototype_version}
        await audit(conn, auth, "prototype.accept_proposal", f"project:{project_id}", details)
        return await _messages(conn, project_id, key)


@router.post("/screens/{key}/chat/{message_id}:reject", response_model=list[ChatMessageOut])
async def reject_proposal(
    request: Request, project_id: uuid.UUID, key: str, message_id: uuid.UUID, auth: EditPrototypes
) -> list[ChatMessageOut]:
    async with transaction(request, auth) as conn:
        await _proposal(conn, project_id, key, message_id)
        await conn.execute(text("UPDATE ui_chat_message SET status = 'rejected' WHERE id = :m"), {"m": message_id})
        details = {"screen": key, "message": str(message_id)}
        await audit(conn, auth, "prototype.reject_proposal", f"project:{project_id}", details)
        return await _messages(conn, project_id, key)
