"""The .NET 10 pack (spec 8.4, ADR-0017): neutral types map exactly to C# and SQL Server, the skeleton follows from
the design, and a hand-written reference target of the fictitious application builds, passes its tests and
reproduces the 12 cases Sybase recorded (the same golden master as the Java pack); without the declared mask the one
real difference shows up. Sandbox tests skip without Docker or the image nexti-sandbox-dotnet:1."""

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from nexti_adapter_sybase.ase import RecordedRunner
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import GoldenMaster, Suite
from nexti_core.spec.design import Design
from nexti_pack_dotnet import IMAGE, cs_type, layer_of, namespace, skeleton, sql_type
from nexti_pack_dotnet.canary import mutations
from nexti_pack_dotnet.equivalence import plan, run_equivalence, target_case
from nexti_pack_dotnet.pack import PACK
from nexti_sandbox import DockerSandbox

HERE = Path(__file__).parent / "fixtures" / "pago_orden"
PACKS = Path(__file__).resolve().parents[2]
LEGACY = PACKS.parents[1] / "adapters/source/sybase/tests/fixtures/pago_orden"
DESIGN = Design.model_validate_json((PACKS / "spring_boot/tests/fixtures/pago_orden/design.json").read_text("utf-8"))
PAY = DESIGN.use_cases[0]
SUITE = Suite.model_validate_json((LEGACY / "characterization.json").read_text(encoding="utf-8"))
SOURCE = [SourceFile("sp/sp_pago_orden.sp", (LEGACY / "sp_pago_orden.sp").read_text(encoding="utf-8"))]
MASTER: GoldenMaster = asyncio.run(RecordedRunner(LEGACY / "golden", "replay").run(SOURCE, SUITE))


def reference_project(design: Design) -> dict[str, str]:
    files = PACK.skeleton(design)
    files[PACK.service_path(design, PAY)] = (HERE / "PayOrderService.cs").read_text(encoding="utf-8")
    files[PACK.test_path(design, PAY)] = (HERE / "PayOrderServiceTests.cs").read_text(encoding="utf-8")
    for port in design.ports:
        files[PACK.adapter_path(design, port)] = (HERE / f"Sql{port.name}.cs").read_text(encoding="utf-8")
    return files


@pytest.mark.parametrize(
    ("neutral", "cs", "sql"),
    [
        ("decimal(19,4,signed)", "decimal?", "DECIMAL(19,4)"),
        ("integer(32,signed)", "int?", "INT"),
        ("integer(64,signed)", "long?", "BIGINT"),
        ("integer(32,unsigned)", "long?", "BIGINT"),
        ("text(fixed,3,iso8859-1)", "string?", "NCHAR(3)"),
        ("text(var,max,utf8)", "string?", "NVARCHAR(MAX)"),
        ("timestamp(local)", "DateTime?", "DATETIME2"),
        ("timestamp(tz)", "DateTimeOffset?", "DATETIMEOFFSET"),
        ("date(yyyy-MM-dd)", "DateOnly?", "DATE"),
        ("boolean", "bool?", "BIT"),
        ("enum(CTE|AHO|VIR)", "string?", "NVARCHAR(3)"),
    ],
)
def test_neutral_types_map_to_csharp_and_sql_server(neutral: str, cs: str, sql: str) -> None:
    assert (cs_type(neutral), sql_type(neutral)) == (cs, sql)


def test_the_skeleton_follows_from_the_design() -> None:
    files = skeleton(DESIGN)
    assert namespace(DESIGN) == "Bancoficticio.Payments"
    assert "public sealed record PaymentOrder(" in files["src/App/Domain/Model/PaymentOrder.cs"]
    assert "long Debit(string? account, string? type, decimal? amount, string? reference);" in files[
        "src/App/Domain/Port/DebitGateway.cs"]  # fmt: skip
    assert "CREATE TABLE payment_order" in files["src/App/Db/schema.sql"]
    assert "PRIMARY KEY (order_number, company)" in files["src/App/Db/schema.sql"]
    assert 'Include="Microsoft.Data.SqlClient" Version="6.1.7"' in files["src/App/App.csproj"]
    assert '[HttpPost("orders/pay")]' in files["src/App/Adapters/In/Rest/PayOrderController.cs"]
    assert {p for p in files if PACK.held_back(p)} == {
        "src/App/Program.cs", "src/App/Wiring.cs", "src/App/Adapters/In/Rest/PayOrderController.cs",
    }  # fmt: skip
    assert layer_of("src/App/Adapters/In/Rest/PayOrderRequest.cs", DESIGN) == "contracts"
    assert layer_of("src/App/Application/PayOrderService.cs", DESIGN) == "domain"
    assert layer_of("src/App/Adapters/Out/Sql/SqlOrderRepository.cs", DESIGN) == "adapters"
    assert layer_of("tests/App.Tests/PayOrderServiceTests.cs", DESIGN) == "tests"


def test_the_answer_must_carry_csharp() -> None:
    assert PACK.code_block("Here:\n```csharp\npublic sealed class A {}\n```").startswith("public sealed class A")
    with pytest.raises(ValueError, match="no C# class"):
        PACK.code_block("```java\nint x = 1;\n```")


