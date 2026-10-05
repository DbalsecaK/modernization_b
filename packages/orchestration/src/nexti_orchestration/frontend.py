"""Frontend generation and its verdict (spec 8.4, 11.3; ADR-0016, ADR-0028). After the backend, the frontend developer
writes one page per screen from its screen spec, its prototype (C2) and the typed client derived from the design (C3);
the platform's harness checks each page in the frontend sandbox (hacer-verificar-corregir). The skeleton, the OpenAPI
contract and the client are code. A frontend target without a pack makes generation wait (D-06); `none` builds no
frontend. Next.js adds its BFF route when the architecture is `bff-microservices` (ADR-0028)."""

import re
from typing import Any, Protocol, cast

from nexti_agents import prompt
from nexti_core.spec.screens import ScreenSpec
from nexti_orchestration.context import Attempt, PhaseContext, Verification
from nexti_orchestration.extraction import ModelCaller, ReplyError, raise_if_cut
from nexti_orchestration.model import PhaseFailedError, PhaseUnavailableError
from nexti_pack_frontend import IMAGE, PREFIX, ScreenContract, angular, contract_of, describe, nextjs, openapi, react
from nexti_pack_frontend.build import Flavour, FrontendRun, build_and_test
from nexti_pack_frontend.validation import problems
from nexti_pack_spring_boot import Design
from nexti_sandbox import Sandbox
from nexti_verification import verdict as checks

DEVELOPER = "frontend-dev"
PACKS: dict[str, Any] = {"react": react, "angular": angular, "nextjs": nextjs}
# what the agent writes in each flavour: the page component (React, Next.js) or the standalone component class
MARKERS = {"react": "export default", "nextjs": "export default", "angular": "export class"}
SUPPORT = {"react": "src/screens/types.ts", "nextjs": "src/app/screens/types.ts", "angular": "src/app/tokens.ts"}
NO_FRONTEND = ("", "none")


class FrontendPort(Protocol):
    models: ModelCaller

    async def load_screens(self) -> list[ScreenSpec]: ...

    async def load_prototypes(self) -> dict[str, str]:
        """The TSX source of the newest prototype of each screen (approved at C2 when there is one)."""
        ...

    async def save_file(self, path: str, content: str) -> str: ...

    async def load_file(self, reference: str) -> str: ...

    def sandbox(self, image: str) -> Sandbox: ...


def flavour_of(target: dict[str, Any]) -> Flavour | None:
    """The frontend pack of the run, None for no frontend; waits (D-06) for a frontend without a pack."""
    frontend = str(target.get("frontend") or "").lower()
    if frontend in NO_FRONTEND:
        return None
    if frontend not in PACKS:
        raise PhaseUnavailableError(f"The {frontend} frontend pack is not available yet: generation waits for it")
    return cast(Flavour, frontend)


def options_of(target: dict[str, Any], flavour: str) -> dict[str, Any]:
    """The flavour's skeleton options: Next.js serves the BFF route on a BFF architecture (ADR-0028)."""
    if flavour == "nextjs":
        return {"bff": str(target.get("architecture") or "") == "bff-microservices"}
    return {}


def code_block(content: str, flavour: str) -> str:
    languages = "ts|typescript" if flavour == "angular" else "tsx|jsx|typescript|ts"
    match = re.search(rf"```(?:{languages})?\s*\n(.*?)```", content, re.DOTALL)
    code = (match.group(1) if match else content).strip()
    marker = MARKERS[flavour]
    if marker not in code:
        raise ReplyError(f"the answer has no page ({marker}) in a code block")
    return code + "\n"


def _request(flavour: str, contract: ScreenContract, prototype: str, files: dict[str, str]) -> str:
    pack = PACKS[flavour]
    support = SUPPORT[flavour]
    return (
        f"Write the file {pack.screen_path(contract)}.\n\n{describe(contract)}\n\n"
        f"Typed client (src/api/client.ts):\n```ts\n{files['src/api/client.ts']}```\n\n"
        f"{support}:\n```ts\n{files[support]}```\n\n"
        "Approved prototype of the screen (React, for its layout and texts):\n"
        f"```tsx\n{prototype or '(none)'}```"
    )


