"""Quarkus as the second framework of the Java pack (ADR-0028): the same core as Spring Boot (domain, ports, use case
services, their oracle tests) with JAX-RS resources, DataSource-based JDBC adapters and CDI wiring at the edges. The
skeleton compiles with the design's core, and the hand-written reference target of the fictitious application passes
its tests and reproduces the 12 cases Sybase recorded against PostgreSQL inside the sandbox; the canary is caught.
Sandbox tests skip without Docker or the image nexti-sandbox-java-quarkus:1 (infra/sandbox/java-quarkus)."""

import asyncio
import subprocess
from pathlib import Path

import pytest

from nexti_adapter_sybase.ase import RecordedRunner
from nexti_agents import prompt
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import GoldenMaster, Suite
from nexti_pack_spring_boot import Design, layer_of
from nexti_pack_spring_boot.equivalence import harness_source
from nexti_pack_spring_boot.pack import PACK as SPRING_BOOT
from nexti_pack_spring_boot.quarkus import IMAGE, QUARKUS_PACK, QUARKUS_VERSION
from nexti_sandbox import DockerSandbox

HERE = Path(__file__).parent / "fixtures" / "pago_orden"
LEGACY = Path(__file__).resolve().parents[4] / "adapters/source/sybase/tests/fixtures/pago_orden"
DESIGN = Design.model_validate_json((HERE / "design.json").read_text(encoding="utf-8"))
PAY = DESIGN.use_cases[0]
SUITE = Suite.model_validate_json((LEGACY / "characterization.json").read_text(encoding="utf-8"))
SOURCE = [SourceFile("sp/sp_pago_orden.sp", (LEGACY / "sp_pago_orden.sp").read_text(encoding="utf-8"))]
MASTER: GoldenMaster = asyncio.run(RecordedRunner(LEGACY / "golden", "replay").run(SOURCE, SUITE))
BASE = "src/main/java/com/bancoficticio/payments"


def reference_project(design: Design) -> dict[str, str]:
    """The Quarkus skeleton with the reference core of the Spring Boot fixture and the Quarkus adapters."""
    files = QUARKUS_PACK.skeleton(design)
    files[QUARKUS_PACK.service_path(design, PAY)] = (HERE / "PayOrderService.java").read_text(encoding="utf-8")
    files[QUARKUS_PACK.test_path(design, PAY)] = (HERE / "PayOrderServiceTest.java").read_text(encoding="utf-8")
    for port in design.ports:
        reference = HERE / "quarkus" / f"Jdbc{port.name}.java"
        if reference.exists():
            files[QUARKUS_PACK.adapter_path(design, port)] = reference.read_text(encoding="utf-8")
    return files


def test_the_core_is_the_spring_boot_one_and_only_the_edges_change() -> None:
    quarkus, spring = QUARKUS_PACK.skeleton(DESIGN), SPRING_BOOT.skeleton(DESIGN)
    core = [p for p in spring if "/domain/" in p or p.endswith(("Request.java", "Response.java", ".sql"))]
    assert core
    assert all(quarkus[p] == spring[p] for p in core)
    assert QUARKUS_PACK.service_path(DESIGN, PAY) == SPRING_BOOT.service_path(DESIGN, PAY)
    assert QUARKUS_PACK.test_path(DESIGN, PAY) == SPRING_BOOT.test_path(DESIGN, PAY)
    assert QUARKUS_PACK.tester_prompt == SPRING_BOOT.tester_prompt
    assert not any("springframework" in c for c in quarkus.values())
    assert f"{BASE}/adapters/in/rest/PayOrderController.java" not in quarkus
    assert f"{BASE}/PaymentsApplication.java" not in quarkus
    resource = quarkus[f"{BASE}/adapters/in/rest/PayOrderResource.java"]
    assert '@Path("/api/payments")' in resource
    assert '@POST\n    @Path("/orders/pay")' in resource
    assert "public PayOrderResponse handle(PayOrderRequest request)" in resource
    assert "RULE-001" in resource
    wiring = quarkus[f"{BASE}/config/Wiring.java"]
    assert "@Produces\n    @Singleton" in wiring
    assert "new com.bancoficticio.payments.application.PayOrderService(orderRepository, tariffRepository," in wiring
    pom = quarkus["pom.xml"]
    assert f"<quarkus.platform.version>{QUARKUS_VERSION}</quarkus.platform.version>" in pom
    for extension in ("quarkus-rest-jackson", "quarkus-agroal", "quarkus-jdbc-postgresql", "quarkus-arc"):
        assert f"<artifactId>{extension}</artifactId>" in pom
    assert "quarkus.datasource.db-kind=postgresql" in quarkus["src/main/resources/application.properties"]
    held = {p for p in quarkus if QUARKUS_PACK.held_back(p)}
    assert held == {f"{BASE}/adapters/in/rest/PayOrderResource.java", f"{BASE}/config/Wiring.java"}
    assert {layer_of(p, DESIGN) for p in quarkus} == {"contracts", "domain", "adapters", "orchestration"}


