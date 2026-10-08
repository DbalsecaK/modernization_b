"""How a project's legacy runs for the golden master (ADR-0052): automatic, recorded traces or a live system of the
customer (an IBM i). The system's address is kept in the table, its credentials only in the secrets store (ADR-0007),
written here and never returned. Testing the connection opens a TCP connection to the system's host server port,
with the same guard against internal addresses as the tenant's tools (SSRF); signing on is the worker's, at run
time (R2b)."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field, model_validator
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz.require import Authorized, require_project
from nexti_api.errors import ProblemError
from nexti_api.projects import services
from nexti_api.projects.repository import secret_store
from nexti_api.schemas import ApiModel
from nexti_core.db.models import Project, ProjectLegacyExecution
from nexti_core.legacy_execution import Credentials, Kind, Mode, checked_config
from nexti_core.secrets import legacy_path
from nexti_ingest import Rejection
from nexti_ingest.git import ensure_public_host

router = APIRouter(prefix="/api/v1/projects/{project_id}/legacy-execution", tags=["inputs"])
ViewProject = Annotated[Authorized, Depends(require_project("project.view"))]
ConfigureProject = Annotated[Authorized, Depends(require_project("project.configure"))]
CONNECT_SECONDS = 5.0


class LegacyExecutionOut(ApiModel):
    mode: Mode
    kind: Kind | None
    config: dict[str, Any]
    has_credentials: bool
    status: Literal["untested", "ok", "failed"]
    last_checked_at: datetime | None
    last_check_detail: str | None


class LegacyExecutionIn(ApiModel):
    mode: Mode
    kind: Kind | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    # New credentials replace the stored ones; omit both to keep them, or set clear_credentials to remove them.
    user: str | None = Field(default=None, min_length=1, max_length=128)
    password: str | None = Field(default=None, min_length=1, max_length=256)
    clear_credentials: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> "LegacyExecutionIn":
        if self.mode == "live" and self.kind is None:
            raise ValueError("a live legacy needs the kind of system it runs on")
        if (self.user is None) != (self.password is None):
            raise ValueError("user and password go together")
        return self


async def _reach(host: str, port: int) -> None:
    """Opens and closes a TCP connection: the host server answers. Raises OSError or TimeoutError."""
    _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), CONNECT_SECONDS)
    writer.close()
    await writer.wait_closed()


async def _row(request: Request, auth: Authorized, project_id: uuid.UUID) -> Any:
    async with transaction(request, auth) as conn:
        if (await conn.execute(select(Project.id).where(Project.id == project_id))).first() is None:
            raise not_found("project")
        query = select(ProjectLegacyExecution).where(ProjectLegacyExecution.project_id == project_id)
        return (await conn.execute(query)).first()


def _out(row: Any) -> LegacyExecutionOut:
    return LegacyExecutionOut(
        mode=row.mode, kind=row.kind, config=row.config or {}, has_credentials=row.vault_path is not None,
        status=row.status, last_checked_at=row.last_checked_at, last_check_detail=row.last_check_detail,
    )  # fmt: skip


@router.get("", response_model=LegacyExecutionOut | None)
async def get_legacy_execution(request: Request, project_id: uuid.UUID, auth: ViewProject) -> LegacyExecutionOut | None:
    row = await _row(request, auth, project_id)
    return _out(row) if row else None


@router.put("", response_model=LegacyExecutionOut)
async def set_legacy_execution(
    request: Request, project_id: uuid.UUID, body: LegacyExecutionIn, auth: ConfigureProject
) -> LegacyExecutionOut:
    assert auth.tenant_id is not None  # noqa: S101
    config: dict[str, Any] = {}
    if body.kind is not None:
        try:
            config = checked_config(body.kind, body.config)
        except ValueError as exc:
            raise ProblemError(422, "invalid_legacy_config", str(exc)) from None
    current = await _row(request, auth, project_id)
    vault_path = current.vault_path if current else None
    if body.user is not None and body.password is not None:
        path = legacy_path(auth.tenant_id, project_id)
        await secret_store(request).put(path, Credentials(user=body.user, password=body.password).model_dump_json())
        vault_path = path
    elif body.clear_credentials and vault_path:
        await secret_store(request).delete(vault_path)
        vault_path = None
    values = {"mode": body.mode, "kind": body.kind, "config": config, "vault_path": vault_path, "status": "untested",
              "last_checked_at": None, "last_check_detail": None}  # fmt: skip
    async with transaction(request, auth) as conn:
        await conn.execute(
            pg_insert(ProjectLegacyExecution)
            .values(tenant_id=auth.tenant_id, project_id=project_id, created_by=auth.user_id, **values)
            .on_conflict_do_update(index_elements=["project_id"], set_=values)
        )
        await audit(
            conn, auth, "legacy_execution.set", f"project:{project_id}",
            {"mode": body.mode, "kind": body.kind, "host": config.get("host"), "library": config.get("library"),
             "access_updated": body.user is not None, "access_removed": body.clear_credentials},
        )  # fmt: skip
    row = await _row(request, auth, project_id)
    assert row is not None  # noqa: S101
    return _out(row)


@router.post(":test", response_model=LegacyExecutionOut)
async def test_legacy_execution(request: Request, project_id: uuid.UUID, auth: ConfigureProject) -> LegacyExecutionOut:
    row = await _row(request, auth, project_id)
    if row is None:
        raise not_found("legacy_execution")
    rejection: Rejection | None = None
    if row.mode != "live" or not row.config:
        ok, detail = True, "nothing to connect to: the legacy is observed from its inputs or recorded traces"
    else:
        host, port = str(row.config["host"]), int(row.config["port"])
        try:
            await ensure_public_host(
                f"https://{host}:{port}/", services.services(request).git_resolver,
                allow_private_hosts=request.app.state.settings.legacy_allow_private_hosts,
            )  # fmt: skip
            await _reach(host, port)
            ok, detail = True, f"{host}:{port} answers"
            if row.vault_path is None:
                ok, detail = False, f"{host}:{port} answers, but there are no credentials to sign on"
        except Rejection as exc:
            rejection, ok, detail = exc, False, exc.detail
        except (OSError, TimeoutError):
            ok, detail = False, f"{host}:{port} does not answer"
    async with transaction(request, auth) as conn:
        await conn.execute(
            update(ProjectLegacyExecution)
            .where(ProjectLegacyExecution.project_id == project_id)
            .values(status="ok" if ok else "failed", last_checked_at=datetime.now(UTC), last_check_detail=detail)
        )
        await audit(
            conn, auth, "legacy_execution.test", f"project:{project_id}",
            {"ok": ok, "code": rejection.code if rejection else None}, outcome="success" if ok else "failure",
        )  # fmt: skip
    if rejection is not None:
        raise ProblemError(422, rejection.code, rejection.detail)
    updated = await _row(request, auth, project_id)
    assert updated is not None  # noqa: S101
    return _out(updated)


@router.delete("", status_code=204)
async def delete_legacy_execution(request: Request, project_id: uuid.UUID, auth: ConfigureProject) -> None:
    row = await _row(request, auth, project_id)
    if row is None:
        raise not_found("legacy_execution")
    async with transaction(request, auth) as conn:
        await conn.execute(delete(ProjectLegacyExecution).where(ProjectLegacyExecution.project_id == project_id))
        await audit(conn, auth, "legacy_execution.delete", f"project:{project_id}", {"mode": row.mode})
    if row.vault_path:
        await secret_store(request).delete(row.vault_path)
