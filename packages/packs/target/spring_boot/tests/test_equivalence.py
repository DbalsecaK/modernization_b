"""The golden master on the target (spec 11.3 check 3): legacy cases translated through the design's mappings, run
by the platform's harness on the generated project with PostgreSQL inside the sandbox, compared in one view. The
reference target of the fictitious application reproduces the 12 cases Sybase recorded; without the declared mask
the one real difference shows up. Sandbox tests skip without Docker or the image nexti-sandbox-java:2."""

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from nexti_adapter_sybase.ase import RecordedRunner
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import GoldenMaster, Suite
from nexti_pack_spring_boot import IMAGE, Design, adapter_path, junit_path, service_path, skeleton
from nexti_pack_spring_boot.equivalence import expected_view, masks, plan, run_equivalence, target_case
from nexti_sandbox import DockerSandbox

PACK = Path(__file__).parent / "fixtures" / "pago_orden"
LEGACY = Path(__file__).resolve().parents[4] / "adapters/source/sybase/tests/fixtures/pago_orden"
DESIGN = Design.model_validate_json((PACK / "design.json").read_text(encoding="utf-8"))
PAY = DESIGN.use_cases[0]
SUITE = Suite.model_validate_json((LEGACY / "characterization.json").read_text(encoding="utf-8"))
SOURCE = [SourceFile("sp/sp_pago_orden.sp", (LEGACY / "sp_pago_orden.sp").read_text(encoding="utf-8"))]
MASTER: GoldenMaster = asyncio.run(RecordedRunner(LEGACY / "golden", "replay").run(SOURCE, SUITE))


def reference_project(design: Design) -> dict[str, str]:
    from nexti_orchestration.generation import wiring

    files = skeleton(design)
    path, content = wiring(design)
    files[path] = content
    files[service_path(design, PAY)] = (PACK / "PayOrderService.java").read_text(encoding="utf-8")
    files[junit_path(design, PAY)] = (PACK / "PayOrderServiceTest.java").read_text(encoding="utf-8")
    for port in design.ports:
        reference = PACK / f"Jdbc{port.name}.java"
        if reference.exists():
            files[adapter_path(design, port)] = reference.read_text(encoding="utf-8")
    return files


def test_a_legacy_case_is_translated_through_the_mappings() -> None:
    case = next(r.case for r in MASTER.results if r.case.name == "separate_commission_is_a_second_debit")
    target = target_case(DESIGN, PAY, case)
    assert target["request"]["channel"] == "OFI"
    assert target["request"]["amount"] == "100.0000"
    assert target["request"]["processingDate"] == "2026-03-02T09:30:00.000"
    assert (
        "INSERT INTO company_tariff (company, service, amount, separate) VALUES (CAST('10' AS INTEGER), "
        "CAST('AGUA' AS VARCHAR(10)), CAST('1.5000' AS NUMERIC(19,4)), CAST('true' AS BOOLEAN))"
    ) in target["setup"]
    assert target["stubs"] == {"DebitGateway": [{"returns": 0, "output": 900001}, {"returns": 0, "output": None}]}
    harness = plan(DESIGN, PAY)
    assert harness["ports"][3] == {"interface": "com.bancoficticio.payments.domain.port.DebitGateway", "adapter": None}
    assert harness["dump"]["payment_order"].endswith("ORDER BY order_number, company")


def test_what_cannot_be_compared_is_declared_with_its_reason() -> None:
    declared = {m.path: m for m in masks(DESIGN, PAY, MASTER)}
    assert set(declared) == {"outputs:@o_movimiento", "calls:cobis..sp_cerror"}
    assert declared["outputs:@o_movimiento"].when == "rejected"
    rejected = next(r.observation for r in MASTER.results if r.case.name == "account_type_not_allowed")
    view = expected_view(DESIGN, PAY, rejected, list(declared.values()))
    assert view.calls == []  # the error log of the legacy is infrastructure
    assert "@o_movimiento" not in view.outputs
    assert view.tables["db_admin..ad_tarifa_empresa"] == []


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


def test_the_reference_target_reproduces_the_golden_master(java_sandbox: DockerSandbox) -> None:
    run = asyncio.run(run_equivalence(java_sandbox, reference_project(DESIGN), DESIGN, PAY, MASTER))
    assert run.problem is None
    assert run.build.passed == 7
    assert run.build.failed == 0
    different = [c.name for c in run.cases if c.failure or c.expected != c.actual]
    assert len(run.cases) == 12
    assert different == []


def test_without_the_declared_mask_the_real_difference_shows(java_sandbox: DockerSandbox) -> None:
    undeclared = Design.model_validate({**json.loads(DESIGN.model_dump_json()), "masks": []})
    run = asyncio.run(run_equivalence(java_sandbox, reference_project(undeclared), undeclared, PAY, MASTER))
    different = {c.name: c for c in run.cases if c.expected != c.actual}
    assert list(different) == ["failed_commission_undoes_the_payment"]
    case = different["failed_commission_undoes_the_payment"]
    assert case.expected.outputs["@o_movimiento"] == "900001"
    assert case.actual.outputs["@o_movimiento"] is None
