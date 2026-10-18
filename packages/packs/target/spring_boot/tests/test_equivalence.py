"""The golden master on the target (spec 11.3 check 3): legacy cases translated through the design's mappings, run
by the platform's harness on the generated project with PostgreSQL inside the sandbox, compared in one view. The
reference target of the fictitious application reproduces the 12 cases Sybase recorded; without the declared mask
the one real difference shows up. Sandbox tests skip without Docker or the image nexti-sandbox-java:2."""

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from nexti_adapter_sybase.ase import RecordedRunner
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import Case, GoldenMaster, Suite
from nexti_pack_spring_boot import IMAGE, Design, adapter_path, junit_path, service_path, skeleton
from nexti_pack_spring_boot.equivalence import (
    expected_view,
    harness_source,
    masks,
    plan,
    run_equivalence,
    target_case,
)
from nexti_sandbox import DockerSandbox
from nexti_sandbox.coverage import target_coverage

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


def test_the_effects_of_a_substitute_reach_the_target_as_an_update_or_an_insert_by_the_entity_key() -> None:
    # ADR-0055 (transactional substitutes): the rows the stub of sp_debito leaves become, through the design's
    # mappings, an UPDATE by the entity's key and the INSERT the harness runs when the update changed nothing.
    case = next(r.case for r in MASTER.results if r.case.name == "separate_commission_is_a_second_debit")
    data = json.loads(case.model_dump_json(by_alias=True))
    data["stubs"]["db_cuentas..sp_debito"][0]["effects"] = {
        "db_cuentas..ct_cuenta": [{"cta_numero": "1000000001", "cta_tipo": "CTE", "cta_saldo": "399.37"}],
        "db_other..unknown": [{"x": 1}],  # no entity keeps it: not an effect on the target
    }
    target = target_case(DESIGN, PAY, Case.model_validate(data))
    first, second = target["stubs"]["DebitGateway"]
    assert first["effects"] == [{
        "update": "UPDATE account SET balance = CAST('399.3700' AS NUMERIC(19,4)) WHERE number = CAST('1000000001' "
                  "AS CHAR(10)) AND type = CAST('CTE' AS CHAR(3))",
        "insert": "INSERT INTO account (number, type, balance) VALUES (CAST('1000000001' AS CHAR(10)), "
                  "CAST('CTE' AS CHAR(3)), CAST('399.3700' AS NUMERIC(19,4)))",
    }]  # fmt: skip
    assert "effects" not in second  # an answer without effects is what it always was
    # A row without its key is only inserted.
    data["stubs"]["db_cuentas..sp_debito"][0]["effects"] = {"db_cuentas..ct_cuenta": [{"cta_saldo": "1"}]}
    (only,) = target_case(DESIGN, PAY, Case.model_validate(data))["stubs"]["DebitGateway"][0]["effects"]
    assert only["update"] is None
    assert only["insert"].startswith("INSERT INTO account (balance)")


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

    # M29 (ADR-0049): the golden master cases run under the native coverage tool of the stack; the reference target
    # has code no case runs (the infrastructure the harness replaces), so some region is reported.
    measured = target_coverage(run.build.after_output)
    assert measured is not None, run.build.after_output[-2000:]
    assert measured.tool == "jacoco"
    assert 0 < measured.lines_covered < measured.lines_total


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


def test_a_branch_removed_from_the_target_makes_the_golden_master_differ(java_sandbox: DockerSandbox) -> None:
    # ADR-0047 (mutation of the detector): delete the separate-commission branch from the reference service; the
    # cases that exercise it in the legacy must differ, so the verdict cannot be PROVEN.
    files = reference_project(DESIGN)
    service = service_path(DESIGN, PAY)
    original = files[service]
    mutated = original.replace("if (separate && commission.signum() > 0) {", "if (false) {", 1)
    assert mutated != original
    run = asyncio.run(run_equivalence(java_sandbox, {**files, service: mutated}, DESIGN, PAY, MASTER))
    different = [c.name for c in run.cases if c.failure or c.expected != c.actual]
    assert "separate_commission_is_a_second_debit" in different


def test_against_the_legacys_engine_every_port_is_real_and_the_calls_come_from_the_log() -> None:
    # ADR-0055 (point 10): the plan points the harness at the engine on the run's network, no port is faked (the
    # called programs are the engine's substitutes), each case is prepared with the engine's own batches, and the
    # calls the comparison judges are the ones the engine logged, in legacy terms.
    from nexti_core.spec.equivalence import EngineTarget, actual_view
    from nexti_pack_spring_boot.equivalence import engine_script

    engine = EngineTarget(
        name="nexti-ase-1",
        network="nexti-eq-1",
        jdbc_url="jdbc:jtds:sybase://nexti-ase-1:5000/nexti_gm",
        user="sa",
        password="x",  # noqa: S106 - the throw-away engine's own
        setup_for=lambda case: ["use nexti_gm", f"-- {case.name}"],
        calls_query="select program, args from nexti_gm..nx_call order by seq",
        programs={"db_cuentas..sp_debito": ["@i_cuenta", "@i_tipo", "@i_valor", "@i_referencia"]},
        parse_args=lambda text: [part.split(":", 1)[1] for part in text.split("|")],
    )
    harness = plan(DESIGN, PAY, engine)
    assert harness["jdbc_url"] == engine.jdbc_url
    assert harness["reset"] == []
    assert harness["calls"] == engine.calls_query
    assert all(p["adapter"] for p in harness["ports"])  # DebitGateway too: the substitute answers for real
    assert harness["ports"][3]["adapter"] == "com.bancoficticio.payments.adapters.out.jdbc.JdbcDebitGateway"
    case = next(r.case for r in MASTER.results if r.case.name == "separate_commission_is_a_second_debit")
    target = target_case(DESIGN, PAY, case, engine=engine)
    assert target["setup"] == ["use nexti_gm", "-- separate_commission_is_a_second_debit"]
    assert target["stubs"] == {}
    script = engine_script(engine)
    assert "/dev/tcp/nexti-ase-1/5000" in script
    assert "initdb" not in script
    assert 'jdbc.queryForList(plan.get("calls").asText())' in harness_source()
    logged = engine.calls(
        [{"program": "db_cuentas..sp_debito", "args": "10:1000000001|3:CTE|8:100.0000|10:PAGO ORDEN"}]
    )
    raw = {"response": {"movement": "900001", "message": "PAGO REALIZADO"}, "tables": {}, "calls": []}
    view = actual_view(DESIGN, PAY, raw, [], legacy_calls=logged)
    assert [c.program for c in view.calls] == ["db_cuentas..sp_debito"]
    assert view.calls[0].arguments["@i_valor"] == "100.0000"


