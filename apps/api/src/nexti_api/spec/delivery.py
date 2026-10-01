"""Hardening and delivery of a project (spec 6.1 phases 12 and 13, ADR-0023), as the web shows them:

- the hardening report of the newest generation (`code.view`);
- the releases of the project: pushed to a branch of the customer's repository, failed, or left as a ZIP (`code.view`);
- a push from the Code tab (`code.push`): the files the tab shows go to a new `nexti/` branch of the project's
  repository, on top of its base branch, never to the base branch. The token comes from the secrets store and never
  reaches the browser, the database nor the audit log.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncConnection

import nexti_delivery
from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz.require import Authorized, require_project
from nexti_api.errors import ProblemError
from nexti_api.projects import services
from nexti_api.schemas import ApiModel
from nexti_api.spec.code import _files
from nexti_core.db.models import ProjectRepository, Release
from nexti_core.secrets import SecretsConfig, SecretStore
from nexti_core.spec.design import Design
from nexti_ingest import Rejection
from nexti_ingest.git import ensure_public_host

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["code"])
ViewCode = Annotated[Authorized, Depends(require_project("code.view"))]
PushCode = Annotated[Authorized, Depends(require_project("code.push"))]


class HardeningCheckOut(ApiModel):
    kind: str
    status: Literal["checked", "not_checked"]
    detail: str


class HardeningFindingOut(ApiModel):
    kind: str
    severity: Literal["critical", "high", "medium", "low"]
    rule: str
    file: str
    line: int | None
    message: str


class HardeningOut(ApiModel):
    run_id: uuid.UUID
    generated_at: datetime
    counts: dict[str, int]
    checks: list[HardeningCheckOut]
    findings: list[HardeningFindingOut]


class ReleaseOut(ApiModel):
    id: uuid.UUID
    run_id: uuid.UUID | None
    kind: Literal["push", "zip"]
    status: Literal["pushed", "failed", "ready"]
    repository_url: str | None
    branch: str | None
    commit_sha: str | None
    files: int
    findings: dict[str, int]
    error: str | None
    created_at: datetime


def _release_out(row: Any) -> ReleaseOut:
    return ReleaseOut(id=row.id, run_id=row.run_id, kind=row.kind, status=row.status,
                      repository_url=row.repository_url, branch=row.branch, commit_sha=row.commit_sha,
                      files=row.files, findings=dict(row.findings or {}), error=row.error,
                      created_at=row.created_at)  # fmt: skip


@router.get("/hardening", response_model=HardeningOut | None)
async def hardening_report(request: Request, project_id: uuid.UUID, auth: ViewCode) -> HardeningOut | None:
    async with transaction(request, auth) as conn:
        row = (
            await conn.execute(
                text("SELECT run_id, object_key, created_at FROM generated_artifact WHERE project_id = :p "
                     "AND path = 'hardening/report.json' ORDER BY created_at DESC LIMIT 1"), {"p": project_id})
        ).first()  # fmt: skip
    if row is None:
        return None
    report = json.loads(b"".join(await services.store(request).read(row.object_key)))
    return HardeningOut.model_validate({"run_id": row.run_id, "generated_at": row.created_at, **report})


@router.get("/releases", response_model=list[ReleaseOut])
async def releases(request: Request, project_id: uuid.UUID, auth: ViewCode) -> list[ReleaseOut]:
    async with transaction(request, auth) as conn:
        rows = await conn.execute(select(Release).where(Release.project_id == project_id)
                                  .order_by(Release.created_at.desc()).limit(50))  # fmt: skip
        return [_release_out(r) for r in rows.all()]


async def _token(request: Request, vault_path: str | None) -> str | None:
    settings = request.app.state.settings
    if not vault_path or not settings.secrets_url:
        return None
    config = SecretsConfig(settings.secrets_url, settings.secrets_token.get_secret_value(), settings.secrets_mount)
    return await SecretStore(config, request.app.state.resources.http).get(vault_path)


async def _design(request: Request, conn: AsyncConnection, project_id: uuid.UUID) -> Design | None:
    key = (
        await conn.execute(text("SELECT object_key FROM generated_artifact WHERE project_id = :p "
                                "AND path = 'design/design.json' ORDER BY created_at DESC LIMIT 1"), {"p": project_id})
    ).scalar()  # fmt: skip
    if key is None:
        return None
    return Design.model_validate_json(b"".join(await services.store(request).read(key)))


@router.post("/code:push", response_model=ReleaseOut, status_code=201)
async def push_code(request: Request, project_id: uuid.UUID, auth: PushCode) -> ReleaseOut:
    """The files of the Code tab to a new `nexti/` branch of the project's repository."""
    assert auth.tenant_id is not None  # noqa: S101
    async with transaction(request, auth) as conn:
        repository = (
            await conn.execute(select(ProjectRepository).where(ProjectRepository.project_id == project_id))
        ).first()  # fmt: skip
        if repository is None:
            raise ProblemError(409, "repository_missing", "Link the customer's repository in Settings first.")
        files = await _files(conn, project_id)
        if not files:
            raise not_found("code")
        design = await _design(request, conn, project_id)
    store = services.store(request)
    contents = {f["path"]: b"".join(await store.read(f["object_key"])).decode("utf-8", "replace") for f in files}
    report = contents.get("hardening/report.json")
    findings = {str(k): int(v) for k, v in json.loads(report).get("counts", {}).items()} if report else {}
    context = design.context if design else "project"
    branch = nexti_delivery.branch_name(f"push-{datetime.now(UTC):%Y%m%d-%H%M%S}")
    settings = request.app.state.settings

    async def ensure(url: str) -> None:
        if settings.git_allow_private_hosts and settings.is_local:
            return
        try:
            await ensure_public_host(url, services.services(request).git_resolver)
        except Rejection as rejection:
            raise nexti_delivery.PushError(rejection.detail) from None

    status, commit, base, error = "pushed", None, None, None
    try:
        pushed = await nexti_delivery.push_release(
            repository.url, await _token(request, repository.vault_path), repository.branch or "main", branch,
            f"{nexti_delivery.RELEASE_PREFIX}/{context}", contents,
            f"NexTI release of {context}\n\nPushed from the Code tab of the NexTI platform.", ensure,
            loopback_http=settings.git_allow_private_hosts and settings.is_local,
        )  # fmt: skip
        commit, base = pushed.commit, pushed.base
    except nexti_delivery.PushError as exc:
        status, error = "failed", str(exc)[:500]
    async with transaction(request, auth) as conn:
        release_id = uuid.uuid4()
        await conn.execute(insert(Release).values(
            id=release_id, tenant_id=auth.tenant_id, project_id=project_id, run_id=files[0]["run_id"], kind="push",
            status=status, repository_url=repository.url, branch=branch, commit_sha=commit, base_sha=base,
            files=len(contents), findings=findings, error=error, created_by=auth.user_id,
        ))  # fmt: skip
        await audit(conn, auth, "code.push", f"project:{project_id}",
                    {"branch": branch, "commit": commit, "files": len(contents), "status": status},
                    outcome="success" if status == "pushed" else "failure")  # fmt: skip
        row = (await conn.execute(select(Release).where(Release.id == release_id))).one()
    if status == "failed":
        raise ProblemError(502, "push_failed", f"The repository did not take the release: {error}")
    return _release_out(row)
