"""Flow 3 in the pipeline (ADR-0026): BillPay as an existing application receives a new query of a payment's status.
The design of the delta is checked against the inventory and the stories, the code against its placement and the
architecture rules, and with scripted models (no spend) the delta is generated, compiled with every test in the Java
sandbox and validated by code with EXTEND_CHECKS. Sandbox tests skip without Docker or the image."""

import asyncio
import json
import subprocess
import uuid
from pathlib import Path

import pytest

from nexti_orchestration import PhaseSpec, RunContext
from nexti_orchestration.context import PhaseContext
from nexti_orchestration.extension import (
    AS_IS,
    BASELINE,
    REPORT,
    Change,
    DeltaDesign,
    ExtensionPhases,
    contract_broken,
    delta_problems,
    fitness_violations,
    parse_files,
    placement_problems,
    read_inventory,
)
from nexti_orchestration.extraction import ModelReply, ReplyError
from nexti_orchestration.feature import FeatureStory
from nexti_orchestration.memory import MemoryStore
from nexti_orchestration.store import Usage
from nexti_pack_spring_boot.build import IMAGE
from nexti_sandbox import DockerSandbox, Sandbox
from nexti_verification import Verdict

APP = Path(__file__).parent / "fixtures" / "billpay_app"
CONTROLLER = "src/main/java/com/contoso/billpay/api/PaymentController.java"
SERVICE = "src/main/java/com/contoso/billpay/domain/PaymentStatusService.java"
TEST = "src/test/java/com/contoso/billpay/domain/PaymentStatusServiceTest.java"
STORY = FeatureStory(
    "US-001", "Query the status of a payment order",
    ["Scenario: a pending order shows its status\nGiven order 1001 of company 10 is pending\nThen its status is P",
     "Scenario: an unknown order has no status\nGiven order 1 does not exist\nThen there is no status"],
    [], "approved",
)  # fmt: skip
DESIGN = DeltaDesign(changes=[Change(
    name="PaymentStatusQuery", description="The status of an order, for the channels", stories=["US-001"],
    http_method="GET", path="/api/v1/payments/{orderId}", reuses=["PaymentController"], tables=["orders"],
    files=[SERVICE, CONTROLLER],
)])  # fmt: skip
SERVICE_JAVA = """package com.contoso.billpay.domain;

import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class PaymentStatusService {
    private final JdbcTemplate jdbc;

    public PaymentStatusService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public Optional<String> status(int orderId, int companyId) {
        List<String> found = jdbc.queryForList(
                "SELECT status FROM orders WHERE order_no = ? AND company_id = ?", String.class, orderId, companyId);
        if (found.isEmpty()) {
            return Optional.empty();
        }
        return Optional.of(found.get(0).trim());
    }
}
"""
TEST_JAVA = """package com.contoso.billpay.domain;

import static org.assertj.core.api.Assertions.assertThat;

import com.contoso.billpay.support.ScriptedJdbc;
import java.util.List;
import org.junit.jupiter.api.Test;

class PaymentStatusServiceTest {
    @Test
    void ac_US001_1_a_pending_order_shows_its_status() {
        ScriptedJdbc jdbc = new ScriptedJdbc().answer("FROM orders", List.of("P"));
        assertThat(new PaymentStatusService(jdbc).status(1001, 10)).contains("P");
    }

    @Test
    void ac_US001_2_an_unknown_order_has_no_status() {
        assertThat(new PaymentStatusService(new ScriptedJdbc()).status(1, 10)).isEmpty();
    }
}
"""


def application() -> dict[str, str]:
    return {p.relative_to(APP).as_posix(): p.read_text(encoding="utf-8") for p in APP.rglob("*") if p.is_file()}


def controller_with_status(original: str) -> str:
    """The existing controller extended with the new endpoint (the delta keeps the POST as it was)."""
    changed = original.replace(
        "import org.springframework.web.bind.annotation.PostMapping;",
        "import com.contoso.billpay.domain.PaymentStatusService;\n"
        "import org.springframework.web.bind.annotation.GetMapping;\n"
        "import org.springframework.web.bind.annotation.PathVariable;\n"
        "import org.springframework.web.bind.annotation.PostMapping;\n"
        "import org.springframework.web.bind.annotation.RequestParam;",
    )
    changed = changed.replace(
        "    private final PaymentService payments;\n\n    public PaymentController(PaymentService payments) {\n"
        "        this.payments = payments;\n    }",
        "    private final PaymentService payments;\n    private final PaymentStatusService statuses;\n\n"
        "    public PaymentController(PaymentService payments, PaymentStatusService statuses) {\n"
        "        this.payments = payments;\n        this.statuses = statuses;\n    }\n\n"
        '    @GetMapping("/payments/{orderId}")\n'
        "    public ResponseEntity<String> status(@PathVariable Integer orderId, @RequestParam Integer companyId) {\n"
        "        return statuses.status(orderId, companyId).map(ResponseEntity::ok)\n"
        "                .orElse(ResponseEntity.notFound().build());\n    }",
    )
    assert changed != original
    return changed


