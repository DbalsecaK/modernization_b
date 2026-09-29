"""Independent verification (spec 6.1 phase 11, 11.3) of the fictitious application's reference target: the golden
master and 12 fresh inputs recorded on Sybase are replayed on the generated project with PostgreSQL in the Java
sandbox, the canary is caught and the source is intact, so code computes PROVEN and stores the proof pack. Without
an engine for the legacy, fresh inputs cannot be checked and the verdict is PARTLY PROVEN. Skipped without Docker
or the image nexti-sandbox-java:2."""

import asyncio
import io
import json
import subprocess
import uuid
import zipfile
from pathlib import Path

import pytest
from nexti_verification import Verdict

from nexti_adapter_sybase.ase import RecordedRunner
from nexti_core.adapters import LegacyRunner, SourceFile
from nexti_core.spec.characterization import GoldenMaster, Suite
from nexti_core.spec.model import Rule
from nexti_orchestration import PhaseSpec, RunContext
from nexti_orchestration.context import PhaseContext
from nexti_orchestration.generation import wiring
from nexti_orchestration.memory import MemoryStore
from nexti_orchestration.verification import VerificationPhases
from nexti_pack_spring_boot import IMAGE, Design, adapter_path, junit_path, service_path, skeleton
from nexti_sandbox import DockerSandbox, Sandbox

PACKAGES = Path(__file__).resolve().parents[2]
LEGACY = PACKAGES / "adapters/source/sybase/tests/fixtures/pago_orden"
PACK = PACKAGES / "packs/target/spring_boot/tests/fixtures/pago_orden"
SOURCE = [SourceFile("sp/sp_pago_orden.sp", (LEGACY / "sp_pago_orden.sp").read_text(encoding="utf-8"))]
RULES = [Rule.model_validate(r) for r in json.loads((LEGACY / "reference_spec.json").read_text("utf-8"))["rules"]]
DESIGN = Design.model_validate_json((PACK / "design.json").read_text(encoding="utf-8"))
SUITE = Suite.model_validate_json((LEGACY / "characterization.json").read_text(encoding="utf-8"))
RECORDINGS = RecordedRunner(LEGACY / "golden", "replay")


def reference_files() -> tuple[dict[str, str], dict[str, list[str]]]:
    pay = DESIGN.use_cases[0]
    files = skeleton(DESIGN)
    path, content = wiring(DESIGN)
    files[path] = content
    files[service_path(DESIGN, pay)] = (PACK / "PayOrderService.java").read_text(encoding="utf-8")
    files[junit_path(DESIGN, pay)] = (PACK / "PayOrderServiceTest.java").read_text(encoding="utf-8")
    for port in DESIGN.ports:
        reference = PACK / f"Jdbc{port.name}.java"
        if reference.exists():
            files[adapter_path(DESIGN, port)] = reference.read_text(encoding="utf-8")
    return files, {service_path(DESIGN, pay): pay.rules, junit_path(DESIGN, pay): pay.rules}


class MemoryPort:
    def __init__(self, sandbox: Sandbox, runner: LegacyRunner | None) -> None:
        self._sandbox = sandbox
        self.runner = runner
        self.saved: list[tuple[Verdict, bytes]] = []

    async def load_rules(self) -> list[Rule]:
        return RULES

    async def source_files(self) -> list[SourceFile]:
        return SOURCE

    async def load_design(self) -> Design | None:
        return DESIGN

    async def load_golden_master(self) -> GoldenMaster | None:
        return await RECORDINGS.run(SOURCE, SUITE)

    async def load_generated(self) -> tuple[dict[str, str], dict[str, list[str]]]:
        return reference_files()

    def legacy_runner(self) -> LegacyRunner | None:
        return self.runner

    def sandbox(self, image: str) -> Sandbox:
        return self._sandbox

    async def save_verdict(self, verdict: Verdict, proof_pack: bytes) -> str:
        self.saved.append((verdict, proof_pack))
        return "proof-pack.zip"


def _context() -> PhaseContext:
    phase = PhaseSpec("verification", "C4", True)
    run = RunContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pipeline", "modernization", (phase,), ("C4",),
                     "balanced", 3, (), target={"backend": "spring-boot"})  # fmt: skip
    return PhaseContext(run, MemoryStore(), phase, None)


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


async def test_the_reference_target_is_proven_by_code(java_sandbox: DockerSandbox) -> None:
    port = MemoryPort(java_sandbox, RECORDINGS)
    result = await VerificationPhases(port).verification(_context())
    assert result.summary == "PayOrder: PROVEN (6 of 6 checks passed)"
    ((verdict, pack),) = port.saved
    statuses = {c.key: (c.status, c.detail) for c in verdict.checks}
    assert statuses["tests_ran"] == ("passed", "7 test(s) passed in a clean build (JUnit XML)")
    assert statuses["same_behaviour"] == ("passed", "12 golden case(s) reproduced")
    assert statuses["fresh_inputs"] == ("passed", "12 fresh input(s) matched on both sides")
    assert statuses["canary"][0] == "passed"
    assert any("outputs:@o_movimiento (rejected)" in note for note in verdict.not_proven)
    archive = zipfile.ZipFile(io.BytesIO(pack))
    trace = {t["rule"]: t for t in json.loads(archive.read("TRACE.json"))}
    assert trace["RULE-004"]["verified"] is True
    assert trace["RULE-004"]["target_files"] == [service_path(DESIGN, DESIGN.use_cases[0]),
                                                  junit_path(DESIGN, DESIGN.use_cases[0])]  # fmt: skip


async def test_without_an_engine_for_fresh_inputs_it_is_partly_proven(java_sandbox: DockerSandbox) -> None:
    port = MemoryPort(java_sandbox, None)
    result = await VerificationPhases(port).verification(_context())
    assert result.summary == "PayOrder: PARTLY PROVEN (5 of 6 checks passed)"
    ((verdict, _),) = port.saved
    assert "Fresh inputs: there is no engine to run the legacy with fresh inputs" in verdict.not_proven
