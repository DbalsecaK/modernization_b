"""The generated code of a project (spec 18.3, tab "Código"): the file tree of the newest generation, one file at a
time, and the whole project as a zip.

Files come from `generated_artifact` rows written by the worker; a path asked by the client is only looked up in that
table, never used to build a storage key. Reading needs `code.view`; the zip needs `code.download` and is audited.
Pushing to Git is the delivery phase of the pipeline (spec 6.1 phase 13), not an action of this tab."""

import io
import uuid
import zipfile
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz.require import Authorized, require_project
from nexti_api.projects import services
from nexti_api.spec.schemas import CodeFileOut, CodeTreeOut

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["code"])
ViewCode = Annotated[Authorized, Depends(require_project("code.view"))]
DownloadCode = Annotated[Authorized, Depends(require_project("code.download"))]
MAX_FILE_BYTES = 512 * 1024
# Working material of the pipeline, not part of the delivered project.
INTERNAL = ("design/", "characterization/")


async def _files(conn: AsyncConnection, project_id: uuid.UUID) -> list[dict[str, Any]]:
    """The files of the newest run that generated code, sorted by path."""
    rows = await conn.execute(
        text("SELECT run_id, layer, path, object_key, size_bytes, rules, created_at FROM generated_artifact "
             "WHERE project_id = :p AND run_id = (SELECT run_id FROM generated_artifact WHERE project_id = :p "
             "AND path NOT LIKE 'design/%' AND path NOT LIKE 'characterization/%' ORDER BY created_at DESC LIMIT 1) "
             "ORDER BY path"),
        {"p": project_id},
    )  # fmt: skip
    return [dict(r) for r in rows.mappings() if not r["path"].startswith(INTERNAL)]


@router.get("/code", response_model=CodeTreeOut | None)
async def code_tree(request: Request, project_id: uuid.UUID, auth: ViewCode) -> CodeTreeOut | None:
    async with transaction(request, auth) as conn:
        files = await _files(conn, project_id)
    if not files:
        return None
    return CodeTreeOut.model_validate({
        "run_id": files[0]["run_id"],
        "generated_at": max(f["created_at"] for f in files),
        "files": [{"path": f["path"], "layer": f["layer"], "size_bytes": f["size_bytes"], "rules": f["rules"] or []}
                  for f in files],
    })  # fmt: skip


@router.get("/code/file", response_model=CodeFileOut)
async def code_file(
    request: Request, project_id: uuid.UUID, auth: ViewCode, path: Annotated[str, Query(max_length=500)]
) -> CodeFileOut:
    async with transaction(request, auth) as conn:
        found = next((f for f in await _files(conn, project_id) if f["path"] == path), None)
    if found is None:
        raise not_found("file")
    data = b"".join(await services.store(request).read(found["object_key"]))
    truncated = len(data) > MAX_FILE_BYTES
    return CodeFileOut(path=found["path"], layer=found["layer"], size_bytes=found["size_bytes"],
                       content=data[:MAX_FILE_BYTES].decode("utf-8", "replace"), truncated=truncated)  # fmt: skip


@router.get("/code:download")
async def code_download(request: Request, project_id: uuid.UUID, auth: DownloadCode) -> Response:
    """The generated project as a zip, the same files the tree shows."""
    async with transaction(request, auth) as conn:
        files = await _files(conn, project_id)
        if not files:
            raise not_found("code")
        await audit(conn, auth, "code.download", f"project:{project_id}",
                    {"run_id": str(files[0]["run_id"]), "files": len(files)})  # fmt: skip
    store = services.store(request)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for f in files:
            archive.writestr(f["path"], b"".join(await store.read(f["object_key"])))
    headers = {
        "Content-Disposition": f'attachment; filename="code-{files[0]["run_id"]}.zip"',
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "private, no-store",
    }
    return Response(buffer.getvalue(), media_type="application/zip", headers=headers)
