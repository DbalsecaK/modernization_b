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
    run = context({"backend": "dotnet-10"})
    port = MemoryGenerationPort()
    with pytest.raises(PhaseUnavailableError, match="dotnet-10 pack"):
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
