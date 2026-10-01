"""The UI phase (spec 6.1 phase 7, 7.4): legacy screens become screen specs, and for each one the UX/UI designer writes
a navigable prototype with the NexTI design system. Code checks what the agent cannot be trusted with: the prototype
stays inside its frame, compiles in the web sandbox and shows every field of the spec (a `data-field` per field). A
person approves the UI at gate C2; changes asked through the chat produce new versions (D-24)."""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Literal, Protocol, cast

from nexti_adapter_bms import BmsAdapter
from nexti_agents import prompt
from nexti_core.adapters import SourceFile
from nexti_core.spec.screens import ScreenSpec
from nexti_orchestration.context import Attempt, PhaseContext, Verification
from nexti_orchestration.extraction import ModelCaller, ReplyError
from nexti_orchestration.model import PhaseResult
from nexti_sandbox import Sandbox
from nexti_ui import IMAGE, PrototypeBuild, build

DESIGNER = "ux-designer"


class UiPort(Protocol):
    models: ModelCaller

    async def source_files(self) -> list[SourceFile]: ...

    async def save_screens(self, screens: Sequence[ScreenSpec]) -> None: ...

    async def ensure_design_system(self) -> int:
        """The project's design system (version 1: the NexTI base); returns its version."""
        ...

    async def save_file(self, path: str, content: str) -> str: ...

    async def load_file(self, reference: str) -> str: ...

    async def save_prototype(self, screen: str, source: str, built: PrototypeBuild, origin: str, notes: str) -> int:
        """A new version of the screen's prototype (code and bundle in the object store); returns its number."""
        ...

    def sandbox(self, image: str) -> Sandbox: ...


def screens_of(files: list[SourceFile]) -> list[ScreenSpec]:
    """The screens the legacy defines (BMS maps in this version; ASPX in M8)."""
    adapter = BmsAdapter()
    return adapter.screens(files) if adapter.detect(files) > 0 else []


def tsx_block(content: str) -> str:
    match = re.search(r"```(?:tsx|jsx|typescript|ts)?\s*\n(.*?)```", content, re.DOTALL)
    code = (match.group(1) if match else content).strip()
    if "export default" not in code:
        raise ReplyError("the answer has no React component (export default) in a ```tsx block")
    return code + "\n"


def missing_fields(screen: ScreenSpec, source: str) -> list[str]:
    """Fields of the spec the prototype does not show (each one needs data-field="<name>")."""
    shown = set(re.findall(r"""data-field\s*=\s*(?:\{\s*)?['"]([^'"]+)['"]""", source))
    return [f.name for f in screen.fields if f.kind != "literal" and f.name not in shown]


def screen_request(screen: ScreenSpec, screens: Sequence[ScreenSpec]) -> str:
    others = ", ".join(f"{s.id} ({s.name})" for s in screens if s.id != screen.id) or "none"
    return (f"Screen spec:\n{screen.model_dump_json(indent=1, exclude_none=True)}\n\n"
            f"Other screens it may navigate to: {others}")  # fmt: skip


async def prototype(
    ctx: PhaseContext, port: UiPort, screen: ScreenSpec, screens: Sequence[ScreenSpec], *, origin: str = "generated",
    change: str = "", previous: str = "",
) -> dict[str, Any]:  # fmt: skip
    """Writes, checks and keeps one version of a screen's prototype (hacer-verificar-corregir)."""
    sandbox = port.sandbox(IMAGE)
    request = screen_request(screen, screens)
    if change:
        request += f"\n\nCurrent prototype:\n```tsx\n{previous}```\n\nChange asked by the reviewer: {change}"
    base = [{"role": "system", "content": prompt(DESIGNER)}, {"role": "user", "content": request}]

    async def work(iteration: int, feedback: str | None) -> Attempt:
        messages = list(base)
        if feedback:
            messages.append({"role": "user", "content": f"The prototype could not be used:\n{feedback}\nFix it."})
        reply = await port.models.complete(DESIGNER, "ui", messages, iteration=iteration)
        try:
            code = tsx_block(reply.content)
        except ReplyError as exc:
            return Attempt({"error": str(exc)}, "no component", reply.usage)
        reference = await port.save_file(f"prototypes/{screen.id}.tsx", code)
        return Attempt({"file": reference}, f"prototype of {screen.id}", reply.usage)

    async def verify(artifact: dict[str, Any]) -> Verification:
        if "error" in artifact:
            return Verification(False, artifact["error"])
        code = await port.load_file(artifact["file"])
        missing = missing_fields(screen, code)
        if missing:
            return Verification(False, "these fields of the spec are not shown (data-field=\"<name>\"): "
                                + ", ".join(missing))  # fmt: skip
        built = await build(sandbox, code)
        if not built.ok:
            return Verification(False, "\n".join(built.errors)[:4000])
        return Verification(True)

    attempt = await ctx.do_verify_correct(DESIGNER, work, verify, what=f"Prototype of {screen.id}")
    code = await port.load_file(attempt.artifact["file"])
    built = await build(sandbox, code)  # the verified code; built again to keep its bundle
    version = await port.save_prototype(screen.id, code, built, origin, change[:2000])
    return {"screen": screen.id, "version": version}