def test_the_canary_changes_one_line_deterministically() -> None:
    source = (HERE / "PayOrderService.cs").read_text(encoding="utf-8")
    found = mutations(source)
    assert len(found) == 3
    assert found == mutations(source)
    assert all(m.before != m.after and m.after in m.source for m in found)


def test_a_legacy_case_is_translated_with_sql_server_types() -> None:
    case = next(r.case for r in MASTER.results if r.case.name == "separate_commission_is_a_second_debit")
    target = target_case(DESIGN, PAY, case)
    assert (
        "INSERT INTO company_tariff (company, service, amount, separate) VALUES (CAST('10' AS INT), "
        "CAST('AGUA' AS NVARCHAR(10)), CAST('1.5000' AS DECIMAL(19,4)), CAST('true' AS BIT))"
    ) in target["setup"]
    harness = plan(DESIGN, PAY)
    assert harness["ports"][3] == {"interface": "Bancoficticio.Payments.Domain.Port.DebitGateway, App", "adapter": None}
    assert harness["reset"][0].startswith("TRUNCATE TABLE ")


def _image_available() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


@pytest.fixture(scope="module")
def dotnet_sandbox() -> DockerSandbox:
    box = DockerSandbox(image=IMAGE)
    if not asyncio.run(box.available()) or not _image_available():
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    return box


def test_the_skeleton_alone_compiles(dotnet_sandbox: DockerSandbox) -> None:
    files = {p: c for p, c in PACK.skeleton(DESIGN).items() if not PACK.held_back(p)}
    build = asyncio.run(PACK.compile_and_test(dotnet_sandbox, files, run_tests=False))
    assert build.compiled, build.compile_errors


def test_the_service_and_its_tests_pass_before_the_host_joins(dotnet_sandbox: DockerSandbox) -> None:
    """The generation's middle step: the service and its tests, while the host, wiring and controllers wait."""
    files = {p: c for p, c in reference_project(DESIGN).items() if not PACK.held_back(p) and "/Adapters/Out/" not in p}
    build = asyncio.run(PACK.compile_and_test(dotnet_sandbox, files))
    assert build.compiled, build.compile_errors
    assert (build.passed, build.failed) == (7, 0)


def test_a_compile_error_is_reported(dotnet_sandbox: DockerSandbox) -> None:
    files = reference_project(DESIGN)
    files[PACK.service_path(DESIGN, PAY)] += "\nthis is not C#\n"
    build = asyncio.run(PACK.compile_and_test(dotnet_sandbox, files))
    assert not build.compiled
    assert "PayOrderService.cs" in build.compile_errors


def test_the_reference_target_reproduces_the_golden_master(dotnet_sandbox: DockerSandbox) -> None:
    run = asyncio.run(run_equivalence(dotnet_sandbox, reference_project(DESIGN), DESIGN, PAY, MASTER))
    assert run.problem is None, run.problem
    assert (run.build.passed, run.build.failed) == (7, 0)
    different = {c.name: (c.failure, c.expected, c.actual) for c in run.cases if c.failure or c.expected != c.actual}
    assert len(run.cases) == 12
    assert different == {}


def test_without_the_declared_mask_the_real_difference_shows(dotnet_sandbox: DockerSandbox) -> None:
    undeclared = Design.model_validate({**json.loads(DESIGN.model_dump_json()), "masks": []})
    run = asyncio.run(run_equivalence(dotnet_sandbox, reference_project(undeclared), undeclared, PAY, MASTER))
    different = {c.name: c for c in run.cases if c.expected != c.actual}
    assert list(different) == ["failed_commission_undoes_the_payment"]
    case = different["failed_commission_undoes_the_payment"]
    assert case.expected.outputs["@o_movimiento"] == "900001"
    assert case.actual.outputs["@o_movimiento"] is None


def test_a_probe_names_each_service_and_adapter_as_the_wiring_does() -> None:
    probe = PACK.probe(DESIGN, PACK.adapter_path(DESIGN, DESIGN.ports[0]))
    assert "typeof(Bancoficticio.Payments.Adapters.Out.Sql.SqlOrderRepository)" in probe["src/App/Probe.cs"]
    assert "Bancoficticio.Payments.Application.PayOrderService" in PACK.probe(DESIGN, PACK.service_path(DESIGN, PAY))[
        "src/App/Probe.cs"]  # fmt: skip
    assert PACK.probe(DESIGN, "src/App/Db/schema.sql") == {}


def test_an_adapter_in_another_namespace_does_not_compile(dotnet_sandbox: DockerSandbox) -> None:
    files = reference_project(DESIGN)
    port = DESIGN.ports[0]
    target = PACK.adapter_path(DESIGN, port)
    files[target] = files[target].replace("namespace Bancoficticio.Payments.Adapters.Out.Sql;",
                                          "namespace Bancoficticio.Payments.Adapters.Out.Sql.Wrong;")  # fmt: skip
    files = {p: c for p, c in files.items() if not PACK.held_back(p)} | PACK.probe(DESIGN, target)
    build = asyncio.run(PACK.compile_and_test(dotnet_sandbox, files, run_tests=False))
    assert not build.compiled
    assert "Probe.cs" in build.compile_errors
