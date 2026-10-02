"""The infrastructure of the target (ADR-0021) in the pipeline: generation writes the IaC of the target's cloud and
nothing for a target without one; verification gives each cloud its own verdict from the stored files, with the
proof pack carrying the files it judged. The sandbox is simulated here; the real `tofu validate` runs in the tests of
the deployment pack."""

import asyncio
import io
import json
import uuid
import zipfile
from collections.abc import Mapping
from pathlib import Path

from nexti_core.spec.design import Design
from nexti_orchestration import PhaseSpec, RunContext, infrastructure
from nexti_orchestration.context import PhaseContext
from nexti_orchestration.memory import MemoryStore
from nexti_sandbox import Limits, SandboxResult
from nexti_verification import Verdict

PACK = Path(__file__).resolve().parents[2] / "packs/target/spring_boot/tests/fixtures/pago_orden"
DESIGN = Design.model_validate_json((PACK / "design.json").read_text(encoding="utf-8"))
TARGET = {"backend": "spring-boot", "database": "oracle", "cloud": "aws"}


class ValidSandbox:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    async def run(self, command: list[str], files: Mapping[str, bytes] | None = None,
                  limits: Limits | None = None) -> SandboxResult:  # fmt: skip
        self.inputs = sorted(files or {})
        report = {"valid": True, "warning_count": 0, "diagnostics": []}
        return SandboxResult(0, "===VALIDATE===\n" + json.dumps(report), "", False, 10)


class MemoryPort:
    def __init__(self, files: dict[str, str]) -> None:
        self.files = files
        self.box = ValidSandbox()
        self.saved: list[tuple[Verdict, bytes]] = []

    def sandbox(self, image: str) -> ValidSandbox:
        assert image == "nexti-sandbox-iac:2"
        return self.box

    async def load_infrastructure(self) -> dict[str, str]:
        return self.files

    async def save_verdict(self, verdict: Verdict, proof_pack: bytes) -> str:
        self.saved.append((verdict, proof_pack))
        return "proof"


def _context() -> PhaseContext:
    phase = PhaseSpec("verification", None, True)
    run = RunContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pipeline", "modernization", (phase,), (),
                     "balanced", 3, (), target=TARGET)  # fmt: skip
    return PhaseContext(run, MemoryStore(), phase, None)


def test_generation_writes_the_iac_of_the_cloud_and_nothing_without_one() -> None:
    files, summary = infrastructure.generate(DESIGN, TARGET)
    assert set(files) == {"infra/aws/main.tf", "infra/aws/variables.tf", "infra/aws/outputs.tf", "infra/aws/README.md"}
    assert summary == "OpenTofu for AWS: 3 file(s)"
    assert infrastructure.generate(DESIGN, {"backend": "spring-boot"}) == ({}, "")
    gcp, summary = infrastructure.generate(DESIGN, {"database": "mysql", "cloud": "gcp", "architecture": "serverless"})
    assert "infra/gcp/main.tf" in gcp
    assert summary == "OpenTofu for GCP: 3 file(s)"
    assert infrastructure.generate(DESIGN, {"database": "oracle", "cloud": "gcp"}) == (
        {}, "No IaC: the oracle database is not supported on GCP by the deployment pack")  # fmt: skip


def test_verification_gives_the_iac_its_own_verdict() -> None:
    files, _ = infrastructure.generate(DESIGN, TARGET)
    port = MemoryPort(files)
    summary = asyncio.run(infrastructure.verify(_context(), port))
    assert summary == "iac-aws: PROVEN (6 of 6 checks passed)"
    assert port.box.inputs == ["infra/main.tf", "infra/outputs.tf", "infra/variables.tf"]
    verdict, pack = port.saved[0]
    assert verdict.module == "iac-aws"
    with zipfile.ZipFile(io.BytesIO(pack)) as archive:
        assert {"VERIFICATION.json", "infra/aws/main.tf", "infra/aws/README.md"} <= set(archive.namelist())


def test_a_project_without_iac_has_no_iac_verdict() -> None:
    port = MemoryPort({})
    assert asyncio.run(infrastructure.verify(_context(), port)) == ""
    assert port.saved == []
