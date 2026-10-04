"""Model-written reading aids of the knowledge graph (ADR-0032, spec 4.1 and 5.2.1): the description of every unit and
block, the architect's observations and the business flows by scenario. The worker writes them as generated artifacts
when the run has the `deep_inventory` option; this module only reads the newest ones. They describe the code's
structure like the graph does, so seeing the project is enough. Everything is empty when no run wrote them."""

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import text

from nexti_api.admin.common import transaction
from nexti_api.authz.require import Authorized, require_project
from nexti_api.projects import services
from nexti_api.schemas import ApiModel

router = APIRouter(prefix="/api/v1/projects/{project_id}/graph/insights", tags=["graph"])
ViewProject = Annotated[Authorized, Depends(require_project("project.view"))]
DESCRIPTIONS = "inventory/descriptions.json"
OBSERVATIONS = "inventory/observations.json"
SCENARIOS = "inventory/scenarios.json"


class ScenarioStepOut(ApiModel):
    title: str
    nodes: list[str] = Field(description="Ids of graph nodes (blocks, units or tables) where the step happens")
    rule: str | None


class ScenarioOut(ApiModel):
    id: str
    name: str
    persona: str
    summary: str
    rules: list[str]
    steps: list[ScenarioStepOut]


class GraphInsightsOut(ApiModel):
    descriptions: dict[str, str] = Field(description="Node id -> description written by a model")
    observations: list[str]
    scenarios: list[ScenarioOut]


async def _newest(request: Request, auth: Authorized, project_id: uuid.UUID) -> dict[str, Any]:
    """The newest stored document of each insight, by path."""
    async with transaction(request, auth) as conn:
        rows = (
            await conn.execute(
                text("SELECT DISTINCT ON (path) path, object_key FROM generated_artifact WHERE project_id = :p "
                     "AND path IN (:d, :o, :s) ORDER BY path, created_at DESC"),
                {"p": project_id, "d": DESCRIPTIONS, "o": OBSERVATIONS, "s": SCENARIOS},
            )
        ).all()  # fmt: skip
    store = services.store(request)
    documents: dict[str, Any] = {}
    for row in rows:
        documents[row.path] = json.loads(b"".join(await store.read(row.object_key)))
    return documents


@router.get("", response_model=GraphInsightsOut)
async def get_insights(request: Request, project_id: uuid.UUID, auth: ViewProject) -> GraphInsightsOut:
    """Descriptions, observations and scenarios of the newest run with a deep inventory; empty without one."""
    documents = await _newest(request, auth, project_id)
    return GraphInsightsOut(
        descriptions=documents.get(DESCRIPTIONS, {}).get("descriptions") or {},
        observations=documents.get(OBSERVATIONS, {}).get("observations") or [],
        scenarios=[ScenarioOut.model_validate(s) for s in documents.get(SCENARIOS, {}).get("scenarios") or []],
    )
