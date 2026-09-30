"""Builds and tests a generated frontend in the sandbox (ADR-0016): the compiler (tsc or ngc), the bundles, and the
platform's harness on every screen. What passed comes from the sandbox report, never from what an agent says."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from nexti_pack_frontend.contract import ScreenContract
from nexti_sandbox import Limits, Sandbox

Flavour = Literal["react", "angular"]
LIMITS = Limits(cpus=2.0, memory_mb=1536, pids=256, timeout_seconds=420, work_mb=512, max_output_bytes=4 * 1024 * 1024)
CHECKS = ("mounts", "fields", "actions", "validation", "accessibility", "submit", "navigation")


@dataclass(frozen=True)
class ScreenCheck:
    key: str
    status: Literal["passed", "failed", "not_checked"]
    detail: str


@dataclass
class ScreenRun:
    id: str
    checks: list[ScreenCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.status != "failed" for c in self.checks) and bool(self.checks)

    def problems(self) -> list[str]:
        return [f"{c.key}: {c.detail}" for c in self.checks if c.status == "failed"]


@dataclass
class FrontendRun:
    flavour: str
    compiled: bool
    app: bool
    errors: list[str]
    screens: list[ScreenRun]

    @property
    def ok(self) -> bool:
        return self.compiled and self.app and bool(self.screens) and all(s.ok for s in self.screens)

    def screen(self, screen_id: str) -> ScreenRun | None:
        return next((s for s in self.screens if s.id == screen_id), None)

    def diagnostic(self) -> str:
        if not self.compiled:
            return "the project does not compile:\n" + "\n".join(self.errors)[:4000]
        if not self.app:
            return "the project does not bundle:\n" + "\n".join(self.errors)[:4000]
        return "\n".join(f"{s.id}: {p}" for s in self.screens for p in s.problems())[:4000]


def parse(output: str, flavour: str) -> FrontendRun:
    if "===FRONTEND===" not in output:
        return FrontendRun(flavour, False, False, [output[-3000:] or "the sandbox printed no report"], [])
    data: dict[str, Any] = json.loads(output.split("===FRONTEND===", 1)[1].split("===END===", 1)[0])
    screens = [ScreenRun(s["id"], [ScreenCheck(c["key"], c["status"], c["detail"]) for c in s["checks"]])
               for s in data.get("screens", [])]  # fmt: skip
    return FrontendRun(
        flavour, bool(data.get("compiled")), bool(data.get("app")), list(data.get("errors", [])), screens
    )


async def build_and_test(
    sandbox: Sandbox, flavour: Flavour, files: Mapping[str, str], contracts: Sequence[ScreenContract]
) -> FrontendRun:
    """`files` are the project's files (paths relative to the project root)."""
    inputs = {f"project/{path}": content.encode("utf-8") for path, content in files.items()}
    inputs["screens.json"] = json.dumps([c.to_json() for c in contracts]).encode("utf-8")
    result = await sandbox.run(["node", "/opt/sandbox/scripts/run.mjs", flavour], files=inputs, limits=LIMITS)
    return parse(result.stdout, flavour)