def test_the_return_status_of_a_called_program_travels_as_data_when_the_design_maps_it() -> None:
    # ADR-0055 (phase F): a field mapped to the reserved name `return` carries the status; the fake delivers it
    # (carries_status) instead of throwing, as the legacy reads @w_return and goes on.
    data = json.loads(DESIGN.model_dump_json(by_alias=True))
    port = next(p for p in data["ports"] if p.get("legacy_program"))
    data["entities"].append(
        {
            "name": "DebitResult",
            "key": [],
            "fields": [
                {"name": "status", "type": "integer(32,signed)", "legacy": "return"},
                {"name": "sequence", "type": "integer(64,signed)", "legacy": "@o_secuencial"},
            ],
        }
    )
    port["methods"][0].update(
        {
            "returns": "DebitResult",
            "legacy_output": None,
            "legacy_outputs": {"status": "return", "sequence": "@o_secuencial"},
        }
    )
    design = Design.model_validate(data)
    case = next(r.case for r in MASTER.results if r.case.stubs)
    (first, *_) = target_case(design, design.use_cases[0], case)["stubs"][port["name"]]
    assert first["carries_status"] is True
    assert first["outputs"]["status"] == first["returns"]
    assert "sequence" in first["outputs"]


def test_the_engines_call_log_is_canonicalised_by_the_substitutes_parameter_types() -> None:
    # Phase F: a `char(4)` the substitute logged as `C1  ` is the `C1` the characterization recorded; without the
    # type every case of a real run differed on the padding alone and the convergence could not move.
    from nexti_core.spec.equivalence import EngineTarget

    engine = EngineTarget(
        name="e", network="n", jdbc_url="jdbc:jtds:sybase://e:5000/gm", user="sa",
        password="x",  # noqa: S106 - the throw-away engine's own
        setup_for=lambda case: [], calls_query="select 1",
        programs={"db_cuentas..sp_debito": ["@i_cuenta", "@i_tipo", "@i_valor", "@i_referencia"]},
        parse_args=lambda text: list[str | None](text.split("|")),
        types={"db_cuentas..sp_debito": ["text(fixed,10,iso8859-1)", "text(fixed,4,iso8859-1)",
                                         "decimal(19,4,signed)", None]},
    )  # fmt: skip
    (call,) = engine.calls([{"program": "DB_CUENTAS..SP_DEBITO", "args": "1234567890|C1  |100|REF "}])
    assert call.arguments == {"@i_cuenta": "1234567890", "@i_tipo": "C1", "@i_valor": "100.0000",
                              "@i_referencia": "REF "}  # fmt: skip


def test_the_programs_own_status_is_read_from_the_response_when_the_use_case_maps_it() -> None:
    # Phase F: a legacy whose error exit returns 0 with the code in an output parameter signals errors as data;
    # the use case maps the status with the reserved name `return` and the comparison reads it from the response
    # (never as an output, never masked as a rejected-path output).
    from nexti_core.spec.equivalence import actual_view, masks

    data = json.loads(DESIGN.model_dump_json(by_alias=True))
    data["use_cases"][0]["outputs"].append({"name": "status", "type": "integer(32,signed)", "legacy": "return"})
    design = Design.model_validate(data)
    use_case = design.use_cases[0]
    response: dict[str, str] = {"movement": "900001", "message": "PAGO REALIZADO", "status": "0"}
    raw: dict[str, Any] = {"response": response, "tables": {}, "calls": []}
    assert actual_view(design, use_case, raw, []).returns == 0
    response["status"] = "120000"
    view = actual_view(design, use_case, raw, [])
    assert view.returns == 120000
    assert view.outputs["@o_movimiento"] == "900001"
    assert "return" not in view.outputs
    response.pop("status")
    assert actual_view(design, use_case, raw, []).returns == 0
    found = masks(design, use_case, MASTER)
    assert not any(m.path.lower() == "outputs:return" for m in found)
    # A thrown rejection still reads as the legacy code.
    thrown = {"error": {"code": "X", "legacy_code": "50005", "message": "m"}, "tables": {}, "calls": []}
    assert actual_view(design, use_case, thrown, []).returns == 50005
