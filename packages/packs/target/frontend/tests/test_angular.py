"""The Angular pack in the real sandbox (ADR-0016): the skeleton with the hand-written reference screens of the
fictitious BMS application compiles with ngc (strict templates), bundles and passes the platform's harness on every
screen; a screen that breaks the contract or its template types fails with the reason. Skipped without Docker or the
image nexti-sandbox-frontend:2."""

from pathlib import Path

from nexti_adapter_bms import BmsAdapter
from nexti_core.adapters import SourceFile
from nexti_pack_frontend import ScreenContract, contract_of, openapi
from nexti_pack_frontend import angular as pack
from nexti_pack_frontend.build import FrontendRun, build_and_test
from nexti_pack_spring_boot import Design
from nexti_sandbox import DockerSandbox

ROOT = Path(__file__).resolve().parents[5]
DESIGN = Design.model_validate_json(
    (ROOT / "packages/packs/target/spring_boot/tests/fixtures/pago_orden/design.json").read_text(encoding="utf-8")
)
BMS = ROOT / "packages/adapters/source/bms/tests/fixtures/pagos/PAGOSET.bms"
CONTRACTS = [contract_of(s) for s in BmsAdapter().screens([SourceFile("maps/PAGOSET.bms", BMS.read_text("utf-8"))])]


def order() -> ScreenContract:
    return next(c for c in CONTRACTS if c.id == "SCR-PAGOORD")


FIXTURES = Path(__file__).parent / "fixtures" / "angular"


def project(pages: dict[str, str] | None = None) -> dict[str, str]:
    files = pack.skeleton(openapi(DESIGN), CONTRACTS, "Pagos")
    for contract in CONTRACTS:
        files[pack.screen_path(contract)] = (FIXTURES / f"{contract.module}.component.ts").read_text(encoding="utf-8")
    files.update(pages or {})
    return files


async def run(box: DockerSandbox, files: dict[str, str]) -> FrontendRun:
    return await build_and_test(box, "angular", files, CONTRACTS)


async def test_the_reference_screens_compile_and_pass_the_harness(sandbox: DockerSandbox) -> None:
    result = await run(sandbox, project())
    assert result.ok, result.diagnostic()
    screen = result.screen("SCR-PAGOORD")
    assert screen is not None
    assert {c.key: c.status for c in screen.checks} == {
        "mounts": "passed", "fields": "passed", "actions": "passed", "validation": "passed",
        "accessibility": "passed", "submit": "passed",
    }  # fmt: skip
    assert "payOrder" in next(c.detail for c in screen.checks if c.key == "submit")


async def test_a_screen_that_breaks_the_contract_fails_with_the_reason(sandbox: DockerSandbox) -> None:
    source = (FIXTURES / "pagoord.component.ts").read_text(encoding="utf-8")
    broken = (source.replace('data-field="ORDEN"', "")
              .replace("if (this.form.invalid) return", "")
              .replace('for="empresa">Empresa ', 'for="empresa">'))  # fmt: skip
    result = await run(sandbox, project({pack.screen_path(order()): broken}))
    screen = result.screen("SCR-PAGOORD")
    assert screen is not None
    problems = " ".join(screen.problems())
    assert "ORDEN: missing" in problems
    assert "EMPRESA: no accessible label" in problems
    assert "validation:" in problems


async def test_a_template_that_does_not_type_check_does_not_compile(sandbox: DockerSandbox) -> None:
    source = (
        (FIXTURES / "pagoord.component.ts").read_text(encoding="utf-8").replace("missing('ORDEN')", "missing('NADA')")
    )
    result = await run(sandbox, project({pack.screen_path(order()): source}))
    assert not result.compiled
    assert any("pagoord.component.ts" in e for e in result.errors), result.errors
