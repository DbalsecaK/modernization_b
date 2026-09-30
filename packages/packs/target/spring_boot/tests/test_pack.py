"""The Java Spring Boot pack (spec 8.4): the design is validated, the skeleton follows from it, neutral types map
exactly, and the generated project compiles and passes its tests in the Java sandbox (skipped without Docker or
without the image `nexti-sandbox-java:2`, built from infra/sandbox/java)."""

import asyncio
import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from nexti_pack_spring_boot import (
    IMAGE,
    Design,
    compile_and_test,
    java_type,
    junit_path,
    layer_of,
    parse_junit,
    service_path,
    skeleton,
    sql_type,
)
from nexti_sandbox import DockerSandbox

FIXTURES = Path(__file__).parent / "fixtures" / "pago_orden"
DESIGN = Design.model_validate(json.loads((FIXTURES / "design.json").read_text(encoding="utf-8")))


def image_available() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


@pytest.mark.parametrize(
    ("neutral", "java", "sql"),
    [
        ("decimal(19,4,signed)", "java.math.BigDecimal", "NUMERIC(19,4)"),
        ("integer(32,signed)", "Integer", "INTEGER"),
        ("integer(64,signed)", "Long", "BIGINT"),
        ("integer(32,unsigned)", "Long", "BIGINT"),
        ("text(fixed,3,iso8859-1)", "String", "CHAR(3)"),
        ("text(var,max,utf8)", "String", "TEXT"),
        ("timestamp(local)", "java.time.LocalDateTime", "TIMESTAMP"),
        ("timestamp(tz)", "java.time.OffsetDateTime", "TIMESTAMPTZ"),
        ("date(yyyy-MM-dd)", "java.time.LocalDate", "DATE"),
        ("boolean", "Boolean", "BOOLEAN"),
        ("enum(CTE|AHO|VIR)", "String", "VARCHAR(3)"),
    ],
)
def test_neutral_types_map_to_java_and_postgresql(neutral: str, java: str, sql: str) -> None:
    assert (java_type(neutral), sql_type(neutral)) == (java, sql)


def test_the_design_is_validated() -> None:
    data = json.loads((FIXTURES / "design.json").read_text(encoding="utf-8"))
    for broken in (
        {**data, "base_package": "Com.Bad"},
        {**data, "use_cases": [{**data["use_cases"][0], "ports": ["NoSuchPort"]}]},
        {**data, "entities": [{**data["entities"][0], "name": "class"}]},
        {**data, "entities": [{**data["entities"][0], "key": ["missing"]}]},
        {**data, "use_cases": [{**data["use_cases"][0], "inputs": [{"name": "x", "type": "money"}]}]},
    ):
        with pytest.raises(ValidationError):
            Design.model_validate(broken)
    assert DESIGN.rules() == {f"RULE-00{i}" for i in range(1, 10)}


def test_the_skeleton_follows_the_design_by_layers() -> None:
    files = skeleton(DESIGN)
    base = "src/main/java/com/bancoficticio/payments"
    assert f"{base}/domain/model/PaymentOrder.java" in files
    assert "java.math.BigDecimal commission" in files[f"{base}/domain/model/PaymentOrder.java"]
    port = files[f"{base}/domain/port/OrderRepository.java"]
    assert "java.util.Optional<com.bancoficticio.payments.domain.model.PaymentOrder> find(Integer orderNumber" in port
    assert "int markPaid(" in port
    controller = files[f"{base}/adapters/in/rest/PayOrderController.java"]
    assert '@PostMapping("/orders/pay")' in controller
    assert "RULE-001" in controller
    schema = files["src/main/resources/db/schema.sql"]
    assert "CREATE TABLE payment_order ( -- legacy db_pagos..pg_orden" in schema
    assert "PRIMARY KEY (order_number, company)" in schema
    assert "<version>3.5.6</version>" in files["pom.xml"]
    layers = {layer_of(path, DESIGN) for path in files}
    assert {"contracts", "domain", "adapters", "orchestration"} <= layers
    assert layer_of(junit_path(DESIGN, DESIGN.use_cases[0]), DESIGN) == "tests"


def test_junit_reports_are_read_by_code() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?><testsuites><testsuite name="x">
      <testcase classname="A" name="ok"/><testcase classname="A" name="bad"><failure message="expected 1"/></testcase>
      <testcase classname="A" name="later"><skipped/></testcase></testsuite></testsuites>"""
    assert [(t.name, t.status) for t in parse_junit(xml)] == [("ok", "passed"), ("bad", "failed"), ("later", "skipped")]


@pytest.fixture(scope="module")
def java_sandbox() -> DockerSandbox:
    box = DockerSandbox(image=IMAGE)
    if not asyncio.run(box.available()) or not image_available():
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    return box


def project(service: str | None = None, test: str | None = None) -> dict[str, str]:
    files = skeleton(DESIGN)
    use_case = DESIGN.use_cases[0]
    files[service_path(DESIGN, use_case)] = service or (FIXTURES / "PayOrderService.java").read_text(encoding="utf-8")
    files[junit_path(DESIGN, use_case)] = test or (FIXTURES / "PayOrderServiceTest.java").read_text(encoding="utf-8")
    return files


async def test_the_project_compiles_and_its_tests_pass_in_the_sandbox(java_sandbox: DockerSandbox) -> None:
    result = await compile_and_test(java_sandbox, project())
    assert result.compiled, result.compile_errors
    assert result.passed == 7
    assert result.failed == 0
    assert "<testsuite" in result.junit_xml


async def test_a_compile_error_comes_back_with_the_file_and_line(java_sandbox: DockerSandbox) -> None:
    broken = (FIXTURES / "PayOrderService.java").read_text(encoding="utf-8").replace("BigDecimal total =", "total =")
    result = await compile_and_test(java_sandbox, project(service=broken))
    assert not result.compiled
    assert "PayOrderService.java" in result.compile_errors
    assert "cannot find symbol" in result.compile_errors


async def test_a_failing_test_is_reported_with_its_message(java_sandbox: DockerSandbox) -> None:
    wrong = (
        (FIXTURES / "PayOrderService.java")
        .read_text(encoding="utf-8")
        .replace("RoundingMode.HALF_UP", "RoundingMode.DOWN")
    )
    result = await compile_and_test(java_sandbox, project(service=wrong))
    assert result.compiled
    assert result.failed == 1
    assert "a_web_order_pays_half_the_tariff_rounded" in result.diagnostic()
