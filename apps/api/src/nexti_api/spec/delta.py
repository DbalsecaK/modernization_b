"""The delta added to an existing application (Flow 3, ADR-0026): what the worker read of the application (its AS-IS
inventory), the baseline of its own tests, the design of the delta approved at C3, the files of the delta and the
DELTA.md report. Everything is read-only here; the application's structure is code, so reading needs `code.view`."""

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import transaction
from nexti_api.authz.require import Authorized, require_project
from nexti_api.projects import services
from nexti_api.spec.schemas import DeltaOut

router = APIRouter(prefix="/api/v1/projects/{project_id}/delta", tags=["validation"])
ViewCode = Annotated[Authorized, Depends(require_project("code.view"))]

AS_IS = "delta/as-is-inventory.json"
BASELINE = "delta/baseline.json"
DESIGN = "delta/design.json"
INDEX = "delta/index.json"
REPORT = "delta/DELTA.md"


async def _rows(conn: AsyncConnection, project_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    rows = (
        await conn.execute(
            text("SELECT DISTINCT ON (path) path, object_key, created_at FROM generated_artifact "
                 "WHERE project_id = :p AND path = ANY(:paths) ORDER BY path, created_at DESC"),
            {"p": project_id, "paths": [AS_IS, BASELINE, DESIGN, INDEX, REPORT]},
        )
    ).mappings().all()  # fmt: skip
    return {row["path"]: dict(row) for row in rows}


async def _text(request: Request, row: dict[str, Any] | None) -> str | None:
    if row is None:
        return None
    return b"".join(await services.store(request).read(row["object_key"])).decode("utf-8")


@router.get("", response_model=DeltaOut)
async def get_delta(request: Request, project_id: uuid.UUID, auth: ViewCode) -> DeltaOut:
    """Everything Flow 3 produced so far (empty before the inventory)."""
    async with transaction(request, auth) as conn:
        rows = await _rows(conn, project_id)
    inventory, baseline = await _text(request, rows.get(AS_IS)), await _text(request, rows.get(BASELINE))
    design, index = await _text(request, rows.get(DESIGN)), await _text(request, rows.get(INDEX))
    changes = json.loads(index) if index else {"added": [], "changed": []}
    return DeltaOut(
        inventory=json.loads(inventory) if inventory else None,
        baseline=json.loads(baseline) if baseline else None,
        design=json.loads(design) if design else None,
        added=list(changes["added"]), changed=list(changes["changed"]),
        report=await _text(request, rows.get(REPORT)),
    )  # fmt: skip
