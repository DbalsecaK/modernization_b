"""The React pack in the real sandbox (ADR-0016): the skeleton with the hand-written reference pages of the
fictitious BMS application compiles (tsc strict), bundles and passes the platform's harness on every screen; a page
that loses a field, skips a validation, breaks accessibility or does not type-check fails with the reason. Skipped
without Docker or the image nexti-sandbox-frontend:1."""

from pathlib import Path

from nexti_adapter_bms import BmsAdapter
from nexti_core.adapters import SourceFile
from nexti_pack_frontend import ScreenContract, contract_of, openapi
from nexti_pack_frontend import react as pack
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


FIXTURES = Path(__file__).parent / "fixtures" / "react"


def project(pages: dict[str, str] | None = None) -> dict[str, str]:
    files = pack.skeleton(openapi(DESIGN), CONTRACTS, "Pagos")
    for contract in CONTRACTS:
        files[pack.screen_path(contract)] = (FIXTURES / f"{contract.module}.tsx").read_text(encoding="utf-8")
    files.update(pages or {})
    return files


async def run(sandbox: DockerSandbox, files: dict[str, str]) -> FrontendRun:
    return await build_and_test(sandbox, "react", files, CONTRACTS)


async def test_the_reference_pages_compile_and_pass_the_harness(sandbox: DockerSandbox) -> None:
    result = await run(sandbox, project())
    assert result.ok, result.diagnostic()
    screen = result.screen("SCR-PAGOORD")
    assert screen is not None
    checks = {c.key: c.status for c in screen.checks}
    assert checks == {"mounts": "passed", "fields": "passed", "actions": "passed", "validation": "passed",
                      "accessibility": "passed", "submit": "passed"}  # fmt: skip
    assert "payOrder" in next(c.detail for c in screen.checks if c.key == "submit")


async def test_a_page_that_breaks_the_contract_fails_with_the_reason(sandbox: DockerSandbox) -> None:
    source = (FIXTURES / "pagoord.tsx").read_text(encoding="utf-8")
    broken = (source.replace('data-field="ORDEN" ', "")  # a field lost
              .replace("if (Object.keys(missing).length) return", "")  # the validation skipped
              .replace('label="Empresa" ', 'label="" '))  # fmt: skip
    result = await run(sandbox, project({pack.screen_path(order()): broken}))
    screen = result.screen("SCR-PAGOORD")
    assert screen is not None
    problems = " ".join(screen.problems())
    assert "ORDEN: missing" in problems
    assert "EMPRESA: no accessible label" in problems
    assert "validation:" in problems
    assert not result.ok


async def test_a_page_that_does_not_type_check_does_not_compile(sandbox: DockerSandbox) -> None:
    source = (FIXTURES / "pagoord.tsx").read_text(encoding="utf-8").replace("orderNumber:", "orden:")
    result = await run(sandbox, project({pack.screen_path(order()): source}))
    assert not result.compiled
    assert any("pagoord.tsx" in e for e in result.errors), result.errors
