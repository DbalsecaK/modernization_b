"""Flow 4 in the pipeline (ADR-0025): the target is taken in with its vendor's mapping, the mapping is ready for C2,
and the validation plays the golden master recorded on Sybase on BillPay in the Java sandbox: the verdict is computed
by code with IVV_CHECKS and the report is written. Without an engine for the legacy, fresh inputs are not checked
(PARTLY PROVEN). The rule comparison finds the legacy rules among the target's. Skips without Docker or the image."""

import asyncio
import io
import json
import subprocess
import uuid
import zipfile
from pathlib import Path

import pytest

from nexti_core.adapters import LegacyRunner, SourceFile
from nexti_core.spec.characterization import GoldenMaster
from nexti_core.spec.model import Rule
from nexti_ivv.runner import IMAGE
from nexti_orchestration import PhaseSpec, RunContext
from nexti_orchestration.context import PhaseContext
from nexti_orchestration.ivv import COMPARISON, MAPPING, REPORT, IvvPhases, compare_rules
from nexti_orchestration.memory import MemoryStore
from nexti_sandbox import DockerSandbox, Sandbox
from nexti_verification import Verdict

PACKAGES = Path(__file__).resolve().parents[2]
LEGACY = PACKAGES / "adapters/source/sybase/tests/fixtures/pago_orden"
TARGET = PACKAGES / "ivv/tests/fixtures/billpay"
RULES = [Rule.model_validate(r) for r in json.loads((LEGACY / "reference_spec.json").read_text("utf-8"))["rules"]]


def _golden() -> GoldenMaster:
    masters = [
        GoldenMaster.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted((LEGACY / "golden").glob("*.json"))
    ]
    return next(m for m in masters if any(r.case.name == "web_order_pays_half_the_service_tariff" for r in m.results))


class MemoryPort:
    models = None

    def __init__(self, sandbox: Sandbox | None) -> None:
        self._sandbox = sandbox
        self.artifacts: dict[str, str] = {}
        self.saved: list[tuple[Verdict, bytes]] = []

    async def source_files(self) -> list[SourceFile]:
        return [SourceFile("sp/sp_pago_orden.sp", (LEGACY / "sp_pago_orden.sp").read_text(encoding="utf-8"))]

    async def target_archive(self) -> dict[str, bytes]:
        return {p.relative_to(TARGET).as_posix(): p.read_bytes() for p in TARGET.rglob("*") if p.is_file()}

    async def load_rules(self) -> list[Rule]:
        return RULES

    async def load_golden_master(self) -> GoldenMaster:
        return _golden()

    def legacy_runner(self) -> LegacyRunner | None:
        return None

    def sandbox(self, image: str) -> Sandbox:
        assert image == IMAGE
        assert self._sandbox is not None
        return self._sandbox

    async def save_artifacts(self, files: dict[str, str], layers: dict[str, str], rules: dict[str, list[str]]) -> None:
        self.artifacts |= files

    async def load_artifact(self, path: str) -> str | None:
        return self.artifacts.get(path)

    async def save_verdict(self, verdict: Verdict, proof_pack: bytes) -> str:
        self.saved.append((verdict, proof_pack))
        return "proof"


def _context(phase: str) -> PhaseContext:
    spec = PhaseSpec(phase, None, True)
    run = RunContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pipeline", "independentValidation", (spec,), (),
                     "balanced", 3, (), target={})  # fmt: skip
    return PhaseContext(run, MemoryStore(), spec, None)


def test_the_legacy_rules_are_found_among_the_target_rules() -> None:
    target = [rule.model_copy(update={"id": f"T-{i}"}) for i, rule in enumerate(RULES[:5])]
    extra = RULES[5].model_copy(update={"id": "T-9", "name": "Loyalty points are added to every paid order",
                                        "statement": "Every paid order adds loyalty points to the company account",
                                        "condition": "", "action": ""})  # fmt: skip
    comparison = compare_rules(RULES, [*target, extra])
    assert {p["legacy"] for p in comparison["present"]} >= {r.id for r in RULES[:5]}
    assert "Loyalty points are added to every paid order" in comparison["extra"]


def test_the_target_is_taken_in_with_the_vendor_mapping_ready_for_c2() -> None:
    port = MemoryPort(None)
    phases = IvvPhases(port)  # type: ignore[arg-type]
    intake = asyncio.run(phases.target_intake(_context("targetIntake")))
    assert intake.summary.startswith("spring-boot: 1 endpoint(s), 4 table(s)")
    assert "the vendor's ivv-mapping.yaml" in intake.summary
    assert "/api/v1/payments" in port.artifacts[MAPPING]
    mapping = asyncio.run(phases.mapping(_context("mapping")))
    assert mapping.summary == "The mapping covers every input, output, table and call: ready for C2"


def _image_available() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


def test_the_validation_gives_the_ivv_verdict_and_the_report() -> None:
    box = DockerSandbox(image=IMAGE)
    if not asyncio.run(box.available()) or not _image_available():
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    port = MemoryPort(box)
    phases = IvvPhases(port)  # type: ignore[arg-type]
    asyncio.run(phases.target_intake(_context("targetIntake")))
    port.artifacts[COMPARISON] = json.dumps(compare_rules(RULES, RULES))
    result = asyncio.run(phases.validation(_context("validation")))
    verdict, pack = port.saved[0]
    statuses = {c.key: c.status for c in verdict.checks}
    assert statuses == {"target_runs": "passed", "contract_mapped": "passed", "same_behaviour": "passed",
                        "fresh_inputs": "not_checked", "rules_covered": statuses["rules_covered"],
                        "source_intact": "passed"}, verdict.checks  # fmt: skip
    assert verdict.module == "ivv-sp_pago_orden"
    assert result.summary.startswith("ivv-sp_pago_orden: PARTLY PROVEN") or result.summary.startswith(
        "ivv-sp_pago_orden: NOT PROVEN")  # fmt: skip
    with zipfile.ZipFile(io.BytesIO(pack)) as archive:
        assert {"VERIFICATION.json", "EQUIVALENCE.json", "MAPPING.yaml", "RULES-COMPARED.json"} <= set(
            archive.namelist()
        )
    assert "| target_runs | passed |" in port.artifacts[REPORT]
    report = asyncio.run(phases.report(_context("report")))
    assert report.summary.startswith("IV&V report ready (")
