"""Validation and traceability of a project (spec 11.3, 11.6, 18.x "Validación" and "Origen ↔ destino"): the verdicts
the worker computed by code, their proof packs, and rule by rule the legacy lines, the generated files and the
behaviour of both sides in the golden master and fresh inputs.

Read only: verdicts are evidence written by the worker (a person signs off at C4 through the gates). Showing code
needs `code.view` besides seeing the project; the verdict summary needs only `project.view`."""

import io
import json
import uuid
import zipfile
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import not_found, transaction
from nexti_api.authz.require import Authorized, require_project
from nexti_api.projects import services
from nexti_api.spec.schemas import (
    CaseOut,
    CodeExcerptOut,
    TraceDetailOut,
    TraceRuleOut,
    VerdictOut,
)
from nexti_ingest.archive import read_text_files

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["validation"])
ViewProject = Annotated[Authorized, Depends(require_project("project.view"))]
ViewCode = Annotated[Authorized, Depends(require_project("code.view"))]
CONTEXT_LINES = 3
MAX_EXCERPT_LINES = 400
MAX_TARGET_FILES = 4


async def _verdicts(conn: AsyncConnection, project_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await conn.execute(
        text("SELECT id, run_id, module, verdict, checks, not_proven, proof_pack_key, created_at FROM verdict "
             "WHERE project_id = :p ORDER BY created_at DESC"),
        {"p": project_id},
    )  # fmt: skip
    return [dict(r) for r in rows.mappings()]


@router.get("/verdicts", response_model=list[VerdictOut])
async def list_verdicts(request: Request, project_id: uuid.UUID, auth: ViewProject) -> list[VerdictOut]:
    async with transaction(request, auth) as conn:
        rows = await _verdicts(conn, project_id)
    return [VerdictOut.model_validate({**r, "has_proof_pack": bool(r["proof_pack_key"])}) for r in rows]


@router.get("/verdicts/{verdict_id}/proof-pack")
async def proof_pack(request: Request, project_id: uuid.UUID, verdict_id: uuid.UUID, auth: ViewCode) -> Response:
    """The evidence of a verdict as the worker stored it (a zip a reviewer can keep and recompute)."""
    async with transaction(request, auth) as conn:
        key = (
            await conn.execute(
                text("SELECT proof_pack_key FROM verdict WHERE id = :v AND project_id = :p"),
                {"v": verdict_id, "p": project_id},
            )
        ).scalar_one_or_none()
    if not key:
        raise not_found("proof pack")
    data = b"".join(await services.store(request).read(key))
    headers = {
        "Content-Disposition": f'attachment; filename="proof-pack-{verdict_id}.zip"',
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "private, max-age=300",
    }
    return Response(data, media_type="application/zip", headers=headers)


async def _evidence(request: Request, conn: AsyncConnection, project_id: uuid.UUID) -> dict[str, Any]:
    """TRACE and EQUIVALENCE of the newest verdict, or nothing when the project has not been verified yet."""
    verdicts = await _verdicts(conn, project_id)
    latest = next((v for v in verdicts if v["proof_pack_key"] and not v["module"].startswith("frontend-")), None)
    if latest is None:
        return {}
    data = b"".join(await services.store(request).read(latest["proof_pack_key"]))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        trace = json.loads(archive.read("TRACE.json"))
        equivalence = json.loads(archive.read("EQUIVALENCE.json"))
    cases = list(equivalence.get("golden_master") or []) + list(equivalence.get("fresh_inputs") or [])
    return {"verdict": latest, "trace": {t["rule"]: t for t in trace}, "cases": cases}


async def _rules(conn: AsyncConnection, project_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await conn.execute(
        text("SELECT DISTINCT ON (key) key, status, data FROM spec_element WHERE project_id = :p "
             "AND element_type = 'rule' ORDER BY key, version DESC"),
        {"p": project_id},
    )  # fmt: skip
    return [dict(r) for r in rows.mappings() if r["status"] != "obsolete"]


async def _artifacts(conn: AsyncConnection, project_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await conn.execute(
        text("SELECT DISTINCT ON (path) path, layer, object_key, rules FROM generated_artifact WHERE project_id = :p "
             "AND path NOT LIKE 'design/%' AND path NOT LIKE 'characterization/%' ORDER BY path, created_at DESC"),
        {"p": project_id},
    )  # fmt: skip
    return [dict(r) for r in rows.mappings()]


def _sources(rule: dict[str, Any]) -> list[str]:
    return [f"{s['file']}:{s['line_start']}-{s['line_end']}" for s in rule["data"].get("sources", [])]


@router.get("/traceability", response_model=list[TraceRuleOut])
async def traceability(request: Request, project_id: uuid.UUID, auth: ViewCode) -> list[TraceRuleOut]:
    async with transaction(request, auth) as conn:
        rules = await _rules(conn, project_id)
        artifacts = await _artifacts(conn, project_id)
        evidence = await _evidence(request, conn, project_id)
    trace = evidence.get("trace", {})
    result = []
    for rule in rules:
        traced = trace.get(rule["key"])
        cases = [c for c in evidence.get("cases", []) if rule["key"] in c.get("rules", [])]
        result.append(TraceRuleOut(
            key=rule["key"], name=rule["data"].get("name", ""), priority=rule["data"].get("priority", ""),
            status=rule["status"], sources=_sources(rule),
            target_files=sorted(a["path"] for a in artifacts if rule["key"] in (a["rules"] or [])),
            cases=len(cases), matched=sum(1 for c in cases if c.get("matched")),
            verified=traced["verified"] if traced else None,
        ))  # fmt: skip
    return result


async def _legacy_files(request: Request, conn: AsyncConnection, project_id: uuid.UUID) -> dict[str, str]:
    rows = await conn.execute(
        text("SELECT DISTINCT ON (name) name, object_key FROM input_artifact WHERE project_id = :p "
             "AND kind = 'source_archive' AND status = 'accepted' AND deleted_at IS NULL ORDER BY name, version DESC"),
        {"p": project_id},
    )  # fmt: skip
    files: dict[str, str] = {}
    for row in rows.mappings():
        data = b"".join(await services.store(request).read(row["object_key"]))
        files.update(read_text_files(data))
    return files


def _find(files: dict[str, str], name: str) -> str | None:
    if name in files:
        return name
    return next((path for path in files if path.rsplit("/", 1)[-1] == name.rsplit("/", 1)[-1]), None)


def _excerpt(path: str, content: str, highlighted: list[int], around: tuple[int, int] | None) -> CodeExcerptOut:
    lines = content.split("\n")
    first, last = (1, len(lines)) if around is None else (max(1, around[0] - CONTEXT_LINES),
                                                          min(len(lines), around[1] + CONTEXT_LINES))  # fmt: skip
    last = min(last, first + MAX_EXCERPT_LINES - 1)
    return CodeExcerptOut(path=path, first_line=first, lines=lines[first - 1 : last], highlighted=highlighted,
                          truncated=last < (len(lines) if around is None else min(len(lines), around[1])))  # fmt: skip


@router.get("/traceability/{rule_key}", response_model=TraceDetailOut)
async def rule_trace(request: Request, project_id: uuid.UUID, rule_key: str, auth: ViewCode) -> TraceDetailOut:
    async with transaction(request, auth) as conn:
        rule = next((r for r in await _rules(conn, project_id) if r["key"] == rule_key), None)
        if rule is None:
            raise not_found("rule")
        artifacts = [a for a in await _artifacts(conn, project_id) if rule_key in (a["rules"] or [])]
        legacy_files = await _legacy_files(request, conn, project_id)
        evidence = await _evidence(request, conn, project_id)
    legacy = []
    for source in rule["data"].get("sources", []):
        path = _find(legacy_files, source["file"])
        if path is not None:
            span = list(range(source["line_start"], source["line_end"] + 1))
            legacy.append(_excerpt(path, legacy_files[path], span, (source["line_start"], source["line_end"])))
    target = []
    store = services.store(request)
    for artifact in artifacts[:MAX_TARGET_FILES]:
        content = b"".join(await store.read(artifact["object_key"])).decode("utf-8", "replace")
        marked = [n for n, line in enumerate(content.split("\n"), start=1) if rule_key in line]
        target.append(_excerpt(artifact["path"], content, marked, None))
    cases = [CaseOut(name=c["name"], matched=bool(c.get("matched")), failure=c.get("failure"),
                     differences=c.get("differences", [])) for c in evidence.get("cases", [])
             if rule_key in c.get("rules", [])]  # fmt: skip
    traced = evidence.get("trace", {}).get(rule_key)
    verdict = evidence.get("verdict")
    return TraceDetailOut(
        key=rule_key, rule=rule["data"], status=rule["status"], legacy=legacy, target=target, cases=cases,
        verified=traced["verified"] if traced else None, verdict=verdict["verdict"] if verdict else None,
    )  # fmt: skip
