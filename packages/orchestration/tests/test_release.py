# mypy: disable-error-code="index, arg-type, attr-defined, unused-ignore"
"""Hardening and delivery in the pipeline (ADR-0023): hardening keeps its report with the generated files; delivery
saves the cutover plan and leaves a release: a ZIP without a repository or without `code.push`, a new branch of the
customer's repository otherwise (dulwich's Git server, in the test), and a ZIP with the reason when the push fails."""

import asyncio
import json
import threading
import uuid
from collections.abc import Iterator, Mapping
from pathlib import Path
from wsgiref.simple_server import make_server

import pytest
from dulwich.repo import Repo
from dulwich.server import DictBackend
from dulwich.web import WSGIRequestHandlerLogger, WSGIServerLogger, make_wsgi_chain

from nexti_core.spec.design import Design
from nexti_orchestration import PhaseSpec, RunContext
from nexti_orchestration.context import PhaseContext
from nexti_orchestration.memory import MemoryStore
from nexti_orchestration.release import ReleasePhases, ReleaseRecord, Repository
from nexti_sandbox import Limits, SandboxResult

PACK = Path(__file__).resolve().parents[2] / "packs/target/spring_boot/tests/fixtures/pago_orden"
DESIGN = Design.model_validate_json((PACK / "design.json").read_text(encoding="utf-8"))
GENERATED = {"src/main/java/com/bank/payments/PayOrderService.java": "class PayOrderService {}\n",
             "pom.xml": "<project/>"}  # fmt: skip
JUNIT = '<testsuite><testcase classname="PayOrderServiceTest" name="pays" time="0.3"/></testsuite>'


class NoLeaks:
    async def run(self, command: list[str], files: Mapping[str, bytes] | None = None,
                  limits: Limits | None = None) -> SandboxResult:  # fmt: skip
        return SandboxResult(0, "===REPORT===\n[]", "", False, 5)


class MemoryPort:
    def __init__(self, repository: Repository | None = None, may_push: bool = True) -> None:
        self.files = dict(GENERATED)
        self.releases: list[ReleaseRecord] = []
        self._repository = repository
        self._may_push = may_push

    async def load_design(self) -> Design:
        return DESIGN

    async def load_generated(self) -> tuple[dict[str, str], dict[str, list[str]]]:
        return dict(self.files), {}

    async def load_infrastructure(self) -> dict[str, str]:
        return {"infra/aws/main.tf": "terraform {}\n"}

    async def save_artifacts(self, files: dict[str, str], layers: dict[str, str], rules: dict[str, list[str]]) -> None:
        self.files |= files

    def sandbox(self, image: str) -> NoLeaks:
        assert image == "nexti-sandbox-hardening:1"
        return NoLeaks()

    async def load_test_report(self) -> str:
        return JUNIT

    async def repository(self) -> Repository | None:
        return self._repository

    async def may_push(self) -> bool:
        return self._may_push

    async def save_release(self, release: ReleaseRecord) -> None:
        self.releases.append(release)

    def delivery_services(self) -> tuple[None, None, bool]:
        return None, None, True


def _context(phase: str) -> PhaseContext:
    spec = PhaseSpec(phase, None, True)
    run = RunContext(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "pipeline", "modernization", (spec,), (),
                     "balanced", 3, (), target={})  # fmt: skip
    return PhaseContext(run, MemoryStore(), spec, None)


@pytest.fixture
def git(tmp_path: Path) -> Iterator[tuple[str, Repo]]:
    repo = Repo.init_bare(str(tmp_path / "customer.git"), mkdir=True)
    app = make_wsgi_chain(DictBackend({"/customer.git": repo}))
    httpd = make_server("127.0.0.1", 0, app, handler_class=WSGIRequestHandlerLogger, server_class=WSGIServerLogger)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/customer.git", repo
    httpd.shutdown()


def test_hardening_keeps_its_report_with_the_generated_files() -> None:
    port = MemoryPort()
    result = asyncio.run(ReleasePhases(port).hardening(_context("hardening")))
    assert result.summary == "Hardening: no findings"
    report = json.loads(port.files["hardening/report.json"])
    assert {c["kind"]: c["status"] for c in report["checks"]} == {
        "secrets": "checked", "dependencies": "checked", "patterns": "checked", "performance": "checked"}  # fmt: skip
    assert port.files["hardening/REPORT.md"].startswith("# Hardening report")


def test_without_a_repository_the_release_is_the_zip_with_its_plan() -> None:
    port = MemoryPort()
    result = asyncio.run(ReleasePhases(port).delivery(_context("delivery")))
    assert "ready to download (ZIP); no repository is linked" in result.summary
    assert "docs/cutover/PLAN.md" in port.files
    assert (port.releases[0].kind, port.releases[0].status, port.releases[0].files) == ("zip", "ready", 5)


def test_a_release_without_code_push_stays_a_zip(git: tuple[str, Repo]) -> None:
    port = MemoryPort(Repository(git[0], "main", None), may_push=False)
    result = asyncio.run(ReleasePhases(port).delivery(_context("delivery")))
    assert result.summary.endswith("the run was started without code.push")
    assert git[1].refs.as_dict() == {}


def test_the_release_is_pushed_to_a_new_branch(git: tuple[str, Repo]) -> None:
    url, repo = git
    port = MemoryPort(Repository(url, "main", None))
    ctx = _context("delivery")
    result = asyncio.run(ReleasePhases(port).delivery(ctx))
    release = port.releases[0]
    branch = f"nexti/run-{ctx.run.run_id.hex[:8]}"
    assert (release.kind, release.status, release.branch) == ("push", "pushed", branch)
    assert result.summary.startswith(f"Release of 5 files pushed to {branch}")
    assert repo.refs[f"refs/heads/{branch}".encode()].decode() == release.commit_sha


def test_a_failed_push_leaves_the_zip_and_the_reason() -> None:
    port = MemoryPort(Repository("http://127.0.0.1:9/none.git", "main", "secret-token"))
    result = asyncio.run(ReleasePhases(port).delivery(_context("delivery")))
    release = port.releases[0]
    assert (release.kind, release.status) == ("push", "failed")
    assert "could not be read" in (release.error or "")
    assert "secret-token" not in result.summary