def test_a_method_without_a_body_takes_the_request_from_the_query() -> None:
    data = DESIGN.model_dump(mode="json")
    data["use_cases"][0] = {**data["use_cases"][0], "http_method": "GET", "path": "/orders"}
    resource = QUARKUS_PACK.skeleton(Design.model_validate(data))[f"{BASE}/adapters/in/rest/PayOrderResource.java"]
    assert '@GET\n    @Path("/orders")' in resource
    assert '@QueryParam("orderNumber") Integer orderNumber' in resource
    assert "service.execute(new PayOrderRequest(" in resource


def test_the_adapters_are_asked_with_a_datasource_and_the_quarkus_prompt() -> None:
    files = QUARKUS_PACK.skeleton(DESIGN)
    request = QUARKUS_PACK.adapter_request(DESIGN, "AccountRepository", files)
    assert "javax.sql.DataSource" in request
    assert "JdbcTemplate" in request  # only to say it is not used
    assert "CREATE TABLE account" in request
    developer = prompt(QUARKUS_PACK.developer_prompt)
    assert "javax.sql.DataSource" in developer
    assert "@org.springframework" not in developer
    assert QUARKUS_PACK.describe() == {"name": "quarkus", "image": IMAGE, "framework": "quarkus"}
    assert "org.springframework" not in harness_source("quarkus")
    assert "getConstructor(DataSource.class)" in harness_source("quarkus")


def test_the_canary_is_the_one_of_the_java_pack() -> None:
    source = (HERE / "PayOrderService.java").read_text(encoding="utf-8")
    found = QUARKUS_PACK.mutations(source)
    assert len(found) == 3
    assert [m.after for m in found] == [m.after for m in SPRING_BOOT.mutations(source)]


def _image_available() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


@pytest.fixture(scope="module")
def quarkus_sandbox() -> DockerSandbox:
    box = DockerSandbox(image=IMAGE)
    if not asyncio.run(box.available()) or not _image_available():
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    return box


def test_the_skeleton_alone_compiles(quarkus_sandbox: DockerSandbox) -> None:
    files = {p: c for p, c in QUARKUS_PACK.skeleton(DESIGN).items() if not QUARKUS_PACK.held_back(p)}
    build = asyncio.run(QUARKUS_PACK.compile_and_test(quarkus_sandbox, files, run_tests=False))
    assert build.compiled, build.compile_errors


def test_the_reference_target_compiles_with_its_edges_and_its_tests_pass(quarkus_sandbox: DockerSandbox) -> None:
    build = asyncio.run(QUARKUS_PACK.compile_and_test(quarkus_sandbox, reference_project(DESIGN)))
    assert build.compiled, build.compile_errors
    assert (build.passed, build.failed) == (7, 0)


def test_a_spring_adapter_does_not_compile_in_the_quarkus_sandbox(quarkus_sandbox: DockerSandbox) -> None:
    files = reference_project(DESIGN)
    files[f"{BASE}/adapters/out/jdbc/JdbcAccountRepository.java"] = (HERE / "JdbcAccountRepository.java").read_text(
        encoding="utf-8"
    )
    build = asyncio.run(QUARKUS_PACK.compile_and_test(quarkus_sandbox, files, run_tests=False))
    assert not build.compiled
    assert "JdbcAccountRepository.java" in build.compile_errors


def test_the_reference_target_reproduces_the_golden_master(quarkus_sandbox: DockerSandbox) -> None:
    run = asyncio.run(QUARKUS_PACK.run_equivalence(quarkus_sandbox, reference_project(DESIGN), DESIGN, PAY, MASTER))
    assert run.problem is None, run.problem
    assert (run.build.passed, run.build.failed) == (7, 0)
    different = {c.name: (c.failure, c.expected, c.actual) for c in run.cases if c.failure or c.expected != c.actual}
    assert len(run.cases) == 12
    assert different == {}


def test_the_canary_is_caught(quarkus_sandbox: DockerSandbox) -> None:
    files = reference_project(DESIGN)
    target = QUARKUS_PACK.service_path(DESIGN, PAY)
    mutation = QUARKUS_PACK.mutations(files[target])[0]
    run = asyncio.run(
        QUARKUS_PACK.run_equivalence(quarkus_sandbox, {**files, target: mutation.source}, DESIGN, PAY, MASTER)
    )
    differs = [c.name for c in run.cases if c.failure or c.expected != c.actual]
    assert run.build.failed > 0 or differs
