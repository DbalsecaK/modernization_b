"""The catalog in the database (M2): catalog-sync is idempotent, refuses a changed definition that kept its version,
retires what the files no longer define, and the engine gets the same answer from the tables as from the files."""

import uuid
from typing import Any

import pytest
from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

import nexti_agents
import nexti_skills
from nexti_api.catalog_store import CatalogVersionError, load_catalog, sync_catalog
from nexti_api.seed import DEMO_CONFIGS, seed_project_configs
from nexti_api.tenancy import create_tenant
from nexti_core.composition import Request, Target, build_catalog, evaluate
from nexti_core.db.models import AgentDefinition, Project, ProjectAgent, ProjectConfig, ProjectSkill, SkillDefinition

REQUEST = Request(
    "modernization",
    ("cobol-cics", "bms"),
    Target("microservices-hexagonal", "spring-boot", "angular", "postgresql", "aws"),
)


async def test_sync_is_idempotent_and_the_tables_give_the_same_answer_as_the_files(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        report = await sync_catalog(conn)  # the fixture already synced once
        stored = await load_catalog(conn)
        agents = (await conn.execute(select(func.count()).where(AgentDefinition.current))).scalar_one()
        skills = (await conn.execute(select(func.count()).where(SkillDefinition.current))).scalar_one()
    files = build_catalog(nexti_agents.definitions(), nexti_skills.definitions())
    assert report.added == []
    assert report.retired == []
    assert (agents, skills) == (19, 21)
    assert evaluate(stored, REQUEST) == evaluate(files, REQUEST)
    assert stored.skill("bms-parsing").content == files.skill("bms-parsing").content  # type: ignore[union-attr]


async def test_a_changed_definition_needs_a_new_version(
    owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = nexti_skills.definitions()

    def edited() -> list[dict[str, Any]]:
        docs = [dict(d) for d in original]
        docs[0]["content"] = docs[0]["content"] + "\nOne more line.\n"
        return docs

    monkeypatch.setattr(nexti_skills, "definitions", edited)
    with pytest.raises(CatalogVersionError, match="bump its version"):
        async with owner_engine.begin() as conn:
            await sync_catalog(conn)

    def bumped() -> list[dict[str, Any]]:
        docs = edited()
        docs[0]["version"] = "99.0.0"
        return docs

    monkeypatch.setattr(nexti_skills, "definitions", bumped)
    key = original[0]["name"]
    try:
        async with owner_engine.begin() as conn:
            report = await sync_catalog(conn)
            versions = (
                await conn.execute(
                    select(SkillDefinition.version, SkillDefinition.current).where(SkillDefinition.key == key)
                )
            ).all()
        assert report.added == [f"skill:{key}@99.0.0"]
        # The old version stays for the projects that pinned it; only the new one is current.
        assert {(v.version, v.current) for v in versions} == {(original[0]["version"], False), ("99.0.0", True)}
    finally:
        monkeypatch.setattr(nexti_skills, "definitions", lambda: original)
        async with owner_engine.begin() as conn:
            await conn.execute(text("UPDATE skill_definition SET current = false WHERE key = :k"), {"k": key})
            await conn.execute(
                text("UPDATE skill_definition SET current = true WHERE key = :k AND version = :v"),
                {"k": key, "v": original[0]["version"]},
            )
            await conn.execute(text("DELETE FROM skill_definition WHERE key = :k AND version = '99.0.0'"), {"k": key})


async def test_an_agent_the_files_no_longer_define_is_retired(
    owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = nexti_agents.definitions()
    monkeypatch.setattr(nexti_agents, "definitions", lambda: [d for d in original if d["id"] != "fullstack-dev"])
    try:
        async with owner_engine.begin() as conn:
            report = await sync_catalog(conn)
        assert report.retired == ["agent:fullstack-dev"]
    finally:
        monkeypatch.setattr(nexti_agents, "definitions", lambda: original)
        async with owner_engine.begin() as conn:
            await sync_catalog(conn)
            current = (
                await conn.execute(select(AgentDefinition.current).where(AgentDefinition.key == "fullstack-dev"))
            ).scalar_one()
        assert current is True


async def test_seeded_projects_get_their_configuration(owner_engine: AsyncEngine) -> None:
    name = next(iter(DEMO_CONFIGS))
    async with owner_engine.begin() as conn:
        tenant = await create_tenant(conn, slug=f"seed-{uuid.uuid4().hex[:8]}", name="Seed test")
        project: uuid.UUID = (
            await conn.execute(insert(Project).values(tenant_id=tenant, name=name).returning(Project.id))
        ).scalar_one()
        assert await seed_project_configs(conn) >= 1
        assert await seed_project_configs(conn) == 0  # idempotent
        config = (await conn.execute(select(ProjectConfig).where(ProjectConfig.project_id == project))).one()
        agents = set(
            (await conn.execute(select(ProjectAgent.agent_key).where(ProjectAgent.project_id == project))).scalars()
        )
        skills = set(
            (await conn.execute(select(ProjectSkill.skill_key).where(ProjectSkill.project_id == project))).scalars()
        )
        await conn.execute(text("DELETE FROM project WHERE id = :p"), {"p": project})
    assert config.version == 1
    assert {"rules-verifier", "equivalence-validator", "acceptance-judge"} <= agents
    assert {"exec-cics", "bms-parsing", "spring-hexagonal"} <= skills
