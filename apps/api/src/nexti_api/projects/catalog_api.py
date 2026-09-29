"""The agent and skill catalog as the screens need it (spec 9, 8.3 to 8.7): cards, skills (without their content),
source adapters and options, target options, compatibility rules, pipeline templates and the phases of each flow."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request

from nexti_api.admin.common import not_found, transaction
from nexti_api.authz.require import Authorized, require_tenant
from nexti_api.catalog_store import load_catalog
from nexti_api.schemas import ApiModel

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])
TenantMember = Annotated[Authorized, Depends(require_tenant("tenant.view"))]


class RecommendRuleOut(ApiModel):
    reason: str


class AgentOut(ApiModel):
    key: str
    version: str
    name: str
    name_es: str
    group: Literal["analysis", "design", "build", "quality", "control"]
    description: str
    description_es: str
    phases: list[str]
    capabilities: list[str]
    tools: list[str]
    mandatory: bool
    level: Literal["certified", "assisted", "experimental"]
    default_profile: str
    relative_cost: int


class SkillOut(ApiModel):
    key: str
    version: str
    title: str
    description: str
    type: Literal["source", "target", "conversion", "crossCutting", "customer"]
    agents: list[str]
    technologies: list[str]
    conflicts: list[str]
    requires: list[str]
    status: Literal["draft", "evaluating", "published", "obsolete"]
    eval_score: float | None


class SkillDetailOut(SkillOut):
    content: str


class AdapterOut(ApiModel):
    key: str
    name: str
    level: str
    version: str
    validation: str


class SourceOptionOut(ApiModel):
    key: str
    name: str
    flow: Literal["modernization", "newFeature"]
    adapter: str | None
    required_skills: list[str]


class TargetOptionOut(ApiModel):
    axis: Literal["architecture", "backend", "frontend", "database", "cloud"]
    key: str
    name: str
    level: str | None
    wave: int | None


class RuleOut(ApiModel):
    key: str
    message: str


class TemplateOut(ApiModel):
    key: str
    name: str
    description: str
    required_gates: list[str]
    default_autonomy: Literal["guided", "balanced", "autonomous"]


class PhaseOut(ApiModel):
    key: str
    gate: str | None
    agent_required: bool


class FlowOut(ApiModel):
    key: Literal["modernization", "newFeature"]
    phases: list[PhaseOut]


class CatalogOut(ApiModel):
    agents: list[AgentOut]
    skills: list[SkillOut]
    adapters: list[AdapterOut]
    sources: list[SourceOptionOut]
    targets: list[TargetOptionOut]
    compatibility_rules: list[RuleOut]
    pipeline_templates: list[TemplateOut]
    flows: list[FlowOut]
    cost_unit_usd: int


def _skill(s: object) -> dict[str, object]:
    fields = ("key", "version", "title", "description", "type", "agents", "technologies", "conflicts", "requires",
              "status", "eval_score")  # fmt: skip
    return {f: getattr(s, f) for f in fields}


@router.get("", response_model=CatalogOut)
async def get_catalog(request: Request, auth: TenantMember) -> CatalogOut:
    async with transaction(request, auth) as conn:
        catalog = await load_catalog(conn)
    return CatalogOut(
        agents=[
            AgentOut(
                key=a.key, version=a.version, name=a.name, name_es=a.name_es, group=a.group,
                description=a.description, description_es=a.description_es, phases=list(a.phases),
                capabilities=list(a.capabilities), tools=list(a.tools), mandatory=a.mandatory,
                level=a.level, default_profile=a.default_profile, relative_cost=a.relative_cost,
            )
            for a in catalog.agents
        ],
        skills=[SkillOut.model_validate(_skill(s)) for s in catalog.skills],
        adapters=[AdapterOut.model_validate(a, from_attributes=True) for a in catalog.adapters],
        sources=[SourceOptionOut.model_validate(s, from_attributes=True) for s in catalog.sources],
        targets=[TargetOptionOut.model_validate(t, from_attributes=True) for t in catalog.targets],
        compatibility_rules=[RuleOut(key=r.key, message=r.message) for r in catalog.rules],
        pipeline_templates=[TemplateOut.model_validate(t, from_attributes=True) for t in catalog.templates],
        flows=[
            FlowOut(key=f.key, phases=[PhaseOut.model_validate(p, from_attributes=True) for p in f.phases])
            for f in catalog.flows
        ],
        cost_unit_usd=catalog.cost_unit_usd,
    )  # fmt: skip


@router.get("/skills/{skill_key}", response_model=SkillDetailOut)
async def get_skill(request: Request, skill_key: str, auth: TenantMember) -> SkillDetailOut:
    """A skill with the instructions its agents load on demand (SKILL.md body)."""
    async with transaction(request, auth) as conn:
        catalog = await load_catalog(conn)
    skill = catalog.skill(skill_key)
    if skill is None:
        raise not_found("skill")
    return SkillDetailOut.model_validate({**_skill(skill), "content": skill.content})
