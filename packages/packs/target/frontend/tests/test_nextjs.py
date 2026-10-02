"""The Next.js pack (ADR-0028): the App Router skeleton for the fictitious BMS application (one route folder per
screen, the typed client, the optional BFF) and, in the real sandbox, the hand-written reference screens type-check
with Next's types, bundle and pass the platform's harness and axe exactly like React; a screen that breaks the
contract or does not type-check fails with the reason. The sandbox tests are skipped without Docker or the image
nexti-sandbox-frontend:2."""

import json
from pathlib import Path

from nexti_adapter_bms import BmsAdapter
from nexti_core.adapters import SourceFile
from nexti_pack_frontend import ScreenContract, contract_of, openapi
from nexti_pack_frontend import nextjs as pack
from nexti_pack_frontend.build import FrontendRun, build_and_test
from nexti_pack_frontend.validation import problems
from nexti_pack_spring_boot import Design
from nexti_sandbox import DockerSandbox

ROOT = Path(__file__).resolve().parents[5]
DESIGN = Design.model_validate_json(
    (ROOT / "packages/packs/target/spring_boot/tests/fixtures/pago_orden/design.json").read_text(encoding="utf-8")
)
BMS = ROOT / "packages/adapters/source/bms/tests/fixtures/pagos/PAGOSET.bms"
CONTRACTS = [contract_of(s) for s in BmsAdapter().screens([SourceFile("maps/PAGOSET.bms", BMS.read_text("utf-8"))])]
FIXTURES = Path(__file__).parent / "fixtures" / "nextjs"
BFF = "src/app/api/[...path]/route.ts"


def order() -> ScreenContract:
    return next(c for c in CONTRACTS if c.id == "SCR-PAGOORD")


def project(pages: dict[str, str] | None = None, *, bff: bool = False) -> dict[str, str]:
    files = pack.skeleton(openapi(DESIGN), CONTRACTS, "Pagos", bff=bff)
    for contract in CONTRACTS:
        files[pack.screen_path(contract)] = (FIXTURES / f"{contract.module}.tsx").read_text(encoding="utf-8")
    files.update(pages or {})
    return files


async def run(sandbox: DockerSandbox, files: dict[str, str]) -> FrontendRun:
    return await build_and_test(sandbox, "nextjs", files, CONTRACTS)


def test_the_skeleton_is_an_app_router_project_with_a_route_per_screen() -> None:
    files = pack.skeleton(openapi(DESIGN), CONTRACTS, "Pagos")
    for path in ("src/app/layout.tsx", "src/app/page.tsx", "src/app/screens/index.ts", "src/app/screens/types.ts",
                 "src/app/screens/routes.ts", "src/harness.tsx", "src/api/client.ts", "next-env.d.ts",
                 "openapi.json"):  # fmt: skip
        assert path in files, path
    for contract in CONTRACTS:
        route = files[f"src/app/screens/{contract.module}/page.tsx"]
        assert route.startswith("'use client'")
        assert "useScreenProps()" in route
        assert pack.screen_path(contract) not in files  # the screens are the agent's
        assert f"import {contract.component} from './{contract.module}/screen'" in files["src/app/screens/index.ts"]
        assert f'"{contract.id}": "/screens/{contract.module}"' in files["src/app/screens/routes.ts"]
    assert 'export const START = "SCR-PAGOMEN"' in files["src/app/screens/routes.ts"]
    manifest = json.loads(files["package.json"])
    assert manifest["dependencies"]["next"] == pack.VERSIONS["next"]
    assert manifest["scripts"]["build"] == "next build"
    tsconfig = json.loads(files["tsconfig.json"])
    assert tsconfig["compilerOptions"]["paths"]["@/*"] == ["./src/*"]
    assert "{{" not in "".join(files.values())
    assert BFF not in files


def test_the_bff_only_forwards_to_the_backend_from_the_environment() -> None:
    route = project(bff=True)[BFF]
    assert "process.env.NEXTI_BACKEND_URL" in route
    assert "export { forward as DELETE, forward as GET, forward as PATCH, forward as POST, forward as PUT }" in route
    assert "http://" not in route
    assert "https://" not in route


def test_a_screen_is_a_client_component_without_next_apis() -> None:
    good = (FIXTURES / "pagoord.tsx").read_text(encoding="utf-8")
    assert problems(good, "nextjs") == []
    assert any("'use client'" in p for p in problems(good.removeprefix("'use client'\n"), "nextjs"))
    commented = "// A screen\n" + good
    assert problems(commented, "nextjs") == []
    router = good.replace(
        "import type { ScreenProps }", "import { useRouter } from 'next/navigation'\nimport type { ScreenProps }"
    )
    assert "import 'next/navigation' is not allowed" in " ".join(problems(router, "nextjs"))
    assert any("typed client" in p for p in problems(good + "\nfetch('/api/x')\n", "nextjs"))


async def test_the_reference_screens_compile_and_pass_the_harness(sandbox: DockerSandbox) -> None:
    result = await run(sandbox, project())
    assert result.ok, result.diagnostic()
    screen = result.screen("SCR-PAGOORD")
    assert screen is not None
    checks = {c.key: c.status for c in screen.checks}
    assert checks == {"mounts": "passed", "fields": "passed", "actions": "passed", "validation": "passed",
                      "accessibility": "passed", "submit": "passed"}  # fmt: skip
    assert "payOrder" in next(c.detail for c in screen.checks if c.key == "submit")
    menu = result.screen("SCR-PAGOMEN")
    assert menu is not None
    assert menu.ok


async def test_the_project_with_the_bff_compiles_and_passes(sandbox: DockerSandbox) -> None:
    result = await run(sandbox, project(bff=True))
    assert result.ok, result.diagnostic()


async def test_a_screen_that_breaks_the_contract_fails_with_the_reason(sandbox: DockerSandbox) -> None:
    source = (FIXTURES / "pagoord.tsx").read_text(encoding="utf-8")
    broken = (source.replace('data-field="ORDEN" ', "")
              .replace("if (Object.keys(missing).length) return", "")
              .replace('label="Empresa" ', 'label="" '))  # fmt: skip
    result = await run(sandbox, project({pack.screen_path(order()): broken}))
    screen = result.screen("SCR-PAGOORD")
    assert screen is not None
    found = " ".join(screen.problems())
    assert "ORDEN: missing" in found
    assert "EMPRESA: no accessible label" in found
    assert "validation:" in found
    assert not result.ok


async def test_a_screen_that_does_not_type_check_does_not_compile(sandbox: DockerSandbox) -> None:
    source = (FIXTURES / "pagoord.tsx").read_text(encoding="utf-8").replace("orderNumber:", "orden:")
    result = await run(sandbox, project({pack.screen_path(order()): source}))
    assert not result.compiled
    assert any("pagoord/screen.tsx" in e for e in result.errors), result.errors