class UiPhases:
    def __init__(self, port: UiPort) -> None:
        self.port = port

    async def ui(self, ctx: PhaseContext) -> PhaseResult:
        if ctx.run.flow == "newFeature":  # Flow 2: the screens of the approved specification (from Figma, documents)
            screens = await cast(Any, self.port).load_screens()
            if not screens:
                return PhaseResult(summary="The specification has no screens: nothing to design")
        else:
            screens = screens_of(await self.port.source_files())
            if not screens:
                return PhaseResult(summary="The sources have no screens: nothing to design")
            await ctx.step("screens", lambda: self._save(screens))
        design_system = await ctx.step("design-system", self._design_system)
        for screen in screens:
            piece = ctx.for_shard(f"screen:{screen.id}")
            await piece.step("prototype", partial(prototype, piece, self.port, screen, screens))
        fields = sum(len([f for f in s.fields if f.kind != "literal"]) for s in screens)
        return PhaseResult(summary=f"{len(screens)} screen(s) with {fields} fields; a prototype per screen with the "
                                   f"design system v{design_system['version']}")  # fmt: skip

    async def _save(self, screens: list[ScreenSpec]) -> dict[str, Any]:
        await self.port.save_screens(screens)
        return {"screens": [s.id for s in screens]}

    async def _design_system(self) -> dict[str, Any]:
        return {"version": await self.port.ensure_design_system()}


# -- the change chat (D-24) --------------------------------------------------------------------------------------
@dataclass
class ChangeOutcome:
    """What a change asked through the chat produced: a new version, a proposal to change the spec (new fields the
    spec does not have), or nothing (the designer could not produce a valid prototype)."""

    kind: Literal["version", "proposal", "failed"]
    source: str = ""
    built: PrototypeBuild | None = None
    new_fields: list[str] = field(default_factory=list)
    detail: str = ""


def extra_fields(screen: ScreenSpec, source: str) -> list[str]:
    """data-field names the prototype shows that the spec does not have (a change of spec, never applied silently)."""
    shown = re.findall(r"""data-field\s*=\s*(?:\{\s*)?['"]([^'"]+)['"]""", source)
    known = {f.name for f in screen.fields}
    return sorted({name for name in shown if name not in known})


async def change_prototype(
    models: ModelCaller, sandbox: Sandbox, screen: ScreenSpec, screens: Sequence[ScreenSpec], previous: str,
    change: str, *, max_iterations: int = 3,
) -> ChangeOutcome:  # fmt: skip
    """The designer applies a reviewer's change to the current prototype; code checks it like any prototype."""
    request = (
        f"{screen_request(screen, screens)}\n\nCurrent prototype:\n```tsx\n{previous}```\n\n"
        f"Change asked by the reviewer: {change}\n\nIf the change needs a field the spec does not have, add it with "
        "its own data-field name: the platform will propose it as a change of the screen spec."
    )
    messages = [{"role": "system", "content": prompt(DESIGNER)}, {"role": "user", "content": request}]
    last = ""
    for iteration in range(1, max_iterations + 1):
        reply = await models.complete(DESIGNER, "ui", messages, iteration=iteration)
        problem = ""
        try:
            code = tsx_block(reply.content)
        except ReplyError as exc:
            problem, code = str(exc), ""
        if code:
            missing = missing_fields(screen, code)
            built = await build(sandbox, code) if not missing else None
            if missing:
                problem = "keep every field of the spec (data-field): missing " + ", ".join(missing)
            elif built is not None and not built.ok:
                problem = "\n".join(built.errors)[:4000]
            else:
                added = extra_fields(screen, code)
                kind: Literal["version", "proposal"] = "proposal" if added else "version"
                return ChangeOutcome(kind, code, built, added)
        last = problem
        messages += [{"role": "assistant", "content": reply.content},
                     {"role": "user", "content": f"The prototype could not be used:\n{problem}\nFix it."}]  # fmt: skip
    return ChangeOutcome("failed", detail=last)
