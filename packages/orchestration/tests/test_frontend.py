"""Frontend generation (spec 8.4, ADR-0016) on the fictitious application: the frontend developer writes one page
per screen and the harness checks each in the real sandbox; a page that forgets a field goes back to the developer.
A frontend without a pack waits (D-06), `none` builds nothing, and the verdict's checks come from the sandbox run.
Next.js (ADR-0028) goes the same way, with the BFF route on a BFF architecture. The model is a stand-in that answers
with the hand-written reference pages. Skipped without the frontend image."""

import asyncio
import hashlib
import subprocess
import uuid
from pathlib import Path

import pytest

from nexti_adapter_bms import BmsAdapter
from nexti_core.adapters import SourceFile
from nexti_core.spec.screens import ScreenSpec
from nexti_orchestration import PhaseSpec, RunContext
from nexti_orchestration.context import PhaseContext
from nexti_orchestration.extraction import ModelCaller, ModelReply, ReplyError
from nexti_orchestration.frontend import code_block, flavour_of, frontend_checks, generate, options_of
from nexti_orchestration.memory import MemoryStore
from nexti_orchestration.model import PhaseUnavailableError
from nexti_orchestration.store import Usage
from nexti_pack_frontend import IMAGE, PREFIX
from nexti_pack_frontend.build import FrontendRun, ScreenCheck, ScreenRun
from nexti_pack_frontend.validation import problems
from nexti_pack_spring_boot import Design
from nexti_sandbox import DockerSandbox, Sandbox

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "packages/packs/target/frontend/tests/fixtures"
PAGES = FIXTURES / "react"
PATHS = {"react": "src/screens/{}.tsx", "nextjs": "src/app/screens/{}/screen.tsx"}
DESIGN = Design.model_validate_json(
    (ROOT / "packages/packs/target/spring_boot/tests/fixtures/pago_orden/design.json").read_text(encoding="utf-8")
)
BMS = ROOT / "packages/adapters/source/bms/tests/fixtures/pagos/PAGOSET.bms"
SCREENS = BmsAdapter().screens([SourceFile("maps/PAGOSET.bms", BMS.read_text(encoding="utf-8"))])


class Developer:
    """Answers each screen with its reference page; the first answer for PAGOORD forgets the field ORDEN."""

    def __init__(self, flavour: str = "react") -> None:
        self.flavour = flavour
        self.calls: list[tuple[str, int]] = []

    async def complete(
        self, agent: str, phase: str, messages: list[dict[str, str]], *, iteration: int = 1, judge: int = 0
    ) -> ModelReply:
        path = PATHS[self.flavour]
        module = next(m for m in ("pagomen", "pagoord", "pagores") if path.format(m) in messages[1]["content"])
        self.calls.append((module, iteration))
        page = (FIXTURES / self.flavour / f"{module}.tsx").read_text(encoding="utf-8")
        if module == "pagoord" and iteration == 1:
            page = page.replace('data-field="ORDEN" ', "")
        return ModelReply(f"```tsx\n{page}```", Usage(model="developer", input_tokens=10, output_tokens=10))


class MemoryPort:
    def __init__(self, sandbox: Sandbox, flavour: str = "react") -> None:
        self.developer = Developer(flavour)
        self.models: ModelCaller = self.developer
        self._sandbox = sandbox
        self.files: dict[str, str] = {}

    async def load_screens(self) -> list[ScreenSpec]:
        return SCREENS

    async def load_prototypes(self) -> dict[str, str]:
        return {"SCR-PAGOORD": "export default function Prototype() { return null }\n"}

    async def save_file(self, path: str, content: str) -> str:
        key = hashlib.sha256(content.encode()).hexdigest()
        self.files[key] = content
        return key

    async def load_file(self, reference: str) -> str:
        return self.files[reference]

    def sandbox(self, image: str) -> Sandbox:
        return self._sandbox


def _context(frontend: str, architecture: str = "mvc") -> tuple[PhaseContext, MemoryStore]:
    phase = PhaseSpec("generation", None, True)
    run = RunContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pipeline", "modernization", (phase,), (),
                     "balanced", 3, (), target={"frontend": frontend, "architecture": architecture})  # fmt: skip
    store = MemoryStore()
    return PhaseContext(run, store, phase, None), store


def _image() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


@pytest.fixture(scope="module")
def sandbox() -> DockerSandbox:
    box = DockerSandbox(image=IMAGE)
    if not asyncio.run(box.available()) or not _image():
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    return box