def test_a_delta_design_is_checked_against_the_inventory_and_the_stories() -> None:
    files = application()
    found = read_inventory(files)
    assert delta_problems(DESIGN, [STORY], found, files) == []
    other = FeatureStory("US-002", "Refund a payment", ["Scenario: refund"], [], "approved")
    clash = DeltaDesign(changes=[Change(name="Pay", stories=["US-001"], http_method="POST", path="/api/v1/payments",
                                        reuses=["Ghost"], tables=["refunds"], files=["pom.xml"])])  # fmt: skip
    assert delta_problems(clash, [STORY, other], found, files) == [
        "The story US-002 is in no change",
        "The change Pay reuses Ghost, which the application does not have",
        "The change Pay uses the table refunds, which the application does not have",
        "The change Pay would touch pom.xml: existing tests and build files stay as they are",
    ]
    clash.changes[0].reuses = []
    assert "POST /api/v1/payments already exists" in delta_problems(clash, [STORY], found, files)[0]


def test_files_come_in_fenced_blocks_in_their_place() -> None:
    reply = f"Here they are.\n```java {TEST}\n{TEST_JAVA}```\n```java ./{SERVICE}\n{SERVICE_JAVA}```"
    files = parse_files(reply)
    assert list(files) == [TEST, SERVICE]
    with pytest.raises(ReplyError):
        parse_files("```java\nclass A {}\n```")
    existing = application()
    old_test = "src/test/java/com/contoso/billpay/domain/PaymentServiceTest.java"
    assert placement_problems({old_test: "", SERVICE: ""}, existing, tests=True) == [
        f"{old_test} is an existing test: write a new test class instead",
        f"{SERVICE}: tests go under src/test/",
    ]
    assert placement_problems({"pom.xml": "", "../x.java": ""}, existing, tests=False) == [
        "pom.xml: the build file stays as it is (only libraries already present can be used)",
        "../x.java is not a path inside the project",
    ]


def test_the_architecture_rules_and_the_existing_contract() -> None:
    existing = application()
    sql_in_controller = existing[CONTROLLER].replace("return result", 'jdbc.update("DELETE FROM orders");\n        '
                                                     "return result")  # fmt: skip
    old_test = "src/test/java/com/contoso/billpay/domain/PaymentServiceTest.java"
    assert fitness_violations(existing, {CONTROLLER: sql_in_controller, old_test: "", "pom.xml": ""}) == [
        f"{CONTROLLER}: the controller uses DELETE (persistence belongs in the services or repositories)",
        f"{old_test}: an existing test was changed",
        "pom.xml: the build file was changed",
        "pom.xml: outside src/",
    ]
    assert fitness_violations(existing, {CONTROLLER: controller_with_status(existing[CONTROLLER])}) == []
    before = read_inventory(existing)
    extended = read_inventory(existing | {CONTROLLER: controller_with_status(existing[CONTROLLER])})
    assert contract_broken(before, extended) == []
    assert {(e.method, e.path) for e in extended.endpoints} == {("POST", "/api/v1/payments"),
                                                                ("GET", "/api/v1/payments/{orderId}")}  # fmt: skip
    removed = read_inventory(existing | {CONTROLLER: existing[CONTROLLER].replace("@PostMapping", "@PutMapping")})
    assert contract_broken(before, removed) == ["POST /api/v1/payments was removed"]


class ScriptedModels:
    """The answers a model would give, by agent: the delta is hand-written, nothing is spent."""

    def __init__(self, answers: dict[str, list[str]]) -> None:
        self.answers = answers
        self.calls: list[str] = []

    async def complete(self, agent: str, phase: str, messages: list[dict[str, str]], *, iteration: int = 1,
                       judge: int = 0) -> ModelReply:  # fmt: skip
        self.calls.append(agent)
        return ModelReply(self.answers[agent].pop(0), Usage(input_tokens=1, output_tokens=1))


