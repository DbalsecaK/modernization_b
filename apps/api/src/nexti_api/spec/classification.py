"""The classification of the legacy's statements (spec 6.1 phase 4): which ones are business logic, control flow or
infrastructure, and why. The classification phase stores it as a generated artifact; this module reads it. It
describes the code's structure like the graph does, so seeing the project is enough.

A reviewer may classify a business statement again (ADR-0056): one no rule cites blocks C1, and when it is plumbing
(the message of a failure the business never sees, a trace) the person says so with a reason. The decision is kept
apart from the phase's artifact, with its author and in the audit chain, and applies when the classification and the
coverage are read."""

import json
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import audit, transaction
from nexti_api.authz.require import Authorized, require_project
from nexti_api.errors import ProblemError
from nexti_api.projects import services
from nexti_api.schemas import ApiModel
from nexti_api.spec.schemas import UncitedStatementOut

router = APIRouter(prefix="/api/v1/projects/{project_id}/classification", tags=["graph"])
ViewProject = Annotated[Authorized, Depends(require_project("project.view"))]
# The people who shape the specification reviewed at C1 (business reviewer, leader, analyst).
EditSpec = Annotated[Authorized, Depends(require_project("story.edit"))]
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
    overridden_by: str | None = None  # a person classified it again (the label is theirs), for this reason
    override_reason: str | None = None


class StatementRef(ApiModel):
    file: str = Field(min_length=1, max_length=500)
    line_start: int = Field(gt=0)
    line_end: int = Field(gt=0)


class OverrideIn(ApiModel):
    statements: list[StatementRef] = Field(min_length=1, max_length=200)
    label: Literal["infrastructure", "control_flow"] = "infrastructure"
    reason: str = Field(min_length=10, max_length=2000)


class OverrideOut(StatementRef):
    label: str
    reason: str
    created_by: str | None = None
    created_at: str


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
        decided = await _overrides(conn, project_id)
    if key is None:
        return None
    document = json.loads(b"".join(await services.store(request).read(key)))
    if coverage_key is not None:
        found = _apply(json.loads(b"".join(await services.store(request).read(coverage_key))), decided)
        flags = {(c["file"], c["line_start"], c["line_end"]): c for c in found.get("statements", [])}
        for statement in document.get("statements", []):
            flag = flags.get((statement["file"], statement["line_start"], statement["line_end"]))
            if flag is not None:
                statement["in_slice"], statement["cited"] = flag["in_slice"], flag["cited"]
        document["coverage"] = {k: found.get(k, 0) for k in ("business", "not_sliced", "not_cited")}
    counts: dict[str, int] = dict(document.get("counts", {}))
    for statement in document.get("statements", []):
        override = decided.get((statement["file"], statement["line_start"], statement["line_end"]))
        if override is not None and override["label"] != statement["label"]:
            counts[statement["label"]] = max(0, counts.get(statement["label"], 0) - 1)
            counts[override["label"]] = counts.get(override["label"], 0) + 1
            statement.update(label=override["label"], in_slice=None, cited=None, overridden_by=override["by"],
                             override_reason=override["reason"])  # fmt: skip
    document["counts"] = counts
    return ClassificationOut.model_validate(document)


@router.get("/overrides", response_model=list[OverrideOut])
async def list_overrides(request: Request, project_id: uuid.UUID, auth: ViewProject) -> list[OverrideOut]:
    """The statements people classified again, newest first."""
    async with transaction(request, auth) as conn:
        return await _override_list(conn, project_id)


@router.post("/overrides", response_model=list[OverrideOut], status_code=201)
async def classify_again(
    request: Request, project_id: uuid.UUID, body: OverrideIn, auth: EditSpec
) -> list[OverrideOut]:
    """Classify business statements as infrastructure (or control flow), with a reason: they stop blocking C1. Only
    statements the classification has as business can be classified again; the decision is audited."""
    async with transaction(request, auth) as conn:
        key = await newest(conn, project_id, PATH)
    if key is None:
        raise ProblemError(409, "no_classification", "The legacy's statements are not classified yet.")
    document = json.loads(b"".join(await services.store(request).read(key)))
    business = {(s["file"], s["line_start"], s["line_end"]) for s in document.get("statements", [])
                if s["label"] == "business"}  # fmt: skip
    wanted = [(s.file, s.line_start, s.line_end) for s in body.statements]
    unknown = [f"{f}:{a}" for f, a, b in wanted if (f, a, b) not in business]
    if unknown:
        raise ProblemError(422, "not_business", f"Only business statements can be classified again: "
                           f"{', '.join(unknown[:10])}.", statements=unknown)  # fmt: skip
    reason = body.reason.strip()
    async with transaction(request, auth) as conn:
        for file, start, end in wanted:
            await conn.execute(
                text("INSERT INTO statement_override (tenant_id, project_id, file, line_start, line_end, label, "
                     "reason, created_by) VALUES (:t, :p, :f, :a, :b, :l, :r, :by) "
                     "ON CONFLICT (project_id, file, line_start, line_end) DO UPDATE SET label = EXCLUDED.label, "
                     "reason = EXCLUDED.reason, created_by = EXCLUDED.created_by, created_at = now()"),
                {"t": auth.tenant_id, "p": project_id, "f": file, "a": start, "b": end, "l": body.label,
                 "r": reason, "by": auth.user_id},
            )  # fmt: skip
        await audit(
            conn,
            auth,
            "statement.classify",
            f"project:{project_id}",
            {"label": body.label, "reason": reason, "statements": [f"{f}:{a}-{b}" for f, a, b in wanted]},
        )
        return await _override_list(conn, project_id)


