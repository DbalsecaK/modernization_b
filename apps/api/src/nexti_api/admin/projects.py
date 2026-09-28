"""Projects the user can see in the active tenant (minimal in M0; CRUD and wizard are M2)."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from nexti_api.admin.common import transaction
from nexti_api.authz import names
from nexti_api.authz.require import Authorized, require_tenant
from nexti_api.db.models import Project
from nexti_api.schemas import ApiModel

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


class ProjectOut(ApiModel):
    id: uuid.UUID
    name: str
    status: Literal["active", "archived"]


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    request: Request, auth: Annotated[Authorized, Depends(require_tenant("tenant.view"))]
) -> list[ProjectOut]:
    """OpenFGA answers which projects the user may see (ListObjects); RLS keeps it to the active tenant."""
    visible = await request.app.state.fga.list_objects(names.user(auth.user_id), "viewer", "project")
    ids = [uuid.UUID(obj.split(":", 1)[1]) for obj in visible]
    if not ids:
        return []
    async with transaction(request, auth) as conn:
        rows = (
            await conn.execute(
                select(Project.id, Project.name, Project.status).where(Project.id.in_(ids)).order_by(Project.name)
            )
        ).all()
    return [ProjectOut(id=r.id, name=r.name, status=r.status) for r in rows]
