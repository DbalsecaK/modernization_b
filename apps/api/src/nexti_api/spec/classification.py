"""The classification of the legacy's statements (spec 6.1 phase 4): which ones are business logic, control flow or
infrastructure, and why. The classification phase stores it as a generated artifact; this module only reads it. It
describes the code's structure like the graph does, so seeing the project is enough."""

import json
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import transaction
from nexti_api.authz.require import Authorized, require_project
from nexti_api.projects import services
from nexti_api.schemas import ApiModel

router = APIRouter(prefix="/api/v1/projects/{project_id}/classification", tags=["graph"])
ViewProject = Annotated[Authorized, Depends(require_project("project.view"))]
PATH = "inventory/classification.json"
COVERAGE = "inventory/coverage.json"


class ClassifiedStatementOut(ApiModel):
    unit: str
    file: str
    line_start: int
    line_end: int
    statement: str
    label: Literal["business", "control_flow", "infrastructure"]
    reason: str
    in_slice: bool | None = None  # business statements, once the rules were extracted: an agent read it
    cited: bool | None = None  # and a rule cites it


class StatementCoverageOut(ApiModel):
    business: int
    not_sliced: int
    not_cited: int


class ClassificationOut(ApiModel):
    counts: dict[str, int]
    statements: list[ClassifiedStatementOut]
    coverage: StatementCoverageOut | None = None


@router.get("", response_model=ClassificationOut | None)
async def get_classification(request: Request, project_id: uuid.UUID, auth: ViewProject) -> ClassificationOut | None:
    """The newest classification, or nothing before the classification phase."""
    async with transaction(request, auth) as conn:
        key = await newest(conn, project_id, PATH)
        coverage_key = await newest(conn, project_id, COVERAGE)
    if key is None:
        return None
    document = json.loads(b"".join(await services.store(request).read(key)))
    if coverage_key is not None:
        found = json.loads(b"".join(await services.store(request).read(coverage_key)))
        flags = {(c["file"], c["line_start"], c["line_end"]): c for c in found.get("statements", [])}
        for statement in document.get("statements", []):
            flag = flags.get((statement["file"], statement["line_start"], statement["line_end"]))
            if flag is not None:
                statement["in_slice"], statement["cited"] = flag["in_slice"], flag["cited"]
        document["coverage"] = {k: found.get(k, 0) for k in ("business", "not_sliced", "not_cited")}
    return ClassificationOut.model_validate(document)


async def newest(conn: AsyncConnection, project_id: uuid.UUID, path: str) -> str | None:
    key: str | None = (
        await conn.execute(
            text("SELECT object_key FROM generated_artifact WHERE project_id = :p AND path = :path "
                 "ORDER BY created_at DESC LIMIT 1"),
            {"p": project_id, "path": path},
        )
    ).scalar_one_or_none()  # fmt: skip
    return key


async def coverage_warnings(request: Request, conn: AsyncConnection, project_id: uuid.UUID) -> list[str]:
    """For the review before C1: business statements no slice reached or no rule cites (a warning, not a blocker:
    a person decides whether they hold business logic the specification is missing)."""
    key = await newest(conn, project_id, COVERAGE)
    if key is None:
        return []
    found = json.loads(b"".join(await services.store(request).read(key)))
    statements = found.get("statements", [])
    unread = [str(c["line_start"]) for c in statements if not c["in_slice"]]
    uncited = [str(c["line_start"]) for c in statements if c["in_slice"] and not c["cited"]]
    warnings = []
    for count, lines, what in ((found.get("not_sliced", 0), unread, "reached no slice"),
                               (found.get("not_cited", 0), uncited, "are cited by no rule")):  # fmt: skip
        if count:
            shown = ", ".join(lines[:15]) + ("…" if len(lines) > 15 else "")
            warnings.append(f"{count} of {found.get('business', 0)} business statement(s) {what} (lines {shown})")
    return warnings
