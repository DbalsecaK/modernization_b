"""The classification of the legacy's statements (spec 6.1 phase 4): which ones are business logic, control flow or
infrastructure, and why. The classification phase stores it as a generated artifact; this module only reads it. It
describes the code's structure like the graph does, so seeing the project is enough."""

import json
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from nexti_api.admin.common import transaction
from nexti_api.authz.require import Authorized, require_project
from nexti_api.projects import services
from nexti_api.schemas import ApiModel

router = APIRouter(prefix="/api/v1/projects/{project_id}/classification", tags=["graph"])
ViewProject = Annotated[Authorized, Depends(require_project("project.view"))]
PATH = "inventory/classification.json"


class ClassifiedStatementOut(ApiModel):
    unit: str
    file: str
    line_start: int
    line_end: int
    statement: str
    label: Literal["business", "control_flow", "infrastructure"]
    reason: str


class ClassificationOut(ApiModel):
    counts: dict[str, int]
    statements: list[ClassifiedStatementOut]


@router.get("", response_model=ClassificationOut | None)
async def get_classification(request: Request, project_id: uuid.UUID, auth: ViewProject) -> ClassificationOut | None:
    """The newest classification, or nothing before the classification phase."""
    async with transaction(request, auth) as conn:
        key = (
            await conn.execute(
                text("SELECT object_key FROM generated_artifact WHERE project_id = :p AND path = :path "
                     "ORDER BY created_at DESC LIMIT 1"),
                {"p": project_id, "path": PATH},
            )
        ).scalar_one_or_none()  # fmt: skip
    if key is None:
        return None
    document = json.loads(b"".join(await services.store(request).read(key)))
    return ClassificationOut.model_validate(document)
