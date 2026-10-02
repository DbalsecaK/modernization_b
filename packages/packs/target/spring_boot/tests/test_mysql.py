"""MySQL as the persistence of the Spring Boot pack (spec 8.4, ADR-0027): neutral types map to MySQL 8.4, a reserved
name is quoted with backticks everywhere, and the hand-written reference target of the fictitious application
reproduces the 12 cases Sybase recorded against MySQL inside the sandbox, with its default hardening (no network,
read-only root, user nobody). None of the fictitious application's columns is reserved in MySQL, so the MySQL tests
keep the account type in a column named `condition`. Sandbox tests skip without Docker or the image
nexti-sandbox-java-mysql:1."""

import asyncio
import subprocess
from pathlib import Path

import pytest

from nexti_adapter_sybase.ase import RecordedRunner
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import GoldenMaster, Suite
from nexti_pack_spring_boot import Design
from nexti_pack_spring_boot.mysql import IMAGE, MYSQL_LIMITS, cast_type, mysql_plan, mysql_type, schema, target_case
from nexti_pack_spring_boot.pack import MYSQL_PACK, wiring
from nexti_sandbox import DockerSandbox

HERE = Path(__file__).parent / "fixtures" / "pago_orden"
LEGACY = Path(__file__).resolve().parents[4] / "adapters/source/sybase/tests/fixtures/pago_orden"
SUITE = Suite.model_validate_json((LEGACY / "characterization.json").read_text(encoding="utf-8"))
SOURCE = [SourceFile("sp/sp_pago_orden.sp", (LEGACY / "sp_pago_orden.sp").read_text(encoding="utf-8"))]
MASTER: GoldenMaster = asyncio.run(RecordedRunner(LEGACY / "golden", "replay").run(SOURCE, SUITE))


def _design() -> Design:
    """The fictitious application's design with the account type stored in the reserved column `condition`."""
    data = Design.model_validate_json((HERE / "design.json").read_text(encoding="utf-8")).model_dump(mode="json")
    account = next(e for e in data["entities"] if e["table"] == "account")
    next(f for f in account["fields"] if f["name"] == "type")["column"] = "condition"
    return Design.model_validate(data)


DESIGN = _design()
PAY = DESIGN.use_cases[0]


@pytest.mark.parametrize(
    ("neutral", "mysql"),
    [
        ("decimal(19,4,signed)", "DECIMAL(19,4)"),
        ("integer(8,signed)", "TINYINT"),
        ("integer(16,signed)", "SMALLINT"),
        ("integer(32,signed)", "INT"),
        ("integer(64,signed)", "BIGINT"),
        ("integer(32,unsigned)", "INT UNSIGNED"),
        ("text(fixed,3,iso8859-1)", "CHAR(3)"),
        ("text(var,40,utf8)", "VARCHAR(40)"),
        ("text(var,max,utf8)", "TEXT"),
        ("date(yyyy-MM-dd)", "DATE"),
        ("timestamp(local)", "DATETIME(3)"),
        ("timestamp(tz)", "DATETIME(3)"),
        ("boolean", "BOOLEAN"),
        ("enum(CTE|AHO|VIR)", "VARCHAR(3)"),
    ],
)
def test_neutral_types_map_to_mysql(neutral: str, mysql: str) -> None:
    assert mysql_type(neutral) == mysql


def test_the_rows_are_cast_to_types_mysql_accepts_in_a_cast() -> None:
    neutral = ["integer(32,signed)", "text(var,40,utf8)", "decimal(19,4,signed)", "timestamp(local)", "boolean"]
    assert [cast_type(t) for t in neutral] == ["SIGNED", "CHAR", "DECIMAL(19,4)", "DATETIME(3)", "BOOLEAN"]
    case = next(r.case for r in MASTER.results if r.case.name == "separate_commission_is_a_second_debit")
    rows = target_case(DESIGN, PAY, case)["setup"]
    assert not any("AS BOOLEAN" in r or "AS VARCHAR" in r or "AS INT)" in r for r in rows)
    assert any(r.startswith("INSERT INTO company_tariff ") and r.endswith(", TRUE)") for r in rows)


def test_a_reserved_column_is_quoted_in_the_schema_the_rows_and_the_reads() -> None:
    ddl = schema(DESIGN)
    assert "`condition` CHAR(3)" in ddl
    assert "PRIMARY KEY (number, `condition`)" in ddl
    assert "separate BOOLEAN" in ddl
    assert "payment_date DATETIME(3)" in ddl
    case = next(r.case for r in MASTER.results if r.case.name == "separate_commission_is_a_second_debit")
    rows = target_case(DESIGN, PAY, case)["setup"]
    assert any(r.startswith("INSERT INTO account (number, `condition`, balance) VALUES") for r in rows)
    harness = mysql_plan(DESIGN, PAY)
    assert harness["jdbc_url"].startswith("jdbc:mysql://127.0.0.1:3306/nexti?")
    assert any("STRICT_ALL_TABLES" in s for s in harness["session"])
    assert "SET SESSION time_zone = '+00:00'" in harness["session"]
    assert harness["reset"][0].startswith("TRUNCATE TABLE ")
    assert "`condition` AS `condition`" in harness["dump"]["account"]
    assert harness["dump"]["account"].endswith("ORDER BY number, `condition`")
    assert "DATE_FORMAT(payment_date, '%Y-%m-%dT%H:%i:%s.%f') AS `payment_date`" in harness["dump"]["payment_order"]
    files = MYSQL_PACK.skeleton(DESIGN)
    assert "mysql-connector-j" in files["pom.xml"]
    assert "postgresql" not in files["pom.xml"]
    assert "MySQL 8.4" in MYSQL_PACK.adapter_request(DESIGN, "AccountRepository", files)
    assert MYSQL_PACK.describe() == {"name": "spring-boot", "image": IMAGE, "database": "mysql"}


def test_mysql_keeps_the_default_hardening_of_the_sandbox() -> None:
    assert not MYSQL_LIMITS.internal_network
    assert not MYSQL_LIMITS.writable_root
    assert MYSQL_LIMITS.user is None


def reference_project(design: Design) -> dict[str, str]:
    files = MYSQL_PACK.skeleton(design)
    path, content = wiring(design)
    files[path] = content
    files[MYSQL_PACK.service_path(design, PAY)] = (HERE / "PayOrderService.java").read_text(encoding="utf-8")
    files[MYSQL_PACK.test_path(design, PAY)] = (HERE / "PayOrderServiceTest.java").read_text(encoding="utf-8")
    for port in design.ports:
        mysql = HERE / "mysql" / f"Jdbc{port.name}.java"
        reference = mysql if mysql.exists() else HERE / f"Jdbc{port.name}.java"
        if reference.exists():
            files[MYSQL_PACK.adapter_path(design, port)] = reference.read_text(encoding="utf-8")
    return files


def _image_available() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


@pytest.fixture(scope="module")
def mysql_sandbox() -> DockerSandbox:
    box = DockerSandbox(image=IMAGE)
    if not asyncio.run(box.available()) or not _image_available():
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    return box


def test_the_reference_target_reproduces_the_golden_master_on_mysql(mysql_sandbox: DockerSandbox) -> None:
    run = asyncio.run(MYSQL_PACK.run_equivalence(mysql_sandbox, reference_project(DESIGN), DESIGN, PAY, MASTER))
    assert run.problem is None, run.problem
    assert (run.build.passed, run.build.failed) == (7, 0)
    different = {c.name: (c.failure, c.expected, c.actual) for c in run.cases if c.failure or c.expected != c.actual}
    assert len(run.cases) == 12
    assert different == {}
