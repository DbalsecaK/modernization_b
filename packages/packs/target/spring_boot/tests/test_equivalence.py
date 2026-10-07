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


def test_without_the_declared_mask_the_rejected_path_output_is_masked_with_its_reason(
    java_sandbox: DockerSandbox,
) -> None:
    # P36 (ADR-0044): on a path the legacy rejects, the target raises its business error; the legacy output that
    # the design did not mask is masked automatically, declared with its reason, never silently.
    undeclared = Design.model_validate({**json.loads(DESIGN.model_dump_json()), "masks": []})
    run = asyncio.run(run_equivalence(java_sandbox, reference_project(undeclared), undeclared, PAY, MASTER))
    assert [c.name for c in run.cases if c.failure or c.expected != c.actual] == []
    declared = {m.path: m for m in run.masks}
    assert declared["outputs:@o_movimiento"].when == "rejected"
    assert declared["outputs:@o_movimiento"].reason.startswith("a rejection of the target is an exception")


def test_a_port_that_returns_an_entity_gets_every_output_of_the_program_in_one_answer() -> None:
    # ADR-0043: the stub answer carries `outputs` by field, for the harness to build the record in one call.
    data = json.loads((PACK / "design.json").read_text(encoding="utf-8"))
    data["entities"].append({"name": "DebitResult", "fields": [{"name": "sequence", "type": "integer(64,signed)"}]})
    method = data["ports"][3]["methods"][0]
    method["returns"], method["legacy_output"] = "DebitResult", None
    method["legacy_outputs"] = {"sequence": "@o_secuencial"}
    design = Design.model_validate(data)
    case = next(r.case for r in MASTER.results if r.case.name == "separate_commission_is_a_second_debit")
    target = target_case(design, design.use_cases[0], case)
    assert target["stubs"] == {
        "DebitGateway": [
            {"returns": 0, "output": None, "outputs": {"sequence": 900001}},
            {"returns": 0, "output": None, "outputs": {"sequence": None}},
        ]
    }


def test_an_output_the_program_never_assigns_is_masked_when_every_case_echoes_its_input() -> None:
    # ADR-0044: the legacy returns the caller's value; the target cannot "reproduce" that, so it is not compared.
    echoing = [
        r.model_copy(
            update={
                "case": r.case.model_copy(update={"inputs": {**r.case.inputs, "@o_movimiento": 7}}),
                "observation": r.observation.model_copy(
                    update={"outputs": {**r.observation.outputs, "@o_movimiento": "7"}}
                ),
            }
        )
        for r in MASTER.results
    ]
    master = MASTER.model_copy(update={"results": echoing, "unassigned_outputs": ["@o_movimiento"]})
    found = {m.path: m for m in masks(DESIGN, PAY, master)}
    assert found["outputs:@o_movimiento"].reason.startswith("the program never assigns this output parameter")
    assert found["outputs:@o_movimiento"].when == "always"
    # Declared unassigned but a case returned something else: it is compared (the detection was wrong).
    assert "never assigns" not in " ".join(
        m.reason for m in masks(DESIGN, PAY, MASTER.model_copy(update={"unassigned_outputs": ["@o_movimiento"]}))
    )
    assert "unassigned_outputs" not in MASTER.model_dump_json()  # the recorded runs see the same text as before


def test_a_rejected_case_compares_the_code_and_the_message_text_only() -> None:
    # P36: on a path the legacy rejects, the target raises its business error; the other outputs are a declared
    # "rejected" mask, added when the design did not declare one, and a numeric output is never the message.
    data = json.loads((PACK / "design.json").read_text(encoding="utf-8"))
    data["masks"] = [m for m in data["masks"] if m["path"] != "outputs:@o_movimiento"]
    design = Design.model_validate(data)
    found = {m.path: m for m in masks(design, PAY, MASTER)}
    assert found["outputs:@o_movimiento"].when == "rejected"
    assert found["outputs:@o_movimiento"].reason.startswith("a rejection of the target is an exception")
    assert "outputs:@o_mensaje" not in found  # the message text is compared
    # The fixture design declares the same mask: nothing is added twice (the recorded runs see the same list).
    assert [m.path for m in masks(DESIGN, PAY, MASTER)].count("outputs:@o_movimiento") == 1
    # A numeric legacy_message is an ordinary output: the error message never lands in it.
    from nexti_core.spec.equivalence import actual_view, message_field

    numeric = PAY.model_copy(update={"legacy_message": "@o_movimiento"})
    assert message_field(numeric) is None
    raw = {"error": {"code": "X", "legacy_code": "50005", "message": "ERROR EN DEBITO"}, "tables": {}, "calls": []}
    view = actual_view(design, numeric, raw, [], rejected=True)
    assert view.returns == 50005
    assert view.outputs.get("@o_movimiento") is None
