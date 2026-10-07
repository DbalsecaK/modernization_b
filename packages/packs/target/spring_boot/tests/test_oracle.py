"""Oracle as the persistence of the Spring Boot pack (spec 8.4, ADR-0021): neutral types map to Oracle 23ai, a reserved
column is quoted everywhere, and the hand-written reference target of the fictitious application reproduces the 12
cases Sybase recorded against Oracle Database Free inside the sandbox. Sandbox tests skip without Docker or the image
nexti-sandbox-java-oracle:1."""

import asyncio
import subprocess
from pathlib import Path

import pytest

from nexti_adapter_sybase.ase import RecordedRunner
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import GoldenMaster, Suite
from nexti_pack_spring_boot import Design
from nexti_pack_spring_boot.oracle import IMAGE, oracle_plan, oracle_type, schema, target_case
from nexti_pack_spring_boot.pack import ORACLE_PACK, wiring
from nexti_sandbox import DockerSandbox

HERE = Path(__file__).parent / "fixtures" / "pago_orden"
LEGACY = Path(__file__).resolve().parents[4] / "adapters/source/sybase/tests/fixtures/pago_orden"
DESIGN = Design.model_validate_json((HERE / "design.json").read_text(encoding="utf-8"))
PAY = DESIGN.use_cases[0]
SUITE = Suite.model_validate_json((LEGACY / "characterization.json").read_text(encoding="utf-8"))
SOURCE = [SourceFile("sp/sp_pago_orden.sp", (LEGACY / "sp_pago_orden.sp").read_text(encoding="utf-8"))]
MASTER: GoldenMaster = asyncio.run(RecordedRunner(LEGACY / "golden", "replay").run(SOURCE, SUITE))


@pytest.mark.parametrize(
    ("neutral", "oracle"),
    [
        ("decimal(19,4,signed)", "NUMBER(19,4)"),
        ("integer(32,signed)", "NUMBER(10)"),
        ("integer(64,signed)", "NUMBER(19)"),
        ("text(fixed,3,iso8859-1)", "CHAR(3)"),
        ("text(var,40,utf8)", "VARCHAR2(40)"),
        ("text(var,max,utf8)", "VARCHAR2(4000)"),
        ("date(yyyy-MM-dd)", "DATE"),
        ("timestamp(local)", "TIMESTAMP"),
        ("timestamp(tz)", "TIMESTAMP WITH TIME ZONE"),
        ("boolean", "BOOLEAN"),
        ("enum(CTE|AHO|VIR)", "VARCHAR2(3)"),
    ],
)
def test_neutral_types_map_to_oracle(neutral: str, oracle: str) -> None:
    assert oracle_type(neutral) == oracle


def test_a_reserved_column_is_quoted_in_the_schema_the_rows_and_the_reads() -> None:
    ddl = schema(DESIGN)
    assert '"NUMBER" CHAR(10)' in ddl
    assert 'PRIMARY KEY ("NUMBER", type)' in ddl
    assert "separate BOOLEAN" in ddl
    case = next(r.case for r in MASTER.results if r.case.name == "separate_commission_is_a_second_debit")
    rows = target_case(DESIGN, PAY, case)["setup"]
    assert any(r.startswith('INSERT INTO account ("NUMBER", type, balance) VALUES') for r in rows)
    harness = oracle_plan(DESIGN, PAY)
    assert harness["jdbc_url"] == "jdbc:oracle:thin:@localhost:1521/FREEPDB1"
    assert harness["reset"][0].startswith("TRUNCATE TABLE ")
    assert '"NUMBER" AS "number"' in harness["dump"]["account"]
    assert "TO_CHAR(payment_date, 'YYYY-MM-DD\"T\"HH24:MI:SS.FF6') AS \"payment_date\"" in harness["dump"][
        "payment_order"]  # fmt: skip
    files = ORACLE_PACK.skeleton(DESIGN)
    assert "ojdbc11" in files["pom.xml"]
    assert "Oracle Database 23ai" in ORACLE_PACK.adapter_request(DESIGN, "AccountRepository", files)


def reference_project(design: Design) -> dict[str, str]:
    files = ORACLE_PACK.skeleton(design)
    path, content = wiring(design)
    files[path] = content
    files[ORACLE_PACK.service_path(design, PAY)] = (HERE / "PayOrderService.java").read_text(encoding="utf-8")
    files[ORACLE_PACK.test_path(design, PAY)] = (HERE / "PayOrderServiceTest.java").read_text(encoding="utf-8")
    for port in design.ports:
        oracle = HERE / "oracle" / f"Jdbc{port.name}.java"
        reference = oracle if oracle.exists() else HERE / f"Jdbc{port.name}.java"
        if reference.exists():
            files[ORACLE_PACK.adapter_path(design, port)] = reference.read_text(encoding="utf-8")
    return files


def _image_available() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


@pytest.fixture(scope="module")
def oracle_sandbox() -> DockerSandbox:
    box = DockerSandbox(image=IMAGE)
    if not asyncio.run(box.available()) or not _image_available():
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    return box


def test_the_reference_target_reproduces_the_golden_master_on_oracle(oracle_sandbox: DockerSandbox) -> None:
    run = asyncio.run(ORACLE_PACK.run_equivalence(oracle_sandbox, reference_project(DESIGN), DESIGN, PAY, MASTER))
    assert run.problem is None, run.problem
    assert (run.build.passed, run.build.failed) == (7, 0)
    different = {c.name: (c.failure, c.expected, c.actual) for c in run.cases if c.failure or c.expected != c.actual}
    assert len(run.cases) == 12
    assert different == {}


def test_the_sql_probe_accepts_the_reference_adapters_and_names_a_missing_table(oracle_sandbox: DockerSandbox) -> None:
    # P32 for this pack (step 12 of the plan): the reference adapters prepare against the schema; one that reads a
    # table the design does not keep comes back with the error and its statement.
    import re as _re

    files = reference_project(DESIGN)
    checked = 0
    for port in DESIGN.ports:
        path = ORACLE_PACK.adapter_path(DESIGN, port)
        if path not in files or not _re.search(r"(?i)\bFROM\s+\w", files[path]):
            continue
        assert asyncio.run(ORACLE_PACK.probe_sql(oracle_sandbox, files, path)) == "", path
        broken = _re.sub(r"(?i)\bFROM(\s+)[\w.\"]+", r"FROM\1legacy_lookup", files[path], count=1)
        errors = asyncio.run(ORACLE_PACK.probe_sql(oracle_sandbox, {**files, path: broken}, path))
        assert "legacy_lookup" in errors.lower(), errors
        assert "statement: " in errors
        checked += 1
        break
    assert checked == 1
