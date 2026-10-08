"""The Git repository of a project (spec 7.1): URL, branch and a token kept in the secrets store (ADR-0007; this is
the only API module that uses the secrets client). Testing the connection reads the refs over HTTPS without SSRF;
cloning happens in the pipeline's preflight inside the sandbox (M3)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz.require import Authorized, require_project
from nexti_api.errors import ProblemError
from nexti_api.projects import services
from nexti_api.schemas import ApiModel
from nexti_core.db.models import Project, ProjectRepository
from nexti_core.secrets import SecretsConfig, SecretStore, repository_path
from nexti_ingest import Rejection
from nexti_ingest.git import check_repository, validate_repository_url

router = APIRouter(prefix="/api/v1/projects/{project_id}/repository", tags=["inputs"])
ViewProject = Annotated[Authorized, Depends(require_project("project.view"))]
UploadInputs = Annotated[Authorized, Depends(require_project("input.upload"))]


class RepositoryOut(ApiModel):
    url: str
    branch: str
    has_token: bool
    status: Literal["untested", "ok", "failed"]
    last_checked_at: datetime | None
    last_check_detail: str | None
    branches: list[str] = Field(default_factory=list)


class RepositoryIn(ApiModel):
    url: str = Field(min_length=9, max_length=500)
    branch: str = Field(default="main", min_length=1, max_length=255, pattern=r"^[^\s~^:?*\[\\]+$")
    # A new token replaces the stored one; omit it to keep the current one, or set clear_token to remove it.
    token: str | None = Field(default=None, min_length=8, max_length=500)
    clear_token: bool = False


def secret_store(request: Request) -> SecretStore:
    settings = request.app.state.settings
    if not settings.secrets_url:
        raise ProblemError(503, "secrets_unavailable", "The secrets store is not configured.")
    config = SecretsConfig(settings.secrets_url, settings.secrets_token.get_secret_value(), settings.secrets_mount)
    return SecretStore(config, request.app.state.resources.http)


async def repository_token(request: Request, vault_path: str | None) -> str | None:
    """The token of the project's repository, for a push of the delivery (ADR-0023); never returned to a client."""
    if not vault_path or not request.app.state.settings.secrets_url:
        return None
    return await secret_store(request).get(vault_path)


async def _row(request: Request, auth: Authorized, project_id: uuid.UUID) -> Any:
    async with transaction(request, auth) as conn:
        if (await conn.execute(select(Project.id).where(Project.id == project_id))).first() is None:
            raise not_found("project")
        row = (await conn.execute(select(ProjectRepository).where(ProjectRepository.project_id == project_id))).first()
    return row


def _out(row: Any, branches: list[str] | None = None) -> RepositoryOut:
    return RepositoryOut(
        url=row.url, branch=row.branch, has_token=row.vault_path is not None, status=row.status,
        last_checked_at=row.last_checked_at, last_check_detail=row.last_check_detail, branches=branches or [],
    )  # fmt: skip


@router.get("", response_model=RepositoryOut | None)
async def get_repository(request: Request, project_id: uuid.UUID, auth: ViewProject) -> RepositoryOut | None:
    row = await _row(request, auth, project_id)
    return _out(row) if row else None


@router.put("", response_model=RepositoryOut)
async def set_repository(
    request: Request, project_id: uuid.UUID, body: RepositoryIn, auth: UploadInputs
) -> RepositoryOut:
    assert auth.tenant_id is not None  # noqa: S101
    try:
        url = validate_repository_url(body.url)
    except Rejection as rejection:
        raise ProblemError(422, rejection.code, rejection.detail) from None
    current = await _row(request, auth, project_id)
    vault_path = current.vault_path if current else None
    path = repository_path(auth.tenant_id, project_id)
    if body.token:
        await secret_store(request).put(path, body.token)
        vault_path = path
    elif body.clear_token and vault_path:
        await secret_store(request).delete(vault_path)
        vault_path = None
    values = {"url": url, "branch": body.branch, "vault_path": vault_path, "status": "untested",
              "last_checked_at": None, "last_check_detail": None}  # fmt: skip
    async with transaction(request, auth) as conn:
        await conn.execute(
            pg_insert(ProjectRepository)
            .values(tenant_id=auth.tenant_id, project_id=project_id, created_by=auth.user_id, **values)
            .on_conflict_do_update(index_elements=["project_id"], set_=values)
        )
        await audit(
            conn, auth, "repository.set", f"project:{project_id}",
            {"url": url, "branch": body.branch, "access_updated": bool(body.token), "access_removed": body.clear_token},
        )  # fmt: skip
    row = await _row(request, auth, project_id)
    assert row is not None  # noqa: S101
    return _out(row)


@router.post(":test", response_model=RepositoryOut)
async def test_repository(request: Request, project_id: uuid.UUID, auth: UploadInputs) -> RepositoryOut:
    row = await _row(request, auth, project_id)
    if row is None:
        raise not_found("repository")
    token = await secret_store(request).get(row.vault_path) if row.vault_path else None
    settings = request.app.state.settings
    rejection: Rejection | None = None
    branches: list[str] = []
    try:
        check = await check_repository(
            row.url, row.branch, token, request.app.state.resources.http, services.services(request).git_resolver,
            allow_private_hosts=settings.git_allow_private_hosts and settings.is_local,
        )  # fmt: skip
        ok, detail, branches = check.ok, check.detail, check.branches
    except Rejection as exc:
        rejection, ok, detail = exc, False, exc.detail
    async with transaction(request, auth) as conn:
        await conn.execute(
            update(ProjectRepository)
            .where(ProjectRepository.project_id == project_id)
            .values(status="ok" if ok else "failed", last_checked_at=datetime.now(UTC), last_check_detail=detail)
        )
        await audit(
            conn, auth, "repository.test", f"project:{project_id}",
            {"ok": ok, "code": rejection.code if rejection else None}, outcome="success" if ok else "failure",
        )  # fmt: skip
    if rejection is not None:
        raise ProblemError(422, rejection.code, rejection.detail)
    updated = await _row(request, auth, project_id)
    assert updated is not None  # noqa: S101
    return _out(updated, branches)


@router.delete("", status_code=204)
async def delete_repository(request: Request, project_id: uuid.UUID, auth: UploadInputs) -> None:
    row = await _row(request, auth, project_id)
    if row is None:
        raise not_found("repository")
    async with transaction(request, auth) as conn:
        await conn.execute(delete(ProjectRepository).where(ProjectRepository.project_id == project_id))
        await audit(conn, auth, "repository.delete", f"project:{project_id}", {"url": row.url})
    if row.vault_path:
        await secret_store(request).delete(row.vault_path)
