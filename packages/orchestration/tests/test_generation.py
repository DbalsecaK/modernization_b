"""Design (C3) and generation by layers on the fictitious application (spec 6.1 phases 8 and 10): the architect's
design is validated by code; the tests come first from the rule scenarios; the service is corrected until those
tests pass in the real Java sandbox; a backend without a pack waits instead of generating another language.
Skipped without Docker or the image nexti-sandbox-java:2 (infra/sandbox/java)."""

import asyncio
import hashlib
import json
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

import pytest

from nexti_core.adapters import SourceFile
from nexti_core.spec.model import Rule
from nexti_orchestration import PhaseSpec, RunContext
from nexti_orchestration.context import PhaseContext
from nexti_orchestration.extraction import ModelCaller, ModelReply, ReplyError
from nexti_orchestration.generation import (
    GenerationPhases,
    design_problems,
    java_block,
    legacy_names,
    propose_design,
    wiring,
)
from nexti_orchestration.memory import MemoryStore
from nexti_orchestration.model import PhaseUnavailableError
from nexti_orchestration.store import Usage
from nexti_pack_spring_boot import IMAGE, Design
from nexti_sandbox import DockerSandbox, Sandbox

ROOT = Path(__file__).resolve().parents[3]
PACK = ROOT / "packages/packs/target/spring_boot/tests/fixtures/pago_orden"
REFERENCE = json.loads(
    (ROOT / "packages/adapters/source/sybase/tests/fixtures/pago_orden/reference_spec.json").read_text(encoding="utf-8")
)
RULES = [Rule.model_validate(r) for r in REFERENCE["rules"]]
DESIGN_JSON = (PACK / "design.json").read_text(encoding="utf-8")
SERVICE = (PACK / "PayOrderService.java").read_text(encoding="utf-8")
TEST = (PACK / "PayOrderServiceTest.java").read_text(encoding="utf-8")
SOURCE = (ROOT / "packages/adapters/source/sybase/tests/fixtures/pago_orden/sp_pago_orden.sp").read_text("utf-8")
ADAPTER = """package com.bancoficticio.payments.adapters.out.jdbc;

public class Jdbc{port} {{
}}
"""


