"""Every agent needs a model profile that offers the capabilities it requires (spec 9.4). The profile comes from the
same cascade the gateway uses (12.4); a mismatch is a warning while the project is designed, because the models can
still be configured before anything runs (M3)."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_core.composition import Catalog
from nexti_core.db.models import ModelAssignment, ModelOffering, ModelProfile
from nexti_model_gateway.rules import AssignmentRow, resolve_profile

LONG_CONTEXT_TOKENS = 128_000
# Agent capability (catalog) -> capability of an offering (M1 catalog).
OFFERING_CAPABILITY = {"toolCalling": "tools", "structuredOutput": "structured_output", "vision": "vision"}


@dataclass(frozen=True)
class ModelCheck:
    agent: str
    profile_id: uuid.UUID | None
    profile_name: str | None
    missing: tuple[str, ...]  # agent capabilities the resolved offering lacks


async def check_models(
    conn: AsyncConnection,
    catalog: Catalog,
    agents: tuple[str, ...],
    project_id: uuid.UUID | None,
    overrides: dict[str, uuid.UUID] | None = None,
) -> list[ModelCheck]:
    """The profile each agent would use (role level of the cascade, plus proposed project overrides)."""
    rows = [
        AssignmentRow(r.project_id, r.phase, r.agent_role, r.profile_id)
        for r in (await conn.execute(select(ModelAssignment))).all()
    ]
    profiles = {
        p.id: p
        for p in (
            await conn.execute(
                select(
                    ModelProfile.id, ModelProfile.name, ModelOffering.capabilities, ModelOffering.context_window
                ).join(ModelOffering, ModelOffering.id == ModelProfile.offering_id)
            )
        ).all()
    }
    out = []
    for key in agents:
        agent = catalog.agent(key)
        if agent is None:
            continue
        profile_id = (overrides or {}).get(key) or resolve_profile(rows, project_id, None, key)
        profile = profiles.get(profile_id) if profile_id else None
        if profile is None:
            out.append(ModelCheck(key, None, None, ()))
            continue
        missing = []
        for capability in agent.capabilities:
            if capability == "longContext":
                if (profile.context_window or 0) < LONG_CONTEXT_TOKENS:
                    missing.append(capability)
            elif OFFERING_CAPABILITY.get(capability) not in set(profile.capabilities or ()):
                missing.append(capability)
        out.append(ModelCheck(key, profile.id, profile.name, tuple(missing)))
    return out
