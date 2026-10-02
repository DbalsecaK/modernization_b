"""The independent validation of a third party's target (Flow 4, ADR-0025): what the worker read of the target, the
mapping between the legacy's contract and the target's, the gaps a person must close before C2, the rule comparison
and the report.

The mapping is the one document a person changes here: it is checked by code against the golden master and the
target's inventory, saved as a new version (`ivv_mapping_version`, newer than the intake's artifact) and audited.
Problems do not block saving (a person may save part of the work); the validation fails `contract_mapped` while any
remains. The target's structure is
code, so reading needs `code.view`; changing the mapping is part of approving C2."""

import hashlib
import io
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from yaml import YAMLError

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz.require import Authorized, require_project
from nexti_api.errors import ProblemError
from nexti_api.projects import services
from nexti_api.spec.schemas import IvvMappingIn, IvvOut
from nexti_core.spec.characterization import GoldenMaster
from nexti_ivv import mapping as ivv_mapping
from nexti_ivv.target import TargetInventory

router = APIRouter(prefix="/api/v1/projects/{project_id}/ivv", tags=["validation"])
ViewCode = Annotated[Authorized, Depends(require_project("code.view"))]
ApproveC2 = Annotated[Authorized, Depends(require_project("gate.c2.approve"))]

INVENTORY = "ivv/target-inventory.json"
MAPPING = "ivv/mapping.yaml"
GAPS = "ivv/mapping-gaps.json"
COMPARISON = "ivv/rules-comparison.json"
REPORT = "ivv/REPORT.md"
GOLDEN = "characterization/golden_master.json"
MAX_MAPPING_BYTES = 512 * 1024


async def _rows(conn: AsyncConnection, project_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    rows = (
        await conn.execute(
            text("SELECT DISTINCT ON (path) id, path, object_key, created_at FROM generated_artifact "
                 "WHERE project_id = :p AND path = ANY(:paths) ORDER BY path, created_at DESC"),
            {"p": project_id, "paths": [INVENTORY, MAPPING, GAPS, COMPARISON, REPORT, GOLDEN]},
        )
    ).mappings().all()  # fmt: skip
    found = {row["path"]: dict(row) for row in rows}
    edited = (
        await conn.execute(
            text("SELECT version, object_key, created_at FROM ivv_mapping_version WHERE project_id = :p "
                 "ORDER BY version DESC LIMIT 1"),
            {"p": project_id},
        )
    ).mappings().one_or_none()  # fmt: skip
    if edited is not None and MAPPING in found and edited["created_at"] >= found[MAPPING]["created_at"]:
        found[MAPPING] = {**dict(edited), "path": MAPPING}  # a person's correction after the newest intake
    return found


async def _text(request: Request, row: dict[str, Any] | None) -> str | None:
    if row is None:
        return None
    return b"".join(await services.store(request).read(row["object_key"])).decode("utf-8")


async def _problems(request: Request, rows: dict[str, dict[str, Any]], mapping: ivv_mapping.Mapping) -> list[str]:
    inventory, golden = await _text(request, rows.get(INVENTORY)), await _text(request, rows.get(GOLDEN))
    if inventory is None:
        return ["The target has not been taken in yet"]
    if golden is None:
        return ["There is no golden master of the legacy yet"]
    master = GoldenMaster.model_validate_json(golden)
    return ivv_mapping.problems(mapping, master, TargetInventory.from_dict(json.loads(inventory)))


async def _out(request: Request, rows: dict[str, dict[str, Any]]) -> IvvOut:
    inventory, mapping_text = await _text(request, rows.get(INVENTORY)), await _text(request, rows.get(MAPPING))
    gaps, comparison = await _text(request, rows.get(GAPS)), await _text(request, rows.get(COMPARISON))
    problems: list[str] = []
    if mapping_text is not None:
        try:
            problems = await _problems(request, rows, ivv_mapping.load(mapping_text))
        except (YAMLError, ValidationError) as error:
            problems = [f"The mapping cannot be read: {str(error)[:300]}"]
    return IvvOut(
        inventory=json.loads(inventory) if inventory else None, mapping=mapping_text,
        mapping_updated_at=rows[MAPPING]["created_at"] if MAPPING in rows else None,
        gaps=json.loads(gaps) if gaps else [], problems=problems,
        comparison=json.loads(comparison) if comparison else None, report=await _text(request, rows.get(REPORT)),
    )  # fmt: skip


@router.get("", response_model=IvvOut)
async def get_ivv(request: Request, project_id: uuid.UUID, auth: ViewCode) -> IvvOut:
    """Everything the independent validation produced so far (empty before the target intake)."""
    async with transaction(request, auth) as conn:
        rows = await _rows(conn, project_id)
    return await _out(request, rows)


@router.put("/mapping", response_model=IvvOut)
async def change_mapping(request: Request, project_id: uuid.UUID, body: IvvMappingIn, auth: ApproveC2) -> IvvOut:
    """A person corrects the mapping before approving C2; it must be valid YAML of the mapping's shape."""
    data = body.mapping.encode("utf-8")
    if len(data) > MAX_MAPPING_BYTES:
        raise ProblemError(413, "mapping_too_large", "The mapping is larger than 512 KB.")
    try:
        mapping = ivv_mapping.load(body.mapping)
    except (YAMLError, ValidationError) as error:
        raise ProblemError(422, "invalid_mapping", f"The mapping cannot be read: {str(error)[:500]}") from error
    async with transaction(request, auth) as conn:
        rows = await _rows(conn, project_id)
        current = rows.get(MAPPING)
        if current is None:
            raise not_found("ivv_mapping")
        text_ = ivv_mapping.dump(mapping)
        content = text_.encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        key = f"tenants/{auth.tenant_id}/projects/{project_id}/ivv/mapping-{uuid.uuid4()}.yaml"
        await services.store(request).put(key, io.BytesIO(content), len(content), "text/plain; charset=utf-8")
        rows[MAPPING] = {**current, "object_key": key}
        problems = await _problems(request, rows, mapping)
        version: int = (
            await conn.execute(
                text("INSERT INTO ivv_mapping_version (tenant_id, project_id, version, object_key, sha256, size_bytes, "
                     "problems, created_by) SELECT :t, :p, coalesce(max(version), 0) + 1, :k, :h, :s, :n, :by "
                     "FROM ivv_mapping_version WHERE project_id = :p RETURNING version"),
                {"t": auth.tenant_id, "p": project_id, "k": key, "h": digest, "s": len(content), "n": len(problems),
                 "by": auth.user_id},
            )
        ).scalar_one()  # fmt: skip
        details = {"version": version, "sha256": digest, "programs": [p.legacy for p in mapping.programs],
                   "problems": len(problems)}  # fmt: skip
        await audit(conn, auth, "ivv.mapping.change", f"project:{project_id}", details)
        rows = await _rows(conn, project_id)
    return await _out(request, rows)