class TeamModel:
    """The architect answers the reference design; the tester the reference tests; the developer a wrong service
    first (truncating instead of rounding) and the right one after the failing test comes back."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    async def complete(
        self, agent: str, phase: str, messages: list[dict[str, str]], *, iteration: int = 1, judge: int = 0
    ) -> ModelReply:
        self.calls.append((agent, phase, iteration))
        request = messages[1]["content"]
        if agent == "solution-architect":
            content = DESIGN_JSON
        elif agent == "test-engineer":
            content = f"```java\n{TEST}```"
        elif "JDBC adapter" in request:
            port = re.search(r"adapter Jdbc(\w+)", request)
            content = f"```java\n{ADAPTER.format(port=port.group(1) if port else 'X')}```"
        else:
            wrong = SERVICE.replace("RoundingMode.HALF_UP", "RoundingMode.DOWN")
            content = f"```java\n{wrong if iteration == 1 else SERVICE}```"
        return ModelReply(content, Usage(model="team", input_tokens=10, output_tokens=10))


class MemoryGenerationPort:
    def __init__(self, sandbox: Sandbox | None = None) -> None:
        self.team = TeamModel()
        self.models: ModelCaller = self.team
        self.design: Design | None = None
        self.drafts: dict[str, str] = {}
        self.artifacts: dict[str, str] = {}
        self.layers: dict[str, str] = {}
        self._sandbox = sandbox

    async def load_rules(self) -> list[Rule]:
        return RULES

    async def inventory_digest(self) -> str:
        return "Procedure dbo.sp_pago_orden\nTable db_pagos..pg_orden"

    async def source_files(self) -> list[SourceFile]:
        return [SourceFile("sp/sp_pago_orden.sp", SOURCE)]

    async def save_design(self, design: Design) -> None:
        self.design = design

    async def load_design(self) -> Design | None:
        return self.design

    async def save_file(self, path: str, content: str) -> str:
        key = hashlib.sha256(content.encode()).hexdigest()
        self.drafts[key] = content
        return key

    async def load_file(self, reference: str) -> str:
        return self.drafts[reference]

    async def save_artifacts(self, files: dict[str, str], layers: dict[str, str], rules: dict[str, list[str]]) -> None:
        self.artifacts.update(files)
        self.layers.update(layers)

    def sandbox(self, image: str) -> Sandbox:
        assert self._sandbox is not None
        return self._sandbox


def context(target: dict[str, str] | None = None) -> RunContext:
    phases = (PhaseSpec("design", "C3", True), PhaseSpec("generation", None, True))
    return RunContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pipeline", "modernization", phases, ("C1", "C4"),
                      "balanced", 3, (), target=target or {"backend": "spring-boot"})  # fmt: skip


def phase_context(run: RunContext, key: str, store: MemoryStore) -> PhaseContext:
    return PhaseContext(run, store, next(p for p in run.phases if p.key == key), None)


def test_java_is_taken_from_the_reply() -> None:
    assert java_block("Here:\n```java\npublic class A {}\n```").strip() == "public class A {}"
    with pytest.raises(ReplyError):
        java_block("I would write a class")


def test_every_rule_must_be_in_a_use_case() -> None:
    data = json.loads(DESIGN_JSON)
    data["use_cases"][0]["rules"] = ["RULE-001", "RULE-099"]
    problems = design_problems(Design.model_validate(data), RULES)
    assert "RULE-002" in problems[0]
    assert "RULE-099" in problems[1]


def test_legacy_names_the_code_does_not_have_are_invented() -> None:
    names = legacy_names([SourceFile("sp/sp_pago_orden.sp", SOURCE)])
    assert design_problems(Design.model_validate_json(DESIGN_JSON), RULES, names) == []
    data = json.loads(DESIGN_JSON)
    data["entities"][2]["fields"][0]["legacy"] = "cta_cuenta"  # the SP calls it cta_numero
    problems = design_problems(Design.model_validate(data), RULES, names)
    assert problems == ["these legacy names are not in the legacy code (check the exact spelling): cta_cuenta"]
    data["entities"][2]["fields"][0]["legacy"] = "@i_cuenta"  # it exists, but it is a parameter, not a column
    problems = design_problems(Design.model_validate(data), RULES, names)
    assert problems == [
        "entity fields map to columns of their legacy table, not to parameters or variables: Account.number = @i_cuenta"
    ]


def test_the_design_must_map_the_legacy_to_replay_the_golden_master() -> None:
    assert design_problems(Design.model_validate_json(DESIGN_JSON), RULES) == []
    data = json.loads(DESIGN_JSON)
    del data["entities"][2]["fields"][0]["legacy"]  # Account.number without its legacy column
    del data["use_cases"][0]["inputs"][0]["legacy"]
    del data["ports"][3]["methods"][0]["inputs"][0]["legacy"]
    problems = design_problems(Design.model_validate(data), RULES)
    assert problems == [
        "fields of entities with a legacy table need their legacy column: Account.number",
        "PayOrder: inputs and outputs need their legacy parameter: orderNumber",
        "methods of ports that replace a legacy program need the argument of each input: DebitGateway",
    ]


async def test_an_invalid_design_goes_back_with_the_problems() -> None:
    replies = iter([DESIGN_JSON.replace('"integer(32,signed)"', '"money"', 1), DESIGN_JSON])

    class Architect:
        def __init__(self) -> None:
            self.messages: list[list[dict[str, str]]] = []

        async def complete(self, agent: str, phase: str, messages: list[dict[str, str]], **_: Any) -> ModelReply:
            self.messages.append(list(messages))
            return ModelReply(next(replies), Usage())

    architect = Architect()
    design, usage = await propose_design(architect, RULES, "inventory")
    assert design.context == "payments"
    assert len(usage) == 2
    assert "neutral type" in architect.messages[1][-1]["content"] or "money" in architect.messages[1][-1]["content"]


def test_the_wiring_builds_each_service_from_its_ports() -> None:
    path, java = wiring(Design.model_validate_json(DESIGN_JSON))
    assert path.endswith("com/bancoficticio/payments/config/Wiring.java")
    assert "new com.bancoficticio.payments.application.PayOrderService(orderRepository, tariffRepository" in java


async def test_a_backend_without_a_pack_waits_in_generation() -> None:
    run = context({"backend": "nextjs"})
    port = MemoryGenerationPort()
    with pytest.raises(PhaseUnavailableError, match="nextjs pack"):
        await GenerationPhases(port).generation(phase_context(run, "generation", MemoryStore()))


def _image_available() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


@pytest.fixture(scope="module")
def java_sandbox() -> DockerSandbox:
    box = DockerSandbox(image=IMAGE)
    if not asyncio.run(box.available()) or not _image_available():
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    return box


async def test_design_then_generation_by_layers_corrects_the_service_until_the_tests_pass(
    java_sandbox: DockerSandbox,
) -> None:
    run, store = context(), MemoryStore()
    port = MemoryGenerationPort(java_sandbox)
    phases = GenerationPhases(port)
    designed = await phases.design(phase_context(run, "design", store))
    assert designed.summary.startswith("1 use case(s), 4 entities, 4 ports")

    result = await phases.generation(phase_context(run, "generation", store))
    assert "7 tests pass in the sandbox" in result.summary
    # The service took two attempts: the first truncated instead of rounding.
    assert ("backend-dev", "generation", 2) in port.team.calls
    assert store.kinds().count("selfCorrected") == 1
    failed = next(e for e in store.events if e.kind == "verificationFailed")
    assert "a_web_order_pays_half_the_tariff_rounded" in failed.payload["diagnostic"]
    assert set(port.layers.values()) >= {"contracts", "domain", "adapters", "orchestration", "tests"}
    service = next(p for p in port.artifacts if p.endswith("application/PayOrderService.java"))
    assert "RoundingMode.HALF_UP" in port.artifacts[service]


def test_legacy_names_are_compared_without_markers_or_invisible_characters_and_hints_name_the_closest() -> None:
    from nexti_core.adapters import SourceFile as File
    from nexti_core.spec.design import Design
    from nexti_core.spec.model import Rule as SpecRule
    from nexti_orchestration.generation import design_problems, legacy_names

    names = legacy_names(
        [
            File(
                "p.sp",
                "create proc sp_p @i_cta int, @o_trn int output as\n"
                "select @o_trn = tr_valor from db_x..tr_transaccion where tr_cta = @i_cta",
            )
        ]
    )
    rule = SpecRule.model_validate({"id": "RULE-001", "name": "rule name", "category": "validation", "priority": "P1",
                                    "statement": "a statement long enough",
                                    "sources": [{"file": "p.sp", "line_start": 1, "line_end": 1}]})  # fmt: skip

    def design(legacy: str) -> Design:
        return Design.model_validate({"context": "x", "base_package": "com.x.y", "use_cases": [
            {"name": "Uc", "rules": ["RULE-001"], "legacy_program": "sp_p",
             "outputs": [{"name": "trn", "type": "integer(32,signed)", "legacy": legacy}]}]})  # fmt: skip

    for spelled in ("@o_trn", "@O_TRN", "o_trn", "sp_p.@o_trn", "@o_trn\u200b", " @o_trn "):
        assert design_problems(design(spelled), [rule], names) == [], spelled
    problems = design_problems(design("@o_trx"), [rule], names)
    assert problems == ["these legacy names are not in the legacy code (check the exact spelling): @o_trx"]
    hinted = design_problems(design("@o_trx"), [rule], names, hints=True)
    assert hinted[1] == "closest names in the legacy code: @o_trx -> @o_trn"
    (_, nothing) = design_problems(design("valor_por_transaccion"), [rule], names, hints=True)
    assert nothing.startswith("closest names in the legacy code: valor_por_transaccion -> ")


def test_a_guided_design_cannot_mask_what_the_rules_use_and_keeps_the_written_tables() -> None:
    from nexti_core.adapters import SourceFile as File
    from nexti_core.spec.design import Design
    from nexti_core.spec.model import Rule as SpecRule
    from nexti_orchestration.generation import design_problems, table_of

    source = "create proc sp_p as\nupdate db_x..pg_orden_total set to_estado = 'P'\nexec sp_comision_grabar 1\n"
    files = [File("p.sp", source)]
    rule = SpecRule.model_validate({"id": "RULE-001", "name": "rule name", "category": "validation", "priority": "P1",
                                    "statement": "a statement long enough",
                                    "sources": [{"file": "p.sp", "line_start": 2, "line_end": 3}]})  # fmt: skip
    design = Design.model_validate({
        "context": "x", "base_package": "com.x.y", "use_cases": [{"name": "Uc", "rules": ["RULE-001"]}],
        "masks": [{"path": "tables:db_x..pg_orden_total", "reason": "no entity keeps this legacy table"}],
        "infrastructure": ["sp_comision_grabar"],
    })  # fmt: skip
    assert design_problems(design, [rule], files=files, written={"pg_orden_total", "pg_detalle"}) == []
    found = design_problems(design, [rule], hints=True, files=files, written={"pg_orden_total", "pg_detalle"})
    assert found == [
        "mask tables:db_x..pg_orden_total hides a table the rules use (RULE-001): keep it as an entity with its "
        "legacy_table",
        "sp_comision_grabar is listed as infrastructure, but the rules cite its call (RULE-001): give it a port with "
        "legacy_program",
        "legacy tables the program writes need an entity with legacy_table (or an explained tables: mask): pg_detalle",
    ]
    assert (table_of("db..t.col"), table_of("db.dbo.t"), table_of("t")) == ("t", "t", "t")


def test_the_stack_and_the_preferences_become_guidance_only_when_the_run_has_them() -> None:
    from nexti_orchestration.guided import preference_guidance, stack_guidance

    assert stack_guidance({}) == ""
    # The planner of the stories gets the preferences alone: a guided run without them asks exactly as recorded.
    assert preference_guidance({"backend": "spring-boot", "backend_version": "3.5", "database": "postgresql"}) == ""
    assert preference_guidance({"strategy": "strangler-fig"}).startswith("Migration strategy strangler-fig:")
    text = stack_guidance({"architecture": "preserve-topology", "backend": "spring-boot", "backend_version": "3.5",
                           "frontend": "none", "database": "postgresql", "cloud": "aws", "strategy": "strangler-fig",
                           "artifact": "container", "practices": "solid,tdd,unknown"})  # fmt: skip
    assert text.startswith("Target stack: architecture preserve-topology, backend spring-boot 3.5, database postgresql")
    assert "one service per legacy program" in text
    assert "Migration strategy strangler-fig" in text
    assert "Deployment artifact: packaged as a container image" in text
    assert "solid:" in text
    assert "tdd:" in text
    assert "unknown" not in text
