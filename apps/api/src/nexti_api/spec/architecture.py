"""The architecture of a project's target (spec 18.3, tab "Arquitectura", and the "contratos" view of the
specification): the design approved at C3 and the HTTP contract derived from it.

Both are documents the worker stored as generated artifacts (`design/design.json`, and the frontend's
`openapi.json` from M6b); this module only reads them. They describe the target, not its code, so seeing the project
is enough."""

import json
import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import transaction
from nexti_api.authz.require import Authorized, require_project
from nexti_api.projects import services
from nexti_api.spec.schemas import ContractsOut, DesignOut, OperationOut

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["architecture"])
ViewProject = Annotated[Authorized, Depends(require_project("project.view"))]
HTTP_METHODS = ("get", "post", "put", "patch", "delete")


async def _newest(conn: AsyncConnection, project_id: uuid.UUID, pattern: str) -> dict[str, Any] | None:
    row = (
        await conn.execute(
            text("SELECT run_id, object_key, created_at FROM generated_artifact WHERE project_id = :p "
                 "AND path LIKE :pattern ORDER BY created_at DESC LIMIT 1"),
            {"p": project_id, "pattern": pattern},
        )
    ).mappings().one_or_none()  # fmt: skip
    return dict(row) if row else None


async def _document(request: Request, row: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(b"".join(await services.store(request).read(row["object_key"])))
    return data


@router.get("/design", response_model=DesignOut | None)
async def design(request: Request, project_id: uuid.UUID, auth: ViewProject) -> DesignOut | None:
    """The newest design, or nothing before the design phase."""
    async with transaction(request, auth) as conn:
        row = await _newest(conn, project_id, "design/design.json")
    if row is None:
        return None
    return DesignOut.model_validate({**await _document(request, row), "run_id": row["run_id"],
                                     "created_at": row["created_at"]})  # fmt: skip


def _operations(document: dict[str, Any]) -> list[OperationOut]:
    return [
        OperationOut(method=method.upper(), path=path, name=operation.get("operationId", ""),
                     summary=operation.get("summary", ""), rules=list(operation.get("x-rules", [])))
        for path, item in document.get("paths", {}).items()
        for method, operation in item.items() if method in HTTP_METHODS
    ]  # fmt: skip


def _path(context: str, use_case: dict[str, Any]) -> str:
    """The path the generated controller maps (the packs' rule): /api/{context}{path or /kebab-of-name}."""
    name = re.sub(r"(?<!^)(?=[A-Z])", "-", use_case["name"]).lower()
    return f"/api/{context}{use_case.get('path') or '/' + name}"


@router.get("/contracts", response_model=ContractsOut | None)
async def contracts(request: Request, project_id: uuid.UUID, auth: ViewProject) -> ContractsOut | None:
    """The newest OpenAPI document, else the operations of the newest design, else nothing."""
    async with transaction(request, auth) as conn:
        spec = await _newest(conn, project_id, "frontend/%openapi.json")
        found = spec or await _newest(conn, project_id, "design/design.json")
    if found is None:
        return None
    document = await _document(request, found)
    if spec is not None:
        return ContractsOut(source="openapi", operations=_operations(document), openapi=document)
    context = document.get("context", "")
    operations = [
        OperationOut(method=u.get("http_method", "POST"), path=_path(context, u), name=u["name"],
                     summary=u.get("description", ""), rules=list(u.get("rules", [])))
        for u in document.get("use_cases", [])
    ]  # fmt: skip
    return ContractsOut(source="design", operations=operations, openapi=None)