class MemoryPort:
    def __init__(self, sandbox: Sandbox, models: ScriptedModels) -> None:
        self._sandbox = sandbox
        self.models = models
        self.artifacts: dict[str, str] = {}
        self.files: dict[str, str] = {}
        self.saved: list[tuple[Verdict, bytes]] = []

    async def application_files(self) -> dict[str, str]:
        return application()

    async def load_stories(self) -> list[FeatureStory]:
        return [STORY]

    async def load_inputs(self) -> dict[str, str]:
        return {"inputs/request.md": "US-001: the channels need to query the status of a payment order."}

    async def open_questions(self) -> list[str]:
        return []

    async def save_file(self, path: str, content: str) -> str:
        key = f"{path}#{len(self.files)}"
        self.files[key] = content
        return key

    async def load_file(self, reference: str) -> str:
        return self.files[reference]

    async def save_artifacts(self, files: dict[str, str], layers: dict[str, str], rules: dict[str, list[str]]) -> None:
        self.artifacts |= files

    async def load_artifact(self, path: str) -> str | None:
        return self.artifacts.get(path)

    async def save_verdict(self, verdict: Verdict, proof_pack: bytes) -> str:
        self.saved.append((verdict, proof_pack))
        return "proof"

    def sandbox(self, image: str) -> Sandbox:
        assert image == IMAGE
        return self._sandbox


def _context(phase: str) -> PhaseContext:
    spec = PhaseSpec(phase, None, True)
    run = RunContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pipeline", "extendExisting", (spec,), (), "balanced",
                     3, (), target={"backend": "spring-boot", "database": "postgresql"})  # fmt: skip
    return PhaseContext(run, MemoryStore(), spec, None)


def _image_available() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


def test_the_delta_is_generated_and_validated_with_every_test() -> None:
    box = DockerSandbox(image=IMAGE)
    if not asyncio.run(box.available()) or not _image_available():
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    existing = application()
    broken_code = f"```java {SERVICE}\n{SERVICE_JAVA.replace('found.get(0).trim()', 'found.get(0) + "!"')}```"
    models = ScriptedModels({
        "solution-architect": [json.dumps({"changes": [{"name": "PaymentStatusQuery", "stories": ["US-009"]}]}),
                               DESIGN.model_dump_json()],
        "test-engineer": [f"```java {TEST}\n{TEST_JAVA}```"],
        "backend-dev": [broken_code, f"```java {SERVICE}\n{SERVICE_JAVA}```\n```java {CONTROLLER}\n"
                                     f"{controller_with_status(existing[CONTROLLER])}```"],
    })  # fmt: skip
    port = MemoryPort(box, models)
    phases = ExtensionPhases(port)  # type: ignore[arg-type]
    inventory = asyncio.run(phases.inventory(_context("inventory")))
    assert inventory.summary == ("spring-boot: 1 endpoint(s), 4 table(s), 3 service method(s); baseline: 5 test(s) "
                                 "pass")  # fmt: skip
    assert len(json.loads(port.artifacts[BASELINE])["passed"]) == 5
    assert "/api/v1/payments" in port.artifacts[AS_IS]
    design = asyncio.run(phases.design(_context("design")))
    assert design.summary.startswith("1 change(s), 1 endpoint(s)")  # the first answer named an unknown story
    generation = asyncio.run(phases.generation(_context("generation")))
    assert generation.summary == "2 new and 1 changed file(s); 7 test(s) pass in the sandbox"
    assert models.calls.count("backend-dev") == 2  # the first version failed its tests and was corrected
    asyncio.run(phases.validation(_context("validation")))
    verdict, _ = port.saved[0]
    statuses = {c.key: c.status for c in verdict.checks}
    assert (verdict.module, verdict.verdict) == ("delta-billpayapplication", "PROVEN"), verdict.checks
    assert statuses == dict.fromkeys(["regression", "criteria_covered", "contract_kept", "fitness", "canary",
                                      "traced_to_inputs"], "passed")  # fmt: skip
    assert "`src/main/java/com/contoso/billpay/domain/PaymentStatusService.java`" in port.artifacts[REPORT]
    delivery = asyncio.run(phases.delivery(_context("delivery")))
    assert delivery.summary.startswith("The delta (3 file(s))")
