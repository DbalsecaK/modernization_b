"""The knowledge graph of a project (spec 5, 5.2.1): read-only, through packages/graph (the single access layer
with the tenant and project filters, 5.3). The code layer is written by the worker's inventory; the API reads it
and adds, by code, the rules, the migration state and the business flows."""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy import text

from nexti_api.admin.common import transaction
from nexti_api.authz.require import Authorized, require_project
from nexti_api.errors import ProblemError
from nexti_api.graph.view import VIEW_TYPES, RuleRef, build, lift
from nexti_api.schemas import ApiModel
from nexti_graph import GraphError, GraphStore, Scope

router = APIRouter(prefix="/api/v1/projects/{project_id}/graph", tags=["graph"])
ViewProject = Annotated[Authorized, Depends(require_project("project.view"))]
NodeType = Literal["transaction", "program", "map", "copybook", "file"]


class GraphNodeOut(ApiModel):
    id: str
    name: str
    type: NodeType
    domain: str
    state: Literal["verified", "generated", "inProgress", "pending"]
    loc: int | None
    rules: list[str]
    source: str | None
    file: str | None
    line_start: int | None
    line_end: int | None
    external: bool
    orphan: bool
    kind: str = Field(default="", description="What the unit is: StoredProcedure, Program, Table, Page, ...")


class GraphEdgeOut(ApiModel):
    from_: str = Field(alias="from", serialization_alias="from")
    to: str
    kind: Literal["STARTS", "CALLS", "READS", "WRITES", "COPIES", "USES_MAP"]
    detail: str | None = Field(default=None, description="The kind of call (LINK, XCTL, CALL) when there is one")


class GraphRuleOut(ApiModel):
    id: str
    name: str
    priority: str


class FlowStepOut(ApiModel):
    kind: Literal["start", "screen", "read", "write", "call", "transfer"]
    nodes: list[str]
    rule: str | None


class BusinessFlowOut(ApiModel):
    id: str
    name: str
    entry: str
    rules: list[str]
    steps: list[FlowStepOut]


class GraphOut(ApiModel):
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]
    rules: list[GraphRuleOut]
    flows: list[BusinessFlowOut]


class ImpactOut(ApiModel):
    node: str
    depth: int
    impacted: list[str] = Field(description="The units that may break if the node changes (who uses it)")


def _graph(request: Request) -> GraphStore:
    graph: GraphStore | None = getattr(request.app.state, "graph", None)
    if graph is None:
        raise ProblemError(503, "graph_unavailable", "The knowledge graph is not configured.")
    return graph


async def _context(request: Request, project_id: uuid.UUID, auth: Authorized) -> tuple[list[RuleRef], set[str], bool]:
    async with transaction(request, auth) as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT DISTINCT ON (key) key, status, data FROM spec_element WHERE project_id = :p "
                    "AND element_type = 'rule' ORDER BY key, version DESC"
                ),
                {"p": project_id},
            )
        ).mappings()
        rules = [
            RuleRef(r["key"], str(r["data"].get("name", "")), str(r["data"].get("priority", "")),
                    tuple((s["file"], int(s["line_start"]), int(s["line_end"])) for s in r["data"].get("sources", [])))
            for r in rows if r["status"] != "obsolete"
        ]  # fmt: skip
        generated: set[str] = set(
            (await conn.execute(
                text("SELECT DISTINCT jsonb_array_elements_text(rules) FROM generated_artifact WHERE project_id = :p"),
                {"p": project_id},
            )).scalars()
        )  # fmt: skip
        verified = bool(
            (
                await conn.execute(
                    text("SELECT EXISTS (SELECT 1 FROM verdict WHERE project_id = :p AND verdict <> 'NOT PROVEN')"),
                    {"p": project_id},
                )
            ).scalar()
        )
    return rules, generated, verified


def _scope(auth: Authorized, project_id: uuid.UUID) -> Scope:
    if auth.tenant_id is None:
        raise ProblemError(404, "project_not_found", "The project does not exist.")
    return Scope(auth.tenant_id, project_id)


@router.get("", response_model=GraphOut, response_model_by_alias=True)
async def project_graph(request: Request, project_id: uuid.UUID, auth: ViewProject) -> dict[str, Any]:
    """The code units with their relations, rules, migration state, orphans and business flows."""
    graph = _graph(request)
    rules, generated, verified = await _context(request, project_id, auth)
    scope = _scope(auth, project_id)
    nodes = await graph.nodes(scope)
    relationships = await graph.relationships(scope)
    orphans = await graph.orphans(scope)
    return build(nodes, relationships, orphans, rules, generated, verified)


@router.get("/impact", response_model=ImpactOut)
async def impact(
    request: Request, project_id: uuid.UUID, auth: ViewProject,
    node: Annotated[str, Query(min_length=3, max_length=300)], depth: Annotated[int, Query(ge=1, le=6)] = 3,
) -> ImpactOut:  # fmt: skip
    """What may break if the node changes (5.2): the units that use it, up to `depth` hops."""
    graph = _graph(request)
    scope = _scope(auth, project_id)
    nodes = await graph.nodes(scope)
    view_ids = {n.key for n in nodes if set(n.labels) & set(VIEW_TYPES)}
    if node not in {n.key for n in nodes}:
        raise ProblemError(404, "node_not_found", "The node is not in the graph of this project.")
    try:
        keys = await graph.impact(scope, node, depth)
    except GraphError as exc:
        raise ProblemError(422, "invalid_impact", str(exc)) from exc
    return ImpactOut(node=node, depth=depth, impacted=[k for k in lift(keys, view_ids) if k != node])
