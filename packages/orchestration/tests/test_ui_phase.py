"""The UI phase (spec 6.1 phase 7, 7.4) on the fictitious BMS application: the maps become screen specs, the design
system starts at the NexTI base, and each screen gets a prototype that compiles in the web sandbox and shows every
field of its spec; a prototype that forgets a field goes back to the designer. Skipped without Docker or the image
nexti-sandbox-web:1."""

import asyncio
import hashlib
import subprocess
import uuid
from collections.abc import Sequence
from pathlib import Path

import pytest

from nexti_core.adapters import SourceFile
from nexti_core.spec.screens import ScreenSpec
from nexti_orchestration import PhaseSpec, RunContext
from nexti_orchestration.context import PhaseContext
from nexti_orchestration.extraction import ModelCaller, ModelReply
from nexti_orchestration.memory import MemoryStore
from nexti_orchestration.store import Usage
from nexti_orchestration.ui import UiPhases, missing_fields, screens_of, tsx_block
from nexti_sandbox import DockerSandbox, Sandbox
from nexti_ui import IMAGE, PrototypeBuild

BMS = Path(__file__).resolve().parents[2] / "adapters/source/bms/tests/fixtures/pagos/PAGOSET.bms"
SOURCE = [SourceFile("maps/PAGOSET.bms", BMS.read_text(encoding="utf-8"))]


def prototype_of(screen: ScreenSpec, skip: str | None = None) -> str:
    fields = [f for f in screen.fields if f.kind != "literal" and f.name != skip]
    items = "\n".join(
        f'        <div data-field="{f.name}"><TextField label="{f.name.title()}" '
        f'{"required " if f.required else ""}{"readOnly " if f.kind == "output" else ""}'
        f'maxLength={{{max(f.length, 1)}}} defaultValue="" /></div>'
        for f in fields
    )  # fmt: skip
    keys = ", ".join(f"{{ key: '{a.key}', label: '{a.label.title()}' }}" for a in screen.actions)
    return f"""```tsx
import {{ Screen, Card, Grid, TextField, KeyBar }} from '@nexti/ds'

export default function Prototype({{ navigate }}: {{ navigate: (to: string) => void }}) {{
  return (
    <Screen title="{screen.name.title()}" code="{screen.map}" keys={{<KeyBar actions={{[{keys}]}} />}}>
      <Card title="Datos">
        <Grid>
{items}
        </Grid>
      </Card>
      <button type="button" onClick={{() => navigate('SCR-PAGOMEN')}}>Menu</button>
    </Screen>
  )
}}
```"""


class Designer:
    """Answers each screen from its spec; the first answer for PAGOORD forgets the field VALOR."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def complete(
        self, agent: str, phase: str, messages: list[dict[str, str]], *, iteration: int = 1, judge: int = 0
    ) -> ModelReply:
        screen = next(s for s in screens_of(SOURCE) if f'"id": "{s.id}"' in messages[1]["content"])
        self.calls.append((screen.id, iteration))
        skip = "VALOR" if screen.id == "SCR-PAGOORD" and iteration == 1 else None
        return ModelReply(prototype_of(screen, skip), Usage(model="designer", input_tokens=10, output_tokens=10))


class MemoryUiPort:
    def __init__(self, sandbox: Sandbox | None) -> None:
        self.designer = Designer()
        self.models: ModelCaller = self.designer
        self._sandbox = sandbox
        self.screens: list[ScreenSpec] = []
        self.files: dict[str, str] = {}
        self.prototypes: dict[str, list[PrototypeBuild]] = {}
        self.design_system = 0

    async def source_files(self) -> list[SourceFile]:
        return SOURCE

    async def save_screens(self, screens: Sequence[ScreenSpec]) -> None:
        self.screens = list(screens)

    async def ensure_design_system(self) -> int:
        self.design_system = self.design_system or 1
        return self.design_system

    async def save_file(self, path: str, content: str) -> str:
        key = hashlib.sha256(content.encode()).hexdigest()
        self.files[key] = content
        return key

    async def load_file(self, reference: str) -> str:
        return self.files[reference]

    async def save_prototype(self, screen: str, source: str, built: PrototypeBuild, origin: str, notes: str) -> int:
        self.prototypes.setdefault(screen, []).append(built)
        return len(self.prototypes[screen])

    def sandbox(self, image: str) -> Sandbox:
        assert self._sandbox is not None
        return self._sandbox


def _context() -> tuple[PhaseContext, MemoryStore]:
    phase = PhaseSpec("ui", "C2", True)
    run = RunContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pipeline", "modernization", (phase,), ("C2",),
                     "balanced", 3, (), target={"frontend": "react"})  # fmt: skip
    store = MemoryStore()
    return PhaseContext(run, store, phase, None), store


def test_the_legacy_maps_are_the_screens_and_every_field_must_be_shown() -> None:
    screens = screens_of(SOURCE)
    assert [s.id for s in screens] == ["SCR-PAGOMEN", "SCR-PAGOORD", "SCR-PAGORES"]
    order = screens[1]
    code = tsx_block(prototype_of(order, skip="VALOR"))
    assert missing_fields(order, code) == ["VALOR"]
    assert missing_fields(order, tsx_block(prototype_of(order))) == []
    assert screens_of([SourceFile("sp/x.sp", "create procedure x as return 0")]) == []


def _image_available() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


@pytest.fixture(scope="module")
def web_sandbox() -> DockerSandbox:
    box = DockerSandbox(image=IMAGE)
    if not asyncio.run(box.available()) or not _image_available():
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    return box


async def test_each_screen_gets_a_prototype_that_compiles_and_shows_every_field(web_sandbox: DockerSandbox) -> None:
    port = MemoryUiPort(web_sandbox)
    ctx, store = _context()
    result = await UiPhases(port).ui(ctx)
    assert result.summary == "3 screen(s) with 16 fields; a prototype per screen with the design system v1"
    assert [s.id for s in port.screens] == ["SCR-PAGOMEN", "SCR-PAGOORD", "SCR-PAGORES"]
    assert {k: len(v) for k, v in port.prototypes.items()} == {"SCR-PAGOMEN": 1, "SCR-PAGOORD": 1, "SCR-PAGORES": 1}
    assert all(b.ok and ".nx-screen" in b.css for builds in port.prototypes.values() for b in builds)
    # PAGOORD forgot VALOR the first time: the missing field went back to the designer.
    assert ("SCR-PAGOORD", 2) in port.designer.calls
    assert store.kinds().count("selfCorrected") == 1


async def test_sources_without_screens_have_nothing_to_design() -> None:
    port = MemoryUiPort(None)
    port.source_files = lambda: _no_screens()  # type: ignore[method-assign]
    ctx, _ = _context()
    assert (await UiPhases(port).ui(ctx)).summary == "The sources have no screens: nothing to design"


async def _no_screens() -> list[SourceFile]:
    return [SourceFile("sp/x.sp", "create procedure x as return 0")]