@router.delete("/overrides", response_model=list[OverrideOut])
async def undo_override(
    request: Request, project_id: uuid.UUID, file: str, line_start: int, line_end: int, auth: EditSpec
) -> list[OverrideOut]:
    """Give a statement back the classification the phase gave it."""
    async with transaction(request, auth) as conn:
        gone = (
            await conn.execute(
                text("DELETE FROM statement_override WHERE project_id = :p AND file = :f AND line_start = :a "
                     "AND line_end = :b"),
                {"p": project_id, "f": file, "a": line_start, "b": line_end},
            )
        ).rowcount  # fmt: skip
        if gone:
            await audit(conn, auth, "statement.unclassify", f"project:{project_id}",
                        {"statement": f"{file}:{line_start}-{line_end}"})  # fmt: skip
        return await _override_list(conn, project_id)


async def _override_rows(conn: AsyncConnection, project_id: uuid.UUID) -> list[Any]:
    return list(
        (
            await conn.execute(
                text("SELECT o.file, o.line_start, o.line_end, o.label, o.reason, u.display_name AS by, o.created_at "
                     "FROM statement_override o LEFT JOIN app_user u ON u.id = o.created_by "
                     "WHERE o.project_id = :p ORDER BY o.created_at DESC"),
                {"p": project_id},
            )
        ).all()
    )  # fmt: skip


async def _override_list(conn: AsyncConnection, project_id: uuid.UUID) -> list[OverrideOut]:
    return [
        OverrideOut(
            file=r.file,
            line_start=r.line_start,
            line_end=r.line_end,
            label=r.label,
            reason=r.reason,
            created_by=r.by,
            created_at=r.created_at.isoformat(),
        )
        for r in await _override_rows(conn, project_id)
    ]


async def _overrides(conn: AsyncConnection, project_id: uuid.UUID) -> dict[tuple[str, int, int], dict[str, str]]:
    return {(r.file, r.line_start, r.line_end): {"label": r.label, "reason": r.reason, "by": str(r.by or "")}
            for r in await _override_rows(conn, project_id)}  # fmt: skip


def _apply(found: dict[str, Any], decided: dict[tuple[str, int, int], dict[str, str]]) -> dict[str, Any]:
    """The coverage without the statements a person classified as something other than business."""
    if not decided:
        return found
    statements = [s for s in found.get("statements", []) if (s["file"], s["line_start"], s["line_end"]) not in decided]
    return {
        **found,
        "statements": statements,
        "business": found.get("business", 0) - (len(found.get("statements", [])) - len(statements)),
        "not_sliced": sum(1 for s in statements if not s["in_slice"]),
        "not_cited": sum(1 for s in statements if s["in_slice"] and not s["cited"]),
    }


async def newest(conn: AsyncConnection, project_id: uuid.UUID, path: str) -> str | None:
    key: str | None = (
        await conn.execute(
            text("SELECT object_key FROM generated_artifact WHERE project_id = :p AND path = :path "
                 "ORDER BY created_at DESC LIMIT 1"),
            {"p": project_id, "path": path},
        )
    ).scalar_one_or_none()  # fmt: skip
    return key


async def _coverage(request: Request, conn: AsyncConnection, project_id: uuid.UUID) -> dict[str, Any] | None:
    key = await newest(conn, project_id, COVERAGE)
    if key is None:
        return None
    found: dict[str, Any] = json.loads(b"".join(await services.store(request).read(key)))
    return _apply(found, await _overrides(conn, project_id))


async def uncited(request: Request, conn: AsyncConnection, project_id: uuid.UUID) -> list[UncitedStatementOut]:
    """The business statements no rule cites, with their unit, for the review of C1."""
    found = await _coverage(request, conn, project_id)
    if found is None:
        return []
    return [
        UncitedStatementOut(
            file=c["file"], line_start=c["line_start"], line_end=c["line_end"], unit=c.get("unit") or None
        )
        for c in found.get("statements", [])
        if c["in_slice"] and not c["cited"]
    ]


def _shown(lines: list[str]) -> str:
    return ", ".join(lines[:15]) + ("…" if len(lines) > 15 else "")


async def coverage_warnings(request: Request, conn: AsyncConnection, project_id: uuid.UUID) -> list[str]:
    """For the review before C1: business statements no slice reached (a warning: a person decides whether they
    hold business logic the specification is missing) and the warnings of the guided extraction."""
    found = await _coverage(request, conn, project_id)
    if found is None:
        return []
    statements = found.get("statements", [])
    unread = [f"{c['file']}:{c['line_start']}" for c in statements if not c["in_slice"]]
    warnings = []
    if found.get("not_sliced", 0):
        warnings.append(f"{found['not_sliced']} of {found.get('business', 0)} business statement(s) reached no "
                        f"slice ({_shown(unread)})")  # fmt: skip
    # Guided extraction (ADR-0033): too many P0 rules, instruction-shaped text in the source.
    return warnings + [str(w) for w in found.get("warnings", [])]


async def coverage_blockers(request: Request, conn: AsyncConnection, project_id: uuid.UUID) -> list[str]:
    """Why C1 cannot be approved by the coverage of the rules (ADR-0056): a business statement no rule cites is a
    behaviour no rule asks the target to reproduce, so the golden master cannot be asked to prove it. The rules are
    extracted again citing it, or the statement is classified as infrastructure; a person does not approve past
    it."""
    found = await _coverage(request, conn, project_id)
    if found is None or not found.get("not_cited", 0):
        return []
    statements = found.get("statements", [])
    shown = [f"{c['file']}:{c['line_start']}" for c in statements if c["in_slice"] and not c["cited"]]
    return [f"{found['not_cited']} of {found.get('business', 0)} business statement(s) are cited by no rule "
            f"({_shown(shown)}): extract the rules again so each one is cited, or classify the statement as "
            "infrastructure"]  # fmt: skip
