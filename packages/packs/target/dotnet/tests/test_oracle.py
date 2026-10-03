"""Oracle as the persistence of the .NET pack (spec 8.4, ADR-0031): neutral types map to Oracle 23ai, a reserved column
is quoted everywhere, and the hand-written reference target of the fictitious application (the same core as the SQL
Server reference, with Oracle adapters) passes its tests and reproduces the 12 cases Sybase recorded against Oracle
Database Free inside the sandbox; a canary change is caught. Sandbox tests skip without Docker or the image
nexti-sandbox-dotnet-oracle:1."""

import asyncio
import subprocess
from pathlib import Path

import pytest

from nexti_adapter_sybase.ase import RecordedRunner
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import GoldenMaster, Suite
from nexti_core.spec.design import Design
from nexti_pack_dotnet.canary import mutations
from nexti_pack_dotnet.oracle import IMAGE, ORACLE_PACKAGES, oracle_plan, oracle_type, schema, target_case
from nexti_pack_dotnet.pack import ORACLE_PACK, PACK
from nexti_sandbox import DockerSandbox

HERE = Path(__file__).parent / "fixtures" / "pago_orden"
PACKS = Path(__file__).resolve().parents[2]
LEGACY = PACKS.parents[1] / "adapters/source/sybase/tests/fixtures/pago_orden"
DESIGN = Design.model_validate_json((PACKS / "spring_boot/tests/fixtures/pago_orden/design.json").read_text("utf-8"))
PAY = DESIGN.use_cases[0]
SUITE = Suite.model_validate_json((LEGACY / "characterization.json").read_text(encoding="utf-8"))
SOURCE = [SourceFile("sp/sp_pago_orden.sp", (LEGACY / "sp_pago_orden.sp").read_text(encoding="utf-8"))]
MASTER: GoldenMaster = asyncio.run(RecordedRunner(LEGACY / "golden", "replay").run(SOURCE, SUITE))
SEED = PACKS.parents[2] / "infra/sandbox/dotnet-oracle/seed/Seed.csproj"


def reference_project(design: Design) -> dict[str, str]:
    """The same service and tests as the SQL Server reference, with the Oracle adapters."""
    files = ORACLE_PACK.skeleton(design)
    files[ORACLE_PACK.service_path(design, PAY)] = (HERE / "PayOrderService.cs").read_text(encoding="utf-8")
    files[ORACLE_PACK.test_path(design, PAY)] = (HERE / "PayOrderServiceTests.cs").read_text(encoding="utf-8")
    for port in design.ports:
        files[ORACLE_PACK.adapter_path(design, port)] = (HERE / "oracle" / f"Sql{port.name}.cs").read_text("utf-8")
    return files


@pytest.mark.parametrize(
    ("neutral", "oracle"),
    [
        ("decimal(19,4,signed)", "NUMBER(19,4)"),
        ("integer(32,signed)", "NUMBER(10)"),
        ("integer(64,signed)", "NUMBER(19)"),
        ("text(fixed,3,iso8859-1)", "CHAR(3)"),
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


def test_the_skeleton_carries_the_oracle_schema_client_and_session() -> None:
    files = ORACLE_PACK.skeleton(DESIGN)
    assert files["src/App/Db/schema.sql"] == schema(DESIGN)
    assert '"NUMBER" CHAR(10)' in files["src/App/Db/schema.sql"]
    assert 'PRIMARY KEY ("NUMBER", type)' in files["src/App/Db/schema.sql"]
    project = files["src/App/App.csproj"]
    assert 'Include="Oracle.ManagedDataAccess.Core" Version="23.26.301"' in project
    assert "Microsoft.Data.SqlClient" not in project
    db = files["src/App/Infrastructure/Db.cs"]
    assert "using Oracle.ManagedDataAccess.Client;" in db
    assert "public OracleCommand Command(string sql)" in db
    assert "command.BindByName = true;" in db
    assert "Sql" not in db.replace("sql", "")
    assert {p for p in files if ORACLE_PACK.held_back(p)} == {p for p in PACK.skeleton(DESIGN) if PACK.held_back(p)}
    request = ORACLE_PACK.adapter_request(DESIGN, "AccountRepository", files)
    assert "Oracle Database 23ai" in request
    assert "Bancoficticio.Payments.Adapters.Out.Sql.SqlAccountRepository" in request


def test_the_image_restores_the_packages_the_projects_use() -> None:
    seed = SEED.read_text(encoding="utf-8")
    for name, version in ORACLE_PACKAGES.items():
        assert f'Include="{name}" Version="{version}"' in seed


def test_a_reserved_column_is_quoted_in_the_rows_and_the_reads() -> None:
    case = next(r.case for r in MASTER.results if r.case.name == "separate_commission_is_a_second_debit")
    rows = target_case(DESIGN, PAY, case)["setup"]
    assert any(r.startswith('INSERT INTO account ("NUMBER", type, balance) VALUES') for r in rows)
    harness = oracle_plan(DESIGN, PAY)
    assert harness["provider"] == "Oracle.ManagedDataAccess.Client.OracleConnection, Oracle.ManagedDataAccess"
    assert "Data Source=localhost:1521/FREEPDB1" in harness["connection"]
    assert any("NLS_TIMESTAMP_FORMAT" in s for s in harness["session"])
    assert harness["reset"][0].startswith("TRUNCATE TABLE ")
    assert '"NUMBER" AS "number"' in harness["dump"]["account"]
    assert "TO_CHAR(payment_date, 'YYYY-MM-DD\"T\"HH24:MI:SS.FF6') AS \"payment_date\"" in harness["dump"][
        "payment_order"]  # fmt: skip
    assert harness["ports"][3] == {"interface": "Bancoficticio.Payments.Domain.Port.DebitGateway, App", "adapter": None}


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


def test_the_skeleton_alone_compiles_on_the_oracle_image(oracle_sandbox: DockerSandbox) -> None:
    files = {p: c for p, c in ORACLE_PACK.skeleton(DESIGN).items() if not ORACLE_PACK.held_back(p)}
    build = asyncio.run(ORACLE_PACK.compile_and_test(oracle_sandbox, files, run_tests=False))
    assert build.compiled, build.compile_errors


def test_the_reference_target_reproduces_the_golden_master_on_oracle(oracle_sandbox: DockerSandbox) -> None:
    run = asyncio.run(ORACLE_PACK.run_equivalence(oracle_sandbox, reference_project(DESIGN), DESIGN, PAY, MASTER))
    assert run.problem is None, run.problem
    assert (run.build.passed, run.build.failed) == (7, 0)
    different = {c.name: (c.failure, c.expected, c.actual) for c in run.cases if c.failure or c.expected != c.actual}
    assert len(run.cases) == 12
    assert different == {}


def test_a_canary_change_is_caught_on_oracle(oracle_sandbox: DockerSandbox) -> None:
    files = reference_project(DESIGN)
    path = ORACLE_PACK.service_path(DESIGN, PAY)
    mutation = ORACLE_PACK.mutations(files[path])[0]
    assert mutation == mutations(files[path])[0]
    files[path] = mutation.source
    run = asyncio.run(ORACLE_PACK.run_equivalence(oracle_sandbox, files, DESIGN, PAY, MASTER))
    assert run.problem is None, run.problem
    caught = run.build.failed > 0 or any(c.failure or c.expected != c.actual for c in run.cases)
    assert caught, mutation.after