def test_the_frontend_target_picks_the_pack_or_waits() -> None:
    assert flavour_of({"frontend": "react"}) == "react"
    assert flavour_of({"frontend": "angular"}) == "angular"
    assert flavour_of({"frontend": "nextjs"}) == "nextjs"
    assert flavour_of({"frontend": "none"}) is None
    assert flavour_of({}) is None
    with pytest.raises(PhaseUnavailableError, match="vue"):
        flavour_of({"frontend": "vue"})


def test_the_nextjs_bff_follows_the_architecture() -> None:
    assert options_of({"frontend": "nextjs", "architecture": "bff-microservices"}, "nextjs") == {"bff": True}
    assert options_of({"frontend": "nextjs", "architecture": "mvc"}, "nextjs") == {"bff": False}
    assert options_of({"frontend": "react", "architecture": "bff-microservices"}, "react") == {}


def test_a_nextjs_answer_is_a_page_in_a_code_block() -> None:
    page = (FIXTURES / "nextjs" / "pagores.tsx").read_text(encoding="utf-8")
    assert code_block(f"Here it is:\n```tsx\n{page}```", "nextjs").startswith("'use client'")
    with pytest.raises(ReplyError):
        code_block("```tsx\nconst x = 1\n```", "nextjs")


def test_a_page_may_only_use_the_client_the_framework_and_the_design_system() -> None:
    good = (PAGES / "pagoord.tsx").read_text(encoding="utf-8")
    assert problems(good, "react") == []
    assert "import 'axios' is not allowed" in " ".join(problems("import axios from 'axios'\n" + good, "react"))
    assert any("typed client" in p for p in problems(good + "\nfetch('/api/x')\n", "react"))
    raw = good + "\nconst x = <div dangerouslySetInnerHTML={{ __html: '' }} />\n"
    assert any("raw HTML" in p for p in problems(raw, "react"))
    assert any("external URLs" in p for p in problems(good + "\nconst x = 'https://evil.example'\n", "react"))
    assert any("external URLs" in p for p in problems(good + "\nconst x = '//cdn.example.com/x.js'\n", "react"))
    commented = "import type { ScreenProps } from './types'\n\n// A comment after a string is not a URL\n" + good
    assert not any("external URLs" in p for p in problems(commented, "react"))


async def test_each_page_is_written_checked_and_corrected_in_the_sandbox(sandbox: DockerSandbox) -> None:
    port = MemoryPort(sandbox)
    ctx, store = _context("react")
    files, final, summary = await generate(ctx, port, DESIGN, "react")
    assert final is not None
    assert final.ok, final.diagnostic()
    assert summary == "react frontend: 3 page(s) that compile and pass the harness"
    assert f"{PREFIX}src/screens/pagoord.tsx" in files
    assert f"{PREFIX}openapi.json" in files
    assert f"{PREFIX}src/api/client.ts" in files
    assert ("pagoord", 2) in port.developer.calls  # the forgotten field went back to the developer
    assert store.kinds().count("selfCorrected") == 1
    assert {c.key: c.status for c in frontend_checks(final)} == {
        "compiles": "passed", "screens_mount": "passed", "fields_covered": "passed", "validations": "passed",
        "actions": "passed", "accessibility": "passed",
    }  # fmt: skip


async def test_each_nextjs_screen_is_written_and_checked_with_the_bff(sandbox: DockerSandbox) -> None:
    port = MemoryPort(sandbox, "nextjs")
    ctx, store = _context("nextjs", "bff-microservices")
    files, final, summary = await generate(ctx, port, DESIGN, "nextjs")
    assert final is not None
    assert final.ok, final.diagnostic()
    assert summary == "nextjs frontend: 3 page(s) that compile and pass the harness"
    assert f"{PREFIX}src/app/screens/pagoord/screen.tsx" in files
    assert f"{PREFIX}src/app/screens/pagoord/page.tsx" in files
    assert f"{PREFIX}src/app/api/[...path]/route.ts" in files
    assert ("pagoord", 2) in port.developer.calls
    assert store.kinds().count("selfCorrected") == 1


def test_the_verdict_checks_follow_the_sandbox_run() -> None:
    broken = FrontendRun("react", True, True, [], [
        ScreenRun("SCR-A", [ScreenCheck("mounts", "passed", "ok"), ScreenCheck("fields", "failed", "ORDEN: missing"),
                            ScreenCheck("validation", "not_checked", "no required input field")]),
    ])  # fmt: skip
    found = {c.key: (c.status, c.detail) for c in frontend_checks(broken)}
    assert found["fields_covered"] == ("failed", "SCR-A: ORDEN: missing")
    assert found["validations"][0] == "not_checked"
    assert found["compiles"][0] == "passed"
    failed = frontend_checks(FrontendRun("react", False, False, ["x.tsx(1,1): error TS1"], []))
    assert [(c.key, c.status) for c in failed] == [("compiles", "failed")]
