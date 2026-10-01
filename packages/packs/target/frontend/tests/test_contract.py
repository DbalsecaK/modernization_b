"""The contract of the frontend packs (ADR-0016), derived by code: the OpenAPI of the approved design follows the
controllers of the Spring Boot pack, the typed client follows the OpenAPI, and the screen contract follows the screen
specs of the fictitious BMS application."""

import json
from pathlib import Path

from nexti_adapter_bms import BmsAdapter
from nexti_core.adapters import SourceFile
from nexti_core.spec.screens import ScreenSpec
from nexti_pack_frontend import contract_of, describe, openapi, runtime, typescript_client
from nexti_pack_spring_boot import Design

ROOT = Path(__file__).resolve().parents[5]
DESIGN = Design.model_validate_json(
    (ROOT / "packages/packs/target/spring_boot/tests/fixtures/pago_orden/design.json").read_text(encoding="utf-8")
)
BMS = ROOT / "packages/adapters/source/bms/tests/fixtures/pagos/PAGOSET.bms"


def test_the_openapi_follows_the_design_and_the_controllers() -> None:
    contract = openapi(DESIGN)
    assert contract["openapi"] == "3.1.0"
    (path,) = contract["paths"]
    use_case = DESIGN.use_cases[0]
    operation = contract["paths"][path][use_case.http_method.lower()]
    assert path.startswith(f"/api/{DESIGN.context}/")
    assert operation["operationId"][0].islower()
    assert operation["x-rules"] == list(use_case.rules)
    request = contract["components"]["schemas"][f"{use_case.name}Request"]
    assert set(request["properties"]) == {f.name for f in use_case.inputs}
    assert all("x-neutral" in s for s in request["properties"].values())
    assert "422" in operation["responses"]
    assert json.loads(json.dumps(contract)) == contract  # plain JSON


def test_the_typed_client_has_a_method_per_operation() -> None:
    source = typescript_client(openapi(DESIGN))
    use_case = DESIGN.use_cases[0]
    assert f"export interface {use_case.name}Request {{" in source
    assert f"export interface {use_case.name}Response {{" in source
    assert "export { ApiError } from './client-runtime'" in source
    assert f"{use_case.name[0].lower()}{use_case.name[1:]}(request: {use_case.name}Request)" in source
    assert "export function createApi(" in source
    assert "export class ApiError extends Error" in runtime()


def test_the_screen_contract_follows_the_screen_specs() -> None:
    screens = {s.id: s for s in BmsAdapter().screens([SourceFile("maps/PAGOSET.bms", BMS.read_text(encoding="utf-8"))])}
    order = contract_of(screens["SCR-PAGOORD"])
    assert (order.module, order.component) == ("pagoord", "PagoordScreen")
    fields = {f.name: f for f in order.fields}
    assert fields["ORDEN"].required
    assert fields["ORDEN"].numeric
    assert fields["ORDEN"].length == 7
    assert fields["CLAVE"].secret
    assert fields["MENSAJE"].kind == "output"
    assert "ENTER" in {a.key for a in order.actions}
    text = describe(order)
    assert 'data-field="ORDEN"' in text
    assert "required" in text


def test_the_first_button_of_a_web_screen_submits_its_form() -> None:
    """A screen of Flow 2 (no terminal grid): its first button calls the backend, so it is the submit, not a plain
    navigation the harness would click with the required fields empty."""
    screen = ScreenSpec.model_validate({
        "id": "SCR-SIMULADOR", "name": "Simulador",
        "fields": [{"name": "monto", "kind": "input", "length": 0, "required": True, "type": "decimal(12,2,signed)"}],
        "actions": [{"key": "calcular", "label": "Calcular", "target": "SCR-RESULTADO"},
                    {"key": "limpiar", "label": "Limpiar"}],
    })  # fmt: skip
    contract = contract_of(screen)
    assert [(a.key, a.label, a.target) for a in contract.actions] == [("ENTER", "Calcular", None),
                                                                       ("limpiar", "Limpiar", None)]  # fmt: skip
    assert contract.fields[0].numeric
    assert "no length limit" in describe(contract)
