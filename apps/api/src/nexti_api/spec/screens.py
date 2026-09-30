"""Screens and prototypes of a project (spec 4.1, 7.4, ADR-0013): the screen specs (versioned, editable by people),
the design system, the prototype versions of each screen and the comments on them.

A prototype page is code written by a model: it is served with a strict CSP for an iframe without the same origin
(no cookies, storage, network or access to the page around it). Its TSX source is code and needs `code.view`."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz.require import Authorized, require_project
from nexti_api.errors import ProblemError
from nexti_api.projects import services
from nexti_api.spec.schemas import (
    CommentIn,
    CommentOut,
    DesignSystemOut,
    PrototypeOut,
    ResolveIn,
    RuleOut,
)
from nexti_core.spec.screens import ScreenSpec

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