async def generate(
    ctx: PhaseContext, port: FrontendPort, design: Design, flavour: Flavour
) -> tuple[dict[str, str], FrontendRun | None, str]:
    """The frontend files (under PREFIX), the final sandbox run and a summary."""
    screens = await port.load_screens()
    if not screens:
        return {}, None, "no screens: no frontend to build"
    pack = PACKS[flavour]
    options = options_of(ctx.run.target, flavour)
    contracts = [contract_of(s) for s in screens]
    contract = openapi(design)
    prototypes = await port.load_prototypes()
    sandbox = port.sandbox(IMAGE)
    agent = f"{DEVELOPER}-{flavour}"
    pages: dict[str, str] = {}
    done: list[ScreenContract] = []
    for screen in contracts:
        piece = ctx.for_shard(f"frontend:{screen.id}")
        files = pack.skeleton(contract, [*done, screen], design.context, **options)
        request = _request(flavour, screen, prototypes.get(screen.id, ""), files)
        base = [{"role": "system", "content": prompt(agent)}, {"role": "user", "content": request}]

        async def work(iteration: int, feedback: str | None, base: list[dict[str, str]] = base,
                       screen: ScreenContract = screen, piece: PhaseContext = piece) -> Attempt:  # fmt: skip
            messages = list(base)
            if feedback:
                messages.append({"role": "user", "content": f"The page could not be used:\n{feedback}\nFix it."})
            reply = await port.models.complete(DEVELOPER, "generation", messages, iteration=iteration)
            try:
                code = code_block(reply.content, flavour)
            except ReplyError as exc:
                raise_if_cut(reply, f"Page of {screen.id}", exc, repeated=bool(feedback), json_only=False)
                return Attempt({"error": str(exc)}, "no page", reply.usage)
            reference = await port.save_file(f"frontend/{pack.screen_path(screen)}", code)
            return Attempt({"file": reference}, f"page of {screen.id}", reply.usage)

        async def verify(artifact: dict[str, Any], files: dict[str, str] = files, screen: ScreenContract = screen,
                         ) -> Verification:  # fmt: skip
            if "error" in artifact:
                return Verification(False, artifact["error"])
            code = await port.load_file(artifact["file"])
            blocked = problems(code, flavour)
            if blocked:
                return Verification(False, "; ".join(blocked))
            run = await build_and_test(sandbox, flavour, {**files, **pages, pack.screen_path(screen): code},
                                       [*done, screen])  # fmt: skip
            result = run.screen(screen.id)
            if not run.compiled or not run.app or result is None:
                return Verification(False, run.diagnostic())
            return Verification(result.ok, "\n".join(result.problems())[:4000])

        attempt = await piece.do_verify_correct(DEVELOPER, work, verify, what=f"Page of {screen.id} ({flavour})")
        pages[pack.screen_path(screen)] = await port.load_file(attempt.artifact["file"])
        done.append(screen)
    files = {**pack.skeleton(contract, contracts, design.context, **options), **pages}
    final = await build_and_test(sandbox, flavour, files, contracts)
    if not final.ok:
        raise PhaseFailedError(f"The complete {flavour} frontend does not pass: {final.diagnostic()[:1500]}")
    summary = f"{flavour} frontend: {len(pages)} page(s) that compile and pass the harness"
    return {f"{PREFIX}{path}": content for path, content in files.items()}, final, summary


def frontend_checks(run: FrontendRun) -> list[checks.Check]:
    """The frontend verdict's checks (ADR-0016) from the sandbox run, screen by screen."""

    def by(key: str) -> checks.Check:
        name = {"screens_mount": "mounts", "fields_covered": "fields", "validations": "validation"}.get(key, key)
        failed = [
            f"{s.id}: {c.detail}" for s in run.screens for c in s.checks if c.key == name and c.status == "failed"
        ]
        ran = [s.id for s in run.screens for c in s.checks if c.key == name and c.status != "not_checked"]
        if failed:
            return checks.Check(key, "failed", "; ".join(failed)[:1500], {"screens": ran})
        if not ran:
            return checks.Check(key, "not_checked", "no screen has what this check needs")
        return checks.Check(key, "passed", f"{len(ran)} screen(s)", {"screens": ran})

    compiled = checks.Check("compiles", "passed" if run.compiled and run.app else "failed",
                            "the project type-checks and bundles" if run.compiled and run.app
                            else "\n".join(run.errors)[:1500])  # fmt: skip
    if compiled.status == "failed":
        return [compiled]
    return [compiled, *(by(key) for key, _ in checks.FRONTEND_CHECKS if key != "compiles")]
