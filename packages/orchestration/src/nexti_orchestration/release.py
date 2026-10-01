"""Hardening and delivery (spec 6.1 phases 12 and 13, 7.2, ADR-0023). No model takes part:

- hardening computes the report of the generated project (secrets, dependencies, insecure patterns, slow tests) and
  keeps it with the generated files; it informs, it does not stop the run (C4 already has a person's sign-off);
- delivery puts together the release (the code, the strangler fig cutover plan and the hardening report) and pushes
  it to a new branch of the customer's repository when the project has one and the person who started the run may
  push code (`code.push`); otherwise the release is the ZIP of the Code tab. Every delivery leaves a release row.
"""

import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

import nexti_delivery
import nexti_hardening
from nexti_core.spec.design import Design
from nexti_ingest.git import ensure_public_host
from nexti_orchestration.context import PhaseContext
from nexti_orchestration.model import PhaseFailedError, PhaseResult
from nexti_sandbox import Sandbox


@dataclass(frozen=True)
class Repository:
    url: str
    branch: str
    token: str | None


@dataclass(frozen=True)
class ReleaseRecord:
    kind: str  # push | zip
    status: str  # pushed | failed | ready
    files: int
    findings: dict[str, int]
    repository_url: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    base_sha: str | None = None
    error: str | None = None


class ReleasePort(Protocol):
    async def load_design(self) -> Design | None: ...

    async def load_generated(self) -> tuple[dict[str, str], dict[str, list[str]]]: ...

    async def save_artifacts(
        self, files: dict[str, str], layers: dict[str, str], rules: dict[str, list[str]]
    ) -> None: ...

    def sandbox(self, image: str) -> Sandbox: ...

    async def load_test_report(self) -> str | None:
        """The JUnit XML of the clean build of the run's verification, if any."""
        ...

    async def repository(self) -> Repository | None:
        """The customer's repository of the project, with its token, when one is linked."""
        ...

    async def may_push(self) -> bool:
        """Whether the person who started the run holds `code.push` in this project."""
        ...

    async def save_release(self, release: ReleaseRecord) -> None: ...

    def delivery_services(self) -> tuple[httpx.AsyncClient | None, str | None, bool]:
        """The HTTP client, the OSV URL (None: turned off) and whether private hosts are allowed (local only)."""
        ...


async def _release_files(port: Any) -> dict[str, str]:
    """Everything the release carries: the backend and docs, the frontend and the infrastructure."""
    generated, _ = await port.load_generated()
    files: dict[str, str] = dict(generated)
    if hasattr(port, "load_frontend"):
        files |= {f"frontend/{path}": content for path, content in (await port.load_frontend()).items()}
    if hasattr(port, "load_infrastructure"):
        files |= await port.load_infrastructure()
    return files


class ReleasePhases:
    def __init__(self, port: ReleasePort) -> None:
        self.port = port

    async def hardening(self, ctx: PhaseContext) -> PhaseResult:
        files = await _release_files(self.port)
        if not files:
            raise PhaseFailedError("There is no generated code to harden")
        http, osv_url, _ = self.port.delivery_services()
        await ctx.store.event("started", "running", "Secrets, dependencies, insecure patterns and test times",
                              phase=ctx.phase.key)  # fmt: skip
        report = await nexti_hardening.harden(
            files, sandbox=self.port.sandbox(nexti_hardening.IMAGE), http=http,
            junit_xml=await self.port.load_test_report(), osv_url=osv_url,
        )  # fmt: skip
        await self.port.save_artifacts(
            {nexti_hardening.REPORT_JSON: json.dumps(report.to_dict(), indent=2),
             nexti_hardening.REPORT_MD: report.to_markdown()},
            {nexti_hardening.REPORT_JSON: "docs", nexti_hardening.REPORT_MD: "docs"}, {},
        )  # fmt: skip
        if report.critical:
            await ctx.store.event("info", "running", f"{report.critical} critical or high finding(s): see the report",
                                  phase=ctx.phase.key)  # fmt: skip
        return PhaseResult(summary=report.summary())

    async def delivery(self, ctx: PhaseContext) -> PhaseResult:
        design = await self.port.load_design()
        if design is None:
            raise PhaseFailedError("There is no approved design to deliver")
        plan = nexti_delivery.plan(design)
        await self.port.save_artifacts(plan, dict.fromkeys(plan, "docs"), {})
        files = await _release_files(self.port)
        if not files:
            raise PhaseFailedError("There is no generated code to deliver")
        findings = await self._findings(files)
        repository = await self.port.repository()
        if repository is None or not await self.port.may_push():
            await self.port.save_release(ReleaseRecord("zip", "ready", len(files), findings))
            why = "no repository is linked" if repository is None else "the run was started without code.push"
            return PhaseResult(summary=f"Release of {len(files)} files ready to download (ZIP); {why}")
        http, _, private = self.port.delivery_services()
        branch = nexti_delivery.branch_name(f"run-{ctx.run.run_id.hex[:8]}")

        async def ensure(url: str) -> None:
            if http is None:
                return
            if not private:
                await ensure_public_host(url)

        await ctx.store.event("started", "running", f"Pushing the release to {branch}", phase=ctx.phase.key)
        try:
            pushed = await nexti_delivery.push_release(
                repository.url, repository.token, repository.branch, branch,
                f"{nexti_delivery.RELEASE_PREFIX}/{design.context}", files,
                f"NexTI release of {design.context} (run {ctx.run.run_id})\n\nGenerated, verified (C4) and hardened by "
                "the NexTI platform. See docs/cutover/PLAN.md and hardening/REPORT.md.",
                ensure,
            )  # fmt: skip
        except Exception as exc:  # PushError or a refused host: the release stays as a ZIP
            detail = getattr(exc, "detail", None) or str(exc)
            await self.port.save_release(ReleaseRecord("push", "failed", len(files), findings, repository.url, branch,
                                                       error=detail[:500]))  # fmt: skip
            return PhaseResult(summary=f"Release of {len(files)} files ready as a ZIP; the push failed: {detail}"[:500])
        await self.port.save_release(ReleaseRecord("push", "pushed", len(files), findings, repository.url,
                                                   pushed.branch, pushed.commit, pushed.base))  # fmt: skip
        return PhaseResult(summary=f"Release of {len(files)} files pushed to {pushed.branch} ({pushed.commit[:10]})")

    async def _findings(self, files: dict[str, str]) -> dict[str, int]:
        report = files.get(nexti_hardening.REPORT_JSON)
        if not report:
            return {}
        counts = json.loads(report).get("counts", {})
        return {str(k): int(v) for k, v in counts.items()}
