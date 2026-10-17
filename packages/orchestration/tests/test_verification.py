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
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

import pytest

from nexti_adapter_sybase.ase import RecordedRunner
from nexti_core.adapters import LegacyRunner, SourceFile
from nexti_core.spec.characterization import GoldenMaster, Suite
from nexti_core.spec.model import Rule
from nexti_core.spec.screens import ScreenSpec
from nexti_orchestration import PhaseSpec, RunContext
from nexti_orchestration.context import PhaseContext
from nexti_orchestration.generation import wiring
from nexti_orchestration.memory import MemoryStore
from nexti_orchestration.verification import VerificationPhases
from nexti_pack_spring_boot import IMAGE, Design, adapter_path, junit_path, service_path, skeleton
from nexti_sandbox import DockerSandbox, Sandbox
from nexti_verification import Verdict

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

    async def load_frontend(self) -> dict[str, str]:
        return {}

    async def load_screens(self) -> list[ScreenSpec]:
        return []

    def legacy_runner(self) -> LegacyRunner | None:
        return self.runner

    def sandbox(self, image: str) -> Sandbox:
        return self._sandbox

    async def save_verdict(self, verdict: Verdict, proof_pack: bytes) -> str:
        self.saved.append((verdict, proof_pack))
        return "proof-pack.zip"


def _context(accept_gaps: bool = False) -> PhaseContext:
    phase = PhaseSpec("verification", "C4", True)
    run = RunContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pipeline", "modernization", (phase,), ("C4",),
                     "balanced", 3, (), target={"backend": "spring-boot"})  # fmt: skip
    ctx = PhaseContext(run, MemoryStore(), phase, None)
    if accept_gaps:
        # ADR-0050: the recording carries the coverage and quirks the real engine measured; their gaps (branches
        # without a case, a quirk no case reaches) need a signed decision before any work. Accepted, as a person would.
        ctx.answers[str(ctx.question_id("legacy-gaps"))] = {"option": "accept", "by": "Carlos Ruiz", "text": ""}
    return ctx


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
    result = await VerificationPhases(port).verification(_context(accept_gaps=True))
    # ADR-0055: the six checks pass, but the golden master replaced sp_debito by a stub and never compared the final
    # state of the database, so the seventh check cannot pass and the verdict says so instead of claiming PROVEN.
    assert result.summary == "PayOrder: PARTLY PROVEN (6 of 8 checks passed)"
    ((verdict, pack),) = port.saved
    statuses = {c.key: (c.status, c.detail) for c in verdict.checks}
    assert statuses["behaviour_boundary"][0] == "not_checked"
    # ADR-0050: the recording's coverage leaves gaps a person accepted as not proven (the eighth check).
    assert statuses["legacy_covered"][0] == "not_checked"
    assert "accepted as not proven by Carlos Ruiz" in statuses["legacy_covered"][1]
    assert "db_cuentas..sp_debito" in statuses["behaviour_boundary"][1]
    assert "unit of work" in statuses["behaviour_boundary"][1]
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
    result = await VerificationPhases(port).verification(_context(accept_gaps=True))
    assert result.summary == "PayOrder: PARTLY PROVEN (5 of 8 checks passed)"
    ((verdict, _),) = port.saved
    assert "Fresh inputs: there is no engine to run the legacy with fresh inputs" in verdict.not_proven


async def test_a_golden_master_from_traces_cannot_observe_fresh_inputs() -> None:
    """ADR-0015: with recorded CICS traces the legacy does not run, so fresh inputs stay not checked (PARTLY PROVEN
    at most); nothing is run to find it out."""
    from nexti_core.spec.characterization import TRACE_ENGINE, GoldenMaster, Schema

    master = GoldenMaster(program="PAGOORD", source_sha256="0" * 64, engine=TRACE_ENGINE, schema_=Schema(), results=[])
    phases = VerificationPhases(None)  # type: ignore[arg-type]
    fresh, reason = await phases._fresh(None, None, [], master, None, None, {}, None, {})  # type: ignore[arg-type]
    assert fresh is None
    assert "recorded traces" in reason


async def test_the_gaps_of_the_legacy_are_asked_before_any_work() -> None:
    # ADR-0050: a branch no case entered needs a signed decision; it is asked first, so waiting repeats no work.
    from nexti_core.spec.characterization import Coverage, CoveredBranch, Schema
    from nexti_orchestration.context import NeedsAnswer

    branch = CoveredBranch(id="b1", kind="else", line_start=40, line_end=44)
    master = GoldenMaster(program="db..sp_p", source_sha256="0" * 64, engine="sybase-ase-16.0", schema_=Schema(),
                          results=[], coverage=Coverage(branches=[branch]))  # fmt: skip

    class OnlyMaster:
        async def load_golden_master(self) -> GoldenMaster:
            return master

        async def load_design(self) -> None:
            raise AssertionError("no work before the decision")

    with pytest.raises(NeedsAnswer) as waiting:
        await VerificationPhases(OnlyMaster()).verification(_context())  # type: ignore[arg-type]
    ((_, question),) = waiting.value.questions
    assert question.key == "legacy-gaps"
    assert "- branch 40-44 (else)" in question.context
    assert question.recommended.key == "accept"
    assert [o.key for o in question.alternatives] == ["unreachable"]


def test_the_target_runs_against_the_legacys_engine_only_when_the_data_stays_there() -> None:
    # ADR-0055 (point 10): with `migration` (or no Sybase legacy) there is no engine; the verdict's boundary says
    # the state was not compared.
    from nexti_orchestration.verification import same_engine

    design = Design.model_validate_json(
        (PACKAGES / "packs/target/spring_boot/tests/fixtures/pago_orden/design.json").read_text(encoding="utf-8")
    )
    master = asyncio.run(RECORDINGS.run(SOURCE, SUITE))
    assert design.data_strategy == "migration"
    assert asyncio.run(_enter(same_engine(design, SOURCE, master))) is None
    same = design.model_copy(update={"data_strategy": "same_database"})
    from nexti_adapter_sybase.ase import SameEngine

    assert isinstance(same_engine(same, SOURCE, master), SameEngine)
    assert asyncio.run(_enter(same_engine(same, [SourceFile("x.cbl", "IDENTIFICATION DIVISION.")], master))) is None


async def _enter(context: AbstractAsyncContextManager[Any]) -> object:
    async with context as engine:
        return engine
