"""Inputs of a project (spec 7.1, 15.4): files validated by nexti_ingest before they reach the object store, and
links (Figma, prototypes). A rejected upload is recorded with its reason and audited, but nothing is stored."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz import names
from nexti_api.authz.require import Authorized, deny, require_project
from nexti_api.errors import ProblemError
from nexti_api.projects import services
from nexti_api.schemas import ApiModel
from nexti_core.db.models import AppUser, InputArtifact, Project
from nexti_core.object_store import input_key
from nexti_ingest import Rejection, ScannerUnavailableError, figma_link, prototype_link, safe_name, validate
from nexti_ingest.loose import CODE_KINDS, as_upload

router = APIRouter(prefix="/api/v1/projects/{project_id}/inputs", tags=["inputs"])
ViewProject = Annotated[Authorized, Depends(require_project("project.view"))]
UploadInputs = Annotated[Authorized, Depends(require_project("input.upload"))]
FileKind = Literal["source_archive", "target_archive", "document", "screenshot"]
LinkKind = Literal["figma_link", "prototype_link"]


class InputOut(ApiModel):
    id: uuid.UUID
    kind: Literal["source_archive", "target_archive", "document", "screenshot", "figma_link", "prototype_link"]
    name: str
    version: int | None
    status: Literal["accepted", "rejected", "deleted"]
    size_bytes: int | None
    sha256: str | None
    content_type: str | None
    url: str | None
    notes: str
    findings: dict[str, Any]
    rejection_code: str | None
    rejection_detail: str | None
    uploaded_by: uuid.UUID | None
    uploaded_by_name: str | None
    created_at: datetime


class LinkIn(ApiModel):
    kind: LinkKind
    url: str = Field(min_length=1, max_length=2000)
    notes: str = Field(default="", max_length=2000)


COLUMNS = (
    InputArtifact.id, InputArtifact.kind, InputArtifact.name, InputArtifact.version, InputArtifact.status,
    InputArtifact.size_bytes, InputArtifact.sha256, InputArtifact.content_type, InputArtifact.url, InputArtifact.notes,
    InputArtifact.findings, InputArtifact.rejection_code, InputArtifact.rejection_detail, InputArtifact.uploaded_by,
    AppUser.display_name.label("uploaded_by_name"), InputArtifact.created_at,
)  # fmt: skip


def _query() -> Any:
    return select(*COLUMNS).outerjoin(AppUser, AppUser.id == InputArtifact.uploaded_by)


async def _project(conn: AsyncConnection, project_id: uuid.UUID) -> None:
    if (await conn.execute(select(Project.id).where(Project.id == project_id))).first() is None:
        raise not_found("project")


async def _load(conn: AsyncConnection, project_id: uuid.UUID, input_id: uuid.UUID) -> InputOut:
    row = (
        await conn.execute(_query().where(InputArtifact.id == input_id, InputArtifact.project_id == project_id))
    ).one_or_none()
    if row is None:
        raise not_found("input")
    return InputOut.model_validate(row, from_attributes=True)


async def _next_version(conn: AsyncConnection, project_id: uuid.UUID, kind: str, name: str) -> int:
    current = (
        await conn.execute(
            select(func.max(InputArtifact.version)).where(
                InputArtifact.project_id == project_id, InputArtifact.kind == kind, InputArtifact.name == name
            )
        )
    ).scalar_one()
    return int(current or 0) + 1


async def _record_rejection(
    request: Request, auth: Authorized, project_id: uuid.UUID, kind: str, name: str, rejection: Rejection, **extra: Any
) -> ProblemError:
    async with transaction(request, auth) as conn:
        input_id: uuid.UUID = (
            await conn.execute(
                insert(InputArtifact)
                .values(
                    tenant_id=auth.tenant_id, project_id=project_id, kind=kind, name=name, status="rejected",
                    rejection_code=rejection.code, rejection_detail=rejection.detail, uploaded_by=auth.user_id,
                    **extra,
                )
                .returning(InputArtifact.id)
            )
        ).scalar_one()  # fmt: skip
        await audit(
            conn, auth, "input.reject", f"project:{project_id}",
            {"input_id": str(input_id), "kind": kind, "name": name, "code": rejection.code}, outcome="failure",
        )  # fmt: skip
    return ProblemError(422, rejection.code, rejection.detail, inputId=str(input_id))


@router.get("", response_model=list[InputOut])
async def list_inputs(request: Request, project_id: uuid.UUID, auth: ViewProject) -> list[InputOut]:
    """Every input with its versions, including rejected uploads (why) and deleted ones (when)."""
    async with transaction(request, auth) as conn:
        await _project(conn, project_id)
        rows = (
            await conn.execute(
                _query()
                .where(InputArtifact.project_id == project_id, InputArtifact.dismissed_at.is_(None))
                .order_by(InputArtifact.kind, InputArtifact.name, InputArtifact.created_at.desc())
            )
        ).all()
    return [InputOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("", response_model=InputOut, status_code=201)
async def upload_input(
    request: Request,
    project_id: uuid.UUID,
    auth: UploadInputs,
    file: Annotated[list[UploadFile], File()],
    kind: Annotated[FileKind, Form()],
    notes: Annotated[str, Form(max_length=2000)] = "",
) -> InputOut:
    """Validate (type, size, zip safety, image header, secrets, malware, hash) and store. 422 with the reason on
    rejection; 503 when the scanner does not answer (fail closed, ADR-0008). A code input takes one zip or loose
    code files, which are packed into one zip and validated like an uploaded archive."""
    store, scanner, limits = services.store(request), services.scanner(request), services.services(request).limits
    name = safe_name(file[0].filename or "") if file else ""
    async with transaction(request, auth) as conn:
        await _project(conn, project_id)
    try:
        if kind in CODE_KINDS:
            stream, name = as_upload([(safe_name(f.filename or ""), f.file) for f in file], limits, kind)
            checked_name = name if name.lower().endswith(".zip") else f"{name}.zip"
        elif len(file) != 1:
            raise Rejection("one_file_only", "This kind of input takes one file at a time.")
        else:
            stream, checked_name = file[0].file, name
        accepted = await validate(stream, checked_name, kind, limits, scanner)
    except ScannerUnavailableError as exc:
        raise ProblemError(
            503, "malware_scanner_unavailable", "The malware scanner is not available; try later."
        ) from exc
    except Rejection as rejection:
        raise await _record_rejection(request, auth, project_id, kind, name, rejection) from None

    input_id = uuid.uuid4()
    key = input_key(auth.tenant_id, project_id, input_id)  # type: ignore[arg-type]
    await store.put(key, stream, accepted.size_bytes, accepted.content_type)
    try:
        async with transaction(request, auth) as conn:
            version = await _next_version(conn, project_id, kind, name)
            await conn.execute(
                insert(InputArtifact).values(
                    id=input_id, tenant_id=auth.tenant_id, project_id=project_id, kind=kind, name=name,
                    version=version, status="accepted", object_key=key, size_bytes=accepted.size_bytes,
                    sha256=accepted.sha256, content_type=accepted.content_type, notes=notes,
                    findings=accepted.findings, uploaded_by=auth.user_id,
                )
            )  # fmt: skip
            await audit(
                conn, auth, "input.upload", f"project:{project_id}",
                {"input_id": str(input_id), "kind": kind, "name": name, "version": version,
                 "sha256": accepted.sha256, "flagged_findings": accepted.findings.get("secrets", {}).get("total", 0)},
            )  # fmt: skip
            return await _load(conn, project_id, input_id)
    except IntegrityError as exc:
        await store.delete(key)
        raise ProblemError(409, "input_version_conflict", "Another upload of the same input finished first.") from exc


@router.post(":link", response_model=InputOut, status_code=201)
async def add_link(request: Request, project_id: uuid.UUID, body: LinkIn, auth: UploadInputs) -> InputOut:
    """A Figma link (figma.com/file|design|proto) or a prototype link (https) with notes of what to respect."""
    async with transaction(request, auth) as conn:
        await _project(conn, project_id)
    try:
        link = figma_link(body.url) if body.kind == "figma_link" else prototype_link(body.url)
    except Rejection as rejection:
        raise await _record_rejection(
            request, auth, project_id, body.kind, safe_name(body.url)[:255], rejection, url=body.url[:2000]
        ) from None
    input_id = uuid.uuid4()
    async with transaction(request, auth) as conn:
        version = await _next_version(conn, project_id, body.kind, link.name)
        await conn.execute(
            insert(InputArtifact).values(
                id=input_id, tenant_id=auth.tenant_id, project_id=project_id, kind=body.kind, name=link.name,
                version=version, status="accepted", url=link.url, notes=body.notes, uploaded_by=auth.user_id,
            )
        )  # fmt: skip
        await audit(
            conn, auth, "input.link", f"project:{project_id}",
            {"input_id": str(input_id), "kind": body.kind, "url": link.url, "version": version},
        )  # fmt: skip
        return await _load(conn, project_id, input_id)


@router.get("/{input_id}/content")
async def input_content(
    request: Request, project_id: uuid.UUID, input_id: uuid.UUID, auth: ViewProject
) -> StreamingResponse:
    """The stored file. Code archives need code.download; images are served inline for thumbnails, everything else as
    an attachment, and nothing is ever sniffed or executed by the browser."""
    async with transaction(request, auth) as conn:
        row = (
            await conn.execute(
                select(InputArtifact.kind, InputArtifact.status, InputArtifact.object_key, InputArtifact.content_type,
                       InputArtifact.name, InputArtifact.version)
                .where(InputArtifact.id == input_id, InputArtifact.project_id == project_id)
            )
        ).one_or_none()  # fmt: skip
    if row is None or row.status != "accepted" or row.object_key is None:
        raise not_found("input")
    if row.kind in ("source_archive", "target_archive"):
        obj = names.project(project_id)
        if not await request.app.state.fga.check(names.user(auth.user_id), "code_download", obj):
            await deny(request, auth.session, auth.tenant_id, "code.download", obj)
    chunks = await services.store(request).read(row.object_key)
    inline = row.kind == "screenshot"
    filename = safe_name(row.name).replace('"', "")
    headers = {
        "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "private, max-age=300",
    }
    media = row.content_type if inline else "application/octet-stream"
    return StreamingResponse(chunks, media_type=media, headers=headers)


@router.delete("/{input_id}", status_code=204)
async def delete_input(request: Request, project_id: uuid.UUID, input_id: uuid.UUID, auth: UploadInputs) -> None:
    """Remove the stored file (verifiable deletion, 15.3); the record stays, marked deleted, for the audit trail. A
    rejected upload (nothing was stored) is dismissed from the list; its rejection stays in the audit log."""
    async with transaction(request, auth) as conn:
        found = await _load(conn, project_id, input_id)
        if found.status == "rejected":
            await conn.execute(update(InputArtifact).where(InputArtifact.id == input_id)
                               .values(dismissed_at=datetime.now(UTC)))  # fmt: skip
            await audit(conn, auth, "input.dismiss", f"project:{project_id}",
                        {"input_id": str(input_id), "kind": found.kind, "name": found.name})  # fmt: skip
            return
        if found.status != "accepted":
            raise ProblemError(409, "input_not_active", "Only an accepted input can be deleted.")
        key = (await conn.execute(select(InputArtifact.object_key).where(InputArtifact.id == input_id))).scalar()
        await conn.execute(
            update(InputArtifact)
            .where(InputArtifact.id == input_id)
            .values(status="deleted", object_key=None, deleted_at=datetime.now(UTC))
        )
        await audit(
            conn, auth, "input.delete", f"project:{project_id}",
            {"input_id": str(input_id), "kind": found.kind, "name": found.name, "version": found.version},
        )  # fmt: skip
    if key:
        await services.store(request).delete(key)
