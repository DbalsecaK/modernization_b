"""The infrastructure of the target (spec 8.4, ADR-0021): after the code, the deployment pack writes the OpenTofu of
the target's cloud from the approved design (code, no model), and verification gives it its own verdict
(`iac-<cloud>`): `tofu validate` in the sandbox without credentials and the fitness functions of the pack. A target
without a cloud, or with a cloud that has no generator yet, gets no IaC."""

import io
import json
import zipfile
from collections.abc import Mapping
from typing import Any, Protocol

import nexti_pack_iac
from nexti_core.spec.design import Design
from nexti_orchestration.context import PhaseContext
from nexti_sandbox import Sandbox
from nexti_verification import Verdict
from nexti_verification.proof_pack import verification_document


class InfrastructurePort(Protocol):
    def sandbox(self, image: str) -> Sandbox: ...

    async def load_design(self) -> Design | None: ...

    async def load_infrastructure(self) -> dict[str, str]:
        """The newest generated IaC files, paths under infra/<cloud>/."""
        ...

    async def save_verdict(self, verdict: Verdict, proof_pack: bytes) -> str: ...


def generate(design: Design, target: Mapping[str, Any]) -> tuple[dict[str, str], str]:
    """The IaC files of the target and a summary; nothing when the target has no cloud with a generator."""
    files = nexti_pack_iac.generate(design, target)
    if not files:
        return {}, ""
    cloud = str(target.get("cloud")).lower()
    return files, f"OpenTofu for {cloud.upper()}: {sum(1 for p in files if p.endswith('.tf'))} file(s)"


def proof_pack(verdict: Verdict, files: Mapping[str, str]) -> bytes:
    """The IaC verdict and the files it judged."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("VERIFICATION.json", json.dumps(verification_document(verdict), indent=2))
        for path, content in sorted(files.items()):
            archive.writestr(path, content)
    return buffer.getvalue()


async def verify(ctx: PhaseContext, port: Any) -> str:
    """The IaC's own verdict, from the stored files; empty when the port or the project has no IaC."""
    if not hasattr(port, "load_infrastructure"):
        return ""
    files = await port.load_infrastructure()
    clouds = sorted({p.split("/", 2)[1] for p in files if p.count("/") >= 2})
    if not clouds:
        return ""
    found = []
    for cloud in clouds:
        mine = {p: c for p, c in files.items() if p.startswith(f"{nexti_pack_iac.PREFIX}{cloud}/")}
        await ctx.store.event("started", "running", f"The {cloud.upper()} IaC: tofu validate and fitness functions",
                              phase=ctx.phase.key)  # fmt: skip
        verdict = await nexti_pack_iac.verdict(port.sandbox(nexti_pack_iac.IMAGE), mine, cloud)
        await port.save_verdict(verdict, proof_pack(verdict, mine))
        passed = sum(1 for c in verdict.checks if c.status == "passed")
        found.append(f"{verdict.module}: {verdict.verdict} ({passed} of {len(verdict.checks)} checks passed)")
    return "; ".join(found)
