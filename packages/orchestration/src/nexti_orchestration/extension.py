"""Flow 3, a delta added to an existing application (spec 3.1, ADR-0026). The documentary half (ingestion,
normalization, consolidation and the review before C1) is Flow 2's; these executors are the rest:

- inventory: the AS-IS application read by code (endpoints, fields, tables, services; no rules) and its baseline: the
  application compiled in the pack's sandbox with its own tests, whose passing tests the regression demands;
- design (C3): the architect proposes the changes from the approved stories and the inventory; code checks them
  against the inventory and the stories and sends the problems back;
- generation: per change, the test engineer writes the acceptance tests (one per criterion, with its id) and the
  backend developer writes the new files and the whole of each existing file it changes, until the application with
  the delta compiles and every test passes in the sandbox (do -> verify -> correct);
- validation (C4): the verdict computed by code with EXTEND_CHECKS, no model takes part;
- delivery: the delta alone, with its DELTA.md.

Only the delta is stored; an existing file is never deleted and an existing test is never changed.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nexti_agents import prompt
from nexti_core.adapters import SourceFile
from nexti_ivv.target import TargetInventory, inventory
from nexti_orchestration.context import Attempt, PhaseContext, Verification
from nexti_orchestration.extraction import ModelCaller, ReplyError, parse_json
from nexti_orchestration.feature import FeatureStory
from nexti_orchestration.feature_build import proof_pack
from nexti_orchestration.model import PhaseFailedError, PhaseResult, PhaseUnavailableError
from nexti_orchestration.packs import BackendPack, backend_pack
from nexti_sandbox import Sandbox
from nexti_sandbox.build import BuildResult
from nexti_verification import Verdict
from nexti_verification import verdict as checks

ARCHITECT, DEVELOPER, TESTER, VALIDATOR = "solution-architect", "backend-dev", "test-engineer", "acceptance-judge"
AS_IS = "delta/as-is-inventory.json"
BASELINE = "delta/baseline.json"
DESIGN = "delta/design.json"
DELTA = "delta/files.json"
INDEX = "delta/index.json"  # the new and the changed files, for the web
REPORT = "delta/DELTA.md"
ACTIVE = ("draft", "review", "question", "approved")
BUILD_FILES = ("pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "mvnw", "gradlew")
MAX_SOURCE_CHARS = 60_000
_BLOCK = re.compile(r"```[a-zA-Z]*[ \t]+([\w./-]+\.(?:java|sql|properties|ya?ml))[ \t]*\n(.*?)```", re.DOTALL)
_SQL = re.compile(
    r"(?i)\b(JdbcTemplate|EntityManager|SELECT\s+.+\s+FROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b"
)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldSpec(Model):
    name: str
    type: str = "string"


class Change(Model):
    """One change of the delta: a new endpoint, or an existing one extended, with what it reuses."""

    name: str = Field(pattern=r"^[A-Z][A-Za-z0-9]*$")
    description: str = ""
    stories: list[str] = Field(min_length=1)
    http_method: str | None = None
    path: str | None = None
    request: list[FieldSpec] = []
    response: list[FieldSpec] = []
    reuses: list[str] = []
    tables: list[str] = []
    new_tables: list[str] = []
    files: list[str] = []


class Decision(Model):
    title: str
    decision: str


class DeltaDesign(Model):
    changes: list[Change] = Field(min_length=1)
    decisions: list[Decision] = []


class ExtensionPort(Protocol):
    models: ModelCaller

    async def application_files(self) -> dict[str, str]:
        """Every text file of the existing application (the accepted source archive), by its path."""
        ...

    async def load_stories(self) -> list[FeatureStory]: ...

    async def load_inputs(self) -> dict[str, str]: ...

    async def open_questions(self) -> list[str]: ...

    async def save_file(self, path: str, content: str) -> str: ...

    async def load_file(self, reference: str) -> str: ...

    async def save_artifacts(
        self, files: dict[str, str], layers: dict[str, str], rules: dict[str, list[str]]
    ) -> None: ...

    async def load_artifact(self, path: str) -> str | None: ...

    async def save_verdict(self, verdict: Verdict, proof_pack: bytes) -> str: ...

    def sandbox(self, image: str) -> Sandbox: ...


# -- pure checks (tested without models) ----------------------------------------------------------------------------
def read_inventory(files: dict[str, str]) -> TargetInventory:
    return inventory([SourceFile(p, t) for p, t in files.items()])


def test_id(test: Any) -> str:
    return f"{test.classname}.{test.name}"


def delta_problems(design: DeltaDesign, stories: Sequence[FeatureStory], found: TargetInventory,
                   files: dict[str, str]) -> list[str]:  # fmt: skip
    """What makes a delta design unusable: a story left out, an endpoint that collides with an existing one, a reuse
    or a table the application does not have, a change aimed at an existing test or build file."""
    problems: list[str] = []
    keys = {s.key for s in stories if s.status in ACTIVE}
    covered = {k for c in design.changes for k in c.stories}
    problems += [f"The story {k} is in no change" for k in sorted(keys - covered)]
    problems += [f"The change {c.name} names the unknown story {k}" for c in design.changes for k in c.stories
                 if k not in keys]  # fmt: skip
    classes = {re.sub(r"\.\w+$", "", p.rsplit("/", 1)[-1]) for p in files}
    tables = {t.name.lower() for t in found.tables}
    seen: set[tuple[str, str]] = set()
    for change in design.changes:
        if change.http_method and change.path:
            route = (change.http_method.upper(), change.path)
            if route in seen:
                problems.append(f"Two changes declare {route[0]} {route[1]}")
            seen.add(route)
            if found.endpoint(*route) is not None and not change.reuses:
                problems.append(f"{route[0]} {route[1]} already exists: extend it (list what it reuses) or use "
                                "another path")  # fmt: skip
        problems += [f"The change {change.name} reuses {r}, which the application does not have" for r in
                     change.reuses if r not in classes]  # fmt: skip
        problems += [f"The change {change.name} uses the table {t}, which the application does not have" for t in
                     change.tables if t.lower() not in tables]  # fmt: skip
        protected = [p for p in change.files if (p in files and p.startswith("src/test/")) or p.endswith(BUILD_FILES)]
        problems += [f"The change {change.name} would touch {p}: existing tests and build files stay as they are"
                     for p in protected]  # fmt: skip
    return problems


def parse_files(content: str) -> dict[str, str]:
    """The files of a reply: fenced blocks whose info line names the path (```java src/main/java/...)."""
    found = {m.group(1).lstrip("./"): m.group(2).rstrip() + "\n" for m in _BLOCK.finditer(content)}
    if not found:
        raise ReplyError("no file in the answer: write each file in a fenced block whose first line is "
                         "```java <path>")  # fmt: skip
    return found


def placement_problems(delta: dict[str, str], existing: dict[str, str], *, tests: bool) -> list[str]:
    """Tests go to new files under src/test; code goes under src/main; build files are never touched."""
    problems: list[str] = []
    for path in delta:
        if ".." in path.split("/") or path.startswith("/"):
            problems.append(f"{path} is not a path inside the project")
        elif path.endswith(BUILD_FILES):
            problems.append(f"{path}: the build file stays as it is (only libraries already present can be used)")
        elif tests and not path.startswith("src/test/"):
            problems.append(f"{path}: tests go under src/test/")
        elif tests and path in existing:
            problems.append(f"{path} is an existing test: write a new test class instead")
        elif not tests and not path.startswith("src/main/"):
            problems.append(f"{path}: the code goes under src/main/")
    return problems


def fitness_violations(existing: dict[str, str], delta: dict[str, str]) -> list[str]:
    """The architecture rules of a delta (ADR-0026): no existing test or build file changed, nothing outside src/,
    and no SQL or persistence API in a controller the delta writes."""
    found: list[str] = []
    for path, content in delta.items():
        if path in existing and path.startswith("src/test/"):
            found.append(f"{path}: an existing test was changed")
        if path.endswith(BUILD_FILES):
            found.append(f"{path}: the build file was changed")
        if not path.startswith("src/"):
            found.append(f"{path}: outside src/")
        if "@RestController" in content or "@Controller" in content:
            match = _SQL.search(content)
            if match:
                found.append(f"{path}: the controller uses {match.group(1).split()[0]} (persistence belongs in the "
                             "services or repositories)")  # fmt: skip
    return found


def contract_broken(before: TargetInventory, after: TargetInventory) -> list[str]:
    """Existing endpoints that disappeared or lost request fields."""
    broken: list[str] = []
    for endpoint in before.endpoints:
        now = after.endpoint(endpoint.method, endpoint.path)
        if now is None:
            broken.append(f"{endpoint.method} {endpoint.path} was removed")
            continue
        lost = [f.name for f in endpoint.request if f.name not in {g.name for g in now.request}]
        if lost:
            broken.append(f"{endpoint.method} {endpoint.path} lost the request field(s) {', '.join(lost)}")
    return broken


_FALLBACK: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"if \(!([\w.]+(?:\(\))?)\.isEmpty\(\)\)"), r"if (\1.isEmpty())"),
    (re.compile(r"if \(([\w.]+(?:\(\))?)\.isEmpty\(\)\)"), r"if (!\1.isEmpty())"),
    (re.compile(r" == "), " != "),
    (re.compile(r" != "), " == "),
)


@dataclass(frozen=True)
class Mutation:
    line: int
    before: str
    after: str
    source: str


def fallback_mutations(source: str, limit: int = 3) -> list[Mutation]:
    """Deliberate one-line changes for delta code the pack's canary finds nothing to change in (queries and guards
    rather than calculations): a negated emptiness check or a flipped equality, in line order."""
    lines = source.split("\n")
    found: list[Mutation] = []
    for number, line in enumerate(lines, start=1):
        if line.strip().startswith(("//", "*", "/*", "import ", "package ")):
            continue
        for pattern, replacement in _FALLBACK:
            changed = pattern.sub(replacement, line, count=1)
            if changed != line:
                mutated = "\n".join([*lines[: number - 1], changed, *lines[number:]])
                found.append(Mutation(number, line, changed, mutated))
                break
        if len(found) == limit:
            break
    return found


def criteria_of(stories: Sequence[FeatureStory]) -> list[tuple[str, int, str]]:
    return [(s.key, n, c.strip().split("\n", 1)[0][:200]) for s in stories if s.status in ACTIVE
            for n, c in enumerate(s.criteria, start=1)]  # fmt: skip


def report(verdict: Verdict, delta: dict[str, str], existing: dict[str, str], design: DeltaDesign) -> str:
    added = sorted(p for p in delta if p not in existing)
    changed = sorted(p for p in delta if p in existing)
    lines = [
        "# Delta", "",
        f"Verdict: **{verdict.verdict}**", "",
        "| Check | Status | Detail |", "|---|---|---|",
        *[f"| {c.key} | {c.status} | {c.detail.replace('|', '/')} |" for c in verdict.checks], "",
        "## Changes", "",
        *[f"- **{c.name}** ({', '.join(c.stories)}): {c.description}"
          + (f" — `{c.http_method} {c.path}`" if c.http_method and c.path else "") for c in design.changes], "",
        f"## New files ({len(added)})", "", *[f"- `{p}`" for p in added], "",
        f"## Changed files ({len(changed)})", "", *[f"- `{p}`" for p in changed], "",
        "## Not proven", "", *[f"- {n}" for n in verdict.not_proven],
    ]  # fmt: skip
    return "\n".join(lines) + "\n"


def _sources(files: dict[str, str], prefer: Sequence[str] = ()) -> str:
    """The application's code for a prompt: the files a change names first, then the rest, within a budget."""
    ordered = sorted(files, key=lambda p: (p not in prefer, not p.endswith(".java"), p))
    out, used = [], 0
    for path in ordered:
        if not path.endswith((".java", ".sql", ".properties", ".yml", ".yaml")):
            continue
        block = f"// {path}\n{files[path]}"
        if used + len(block) > MAX_SOURCE_CHARS:
            out.append(f"// {path} (not shown: the budget of the prompt is used)")
            continue
        out.append(block)
        used += len(block)
    return "\n\n".join(out)


def _stories_text(stories: Sequence[FeatureStory], keys: Sequence[str] | None = None) -> str:
    chosen = [s for s in stories if s.status in ACTIVE and (keys is None or s.key in keys)]
    return "\n\n".join(
        f"{s.key}: {s.title}\n" + "\n".join(f"- {checks.criterion_test(s.key, n)}...: {c}"
                                            for n, c in enumerate(s.criteria, start=1)) for s in chosen
    )  # fmt: skip


# -- executors -------------------------------------------------------------------------------------------------------
class ExtensionPhases:
    def __init__(self, port: ExtensionPort) -> None:
        self.port = port

    def _pack(self, ctx: PhaseContext) -> BackendPack:
        pack = backend_pack(ctx.run.target)
        if pack is None or pack.name != "spring-boot":
            raise PhaseUnavailableError("Flow 3 extends Spring Boot applications in this version (ADR-0026)")
        return pack

    async def _application(self) -> dict[str, str]:
        files = await self.port.application_files()
        if not files:
            raise PhaseFailedError("There is no application to extend: upload its code (source_archive)")
        return files

    async def _json(self, path: str) -> Any:
        text = await self.port.load_artifact(path)
        if text is None:
            raise PhaseFailedError(f"{path} is missing: run the earlier phases first")
        return json.loads(text)

    async def inventory(self, ctx: PhaseContext) -> PhaseResult:
        pack = self._pack(ctx)
        files = await self._application()
        found = read_inventory(files)
        if found.stack != "spring-boot":
            raise PhaseFailedError(
                "The application is not recognized as Spring Boot: this flow extends an existing Spring Boot "
                "application (a pom.xml or build.gradle and its Java sources). Legacy code such as a stored procedure "
                "or COBOL programs goes in a Modernization project."
            )
        await ctx.store.event("started", "running", "Baseline: the application with its own tests in the sandbox",
                              phase=ctx.phase.key)  # fmt: skip
        build = await pack.compile_and_test(self.port.sandbox(pack.image), files)
        if not build.compiled:
            raise PhaseFailedError(f"The application does not compile as it is: {build.compile_errors[:1500]}")
        baseline = {"passed": sorted(test_id(t) for t in build.tests if t.status == "passed"),
                    "failed": sorted(test_id(t) for t in build.tests if t.status == "failed")}  # fmt: skip
        await self.port.save_artifacts(
            {AS_IS: json.dumps(asdict(found), indent=2, default=list), BASELINE: json.dumps(baseline, indent=2)},
            {AS_IS: "docs", BASELINE: "docs"}, {},
        )  # fmt: skip
        failing = f", {len(baseline['failed'])} already failing" if baseline["failed"] else ""
        return PhaseResult(summary=f"spring-boot: {len(found.endpoints)} endpoint(s), {len(found.tables)} table(s), "
                                   f"{len(found.slices)} service method(s); baseline: {len(baseline['passed'])} "
                                   f"test(s) pass{failing}")  # fmt: skip

    async def design(self, ctx: PhaseContext) -> PhaseResult:
        files = await self._application()
        found = TargetInventory.from_dict(await self._json(AS_IS))
        stories = [s for s in await self.port.load_stories() if s.status in ACTIVE]
        if not stories:
            raise PhaseFailedError("There are no approved user stories to design the delta from")
        request = [
            {"role": "system", "content": prompt("solution-architect-extend")},
            {"role": "user", "content": (
                f"User stories of the request:\n{_stories_text(stories)}\n\n"
                f"Inventory of the existing application:\n{json.dumps(asdict(found), indent=1, default=list)}\n\n"
                f"Code of the existing application:\n{_sources(files)}")},
        ]  # fmt: skip

        async def work(iteration: int, feedback: str | None) -> Attempt:
            messages = list(request)
            if feedback:
                messages.append({"role": "user", "content": f"The design cannot be used:\n{feedback}\nFix it."})
            reply = await self.port.models.complete(ARCHITECT, "design", messages, iteration=iteration)
            try:
                design = DeltaDesign.model_validate(parse_json(reply.content))
            except (ReplyError, ValidationError) as exc:
                return Attempt({"error": str(exc)[:3000]}, "design with format errors", reply.usage)
            reference = await self.port.save_file(DESIGN, design.model_dump_json(indent=1))
            return Attempt({"design": reference}, f"{len(design.changes)} change(s)", reply.usage)

        async def verify(artifact: dict[str, Any]) -> Verification:
            if "error" in artifact:
                return Verification(False, artifact["error"])
            design = DeltaDesign.model_validate_json(await self.port.load_file(artifact["design"]))
            problems = delta_problems(design, stories, found, files)
            return Verification(not problems, "\n".join(f"- {p}" for p in problems))

        attempt = await ctx.do_verify_correct(ARCHITECT, work, verify, what="Design of the delta")
        design = DeltaDesign.model_validate_json(await self.port.load_file(attempt.artifact["design"]))
        await self.port.save_artifacts({DESIGN: design.model_dump_json(indent=1)}, {DESIGN: "docs"}, {})
        endpoints = sum(1 for c in design.changes if c.path)
        return PhaseResult(summary=f"{len(design.changes)} change(s), {endpoints} endpoint(s), reusing "
                                   f"{len({r for c in design.changes for r in c.reuses})} existing class(es); "
                                   "ready for the architect (C3)")  # fmt: skip

    async def generation(self, ctx: PhaseContext) -> PhaseResult:
        pack = self._pack(ctx)
        existing = await self._application()
        design = DeltaDesign.model_validate(await self._json(DESIGN))
        stories = [s for s in await self.port.load_stories() if s.status in ACTIVE]
        sandbox = self.port.sandbox(pack.image)
        delta: dict[str, str] = {}
        for change in design.changes:
            piece = ctx.for_shard(f"change:{change.name}")
            delta |= await self._tests(piece, change, design, stories, existing, delta)
            delta |= await self._code(piece, pack, sandbox, change, design, stories, existing, delta)
        final = await pack.compile_and_test(sandbox, existing | delta)
        if not final.ok:
            raise PhaseFailedError(f"The application with the delta does not pass: {final.diagnostic(1500)}")
        layers = {p: "tests" if p.startswith("src/test/") else "domain" for p in delta}
        index = {
            "added": sorted(p for p in delta if p not in existing),
            "changed": sorted(p for p in delta if p in existing),
        }
        await self.port.save_artifacts(delta | {DELTA: json.dumps(delta, indent=1), INDEX: json.dumps(index, indent=1)},
                                       layers | {DELTA: "docs", INDEX: "docs"}, {})  # fmt: skip
        added = len(index["added"])
        return PhaseResult(summary=f"{added} new and {len(delta) - added} changed file(s); {final.passed} test(s) "
                                   "pass in the sandbox")  # fmt: skip

    async def _tests(self, ctx: PhaseContext, change: Change, design: DeltaDesign, stories: Sequence[FeatureStory],
                     existing: dict[str, str], delta: dict[str, str]) -> dict[str, str]:  # fmt: skip
        examples = {p: t for p, t in existing.items() if p.startswith("src/test/")}
        request = [
            {"role": "system", "content": prompt("test-engineer-extend")},
            {"role": "user", "content": (
                f"Change to test: {change.model_dump_json(indent=1)}\n\nWhole delta design:\n"
                f"{design.model_dump_json(indent=1)}\n\nAcceptance criteria:\n{_stories_text(stories, change.stories)}"
                f"\n\nExisting tests (follow their style and reuse their helpers):\n{_sources(examples)}\n\n"
                f"Code of the application:\n{_sources(existing | delta, change.files)}")},
        ]  # fmt: skip

        async def work(iteration: int, feedback: str | None) -> Attempt:
            messages = list(request)
            if feedback:
                messages.append({"role": "user", "content": f"The tests cannot be used:\n{feedback}\nFix them."})
            reply = await self.port.models.complete(TESTER, "generation", messages, iteration=iteration)
            try:
                files = parse_files(reply.content)
            except ReplyError as exc:
                return Attempt({"error": str(exc)}, "tests with format errors", reply.usage)
            problems = placement_problems(files, existing, tests=True)
            if problems:
                return Attempt({"error": "\n".join(problems)}, "tests in the wrong place", reply.usage)
            return Attempt({"files": await self.port.save_file(f"delta/tests-{change.name}.json", json.dumps(files))},
                           f"{len(files)} test file(s) for {change.name}", reply.usage)  # fmt: skip

        async def verify(artifact: dict[str, Any]) -> Verification:
            if "error" in artifact:
                return Verification(False, artifact["error"])
            files = json.loads(await self.port.load_file(artifact["files"]))
            ids = [checks.criterion_test(k, n) for s in stories if s.key in change.stories
                   for n, _ in enumerate(s.criteria, start=1) for k in [s.key]]  # fmt: skip
            text = "\n".join(files.values())
            missing = [i for i in ids if i not in text]
            return Verification(not missing, f"no test method starts with: {', '.join(missing)}")

        attempt = await ctx.do_verify_correct(TESTER, work, verify, what=f"Acceptance tests of {change.name}")
        return dict(json.loads(await self.port.load_file(attempt.artifact["files"])))

    async def _code(self, ctx: PhaseContext, pack: BackendPack, sandbox: Sandbox, change: Change,
                    design: DeltaDesign, stories: Sequence[FeatureStory], existing: dict[str, str],
                    delta: dict[str, str]) -> dict[str, str]:  # fmt: skip
        tests = {p: t for p, t in delta.items() if p.startswith("src/test/")}
        base = [
            {"role": "system", "content": prompt("backend-dev-extend")},
            {"role": "user", "content": (
                f"Change to implement: {change.model_dump_json(indent=1)}\n\nWhole delta design:\n"
                f"{design.model_dump_json(indent=1)}\n\nUser stories:\n{_stories_text(stories, change.stories)}\n\n"
                f"The tests it must pass:\n{_sources(tests)}\n\n"
                "Code of the application (with the delta written so far):\n"
                f"{_sources(existing | delta, change.files)}")},
        ]  # fmt: skip

        async def work(iteration: int, feedback: str | None) -> Attempt:
            messages = list(base)
            if feedback:
                messages.append({"role": "user", "content": f"The previous version failed:\n{feedback}\nFix it."})
            reply = await self.port.models.complete(DEVELOPER, "generation", messages, iteration=iteration)
            try:
                files = parse_files(reply.content)
            except ReplyError as exc:
                return Attempt({"error": str(exc)}, "code with format errors", reply.usage)
            problems = placement_problems(files, existing, tests=False)
            if problems:
                return Attempt({"error": "\n".join(problems)}, "code in the wrong place", reply.usage)
            return Attempt({"files": await self.port.save_file(f"delta/code-{change.name}.json", json.dumps(files))},
                           f"{len(files)} file(s) for {change.name}", reply.usage)  # fmt: skip

        async def verify(artifact: dict[str, Any]) -> Verification:
            if "error" in artifact:
                return Verification(False, artifact["error"])
            files = json.loads(await self.port.load_file(artifact["files"]))
            build: BuildResult = await pack.compile_and_test(sandbox, existing | delta | files)
            if build.ok and build.passed:
                return Verification(True)
            if build.compiled and not build.tests:
                return Verification(False, "no test ran: a test class did not compile or was not found")
            return Verification(False, build.diagnostic())

        attempt = await ctx.do_verify_correct(DEVELOPER, work, verify, what=f"Code of {change.name}")
        return dict(json.loads(await self.port.load_file(attempt.artifact["files"])))

    async def validation(self, ctx: PhaseContext) -> PhaseResult:
        async def work() -> Attempt:
            return Attempt(await self._validate(ctx), "verdict")

        attempt = await ctx.invoke(VALIDATOR, work, what="Validation of the delta (Flow 3)")
        return PhaseResult(summary=attempt.artifact["summary"])

    async def _validate(self, ctx: PhaseContext) -> dict[str, Any]:
        pack = self._pack(ctx)
        existing = await self._application()
        delta: dict[str, str] = await self._json(DELTA)
        design = DeltaDesign.model_validate(await self._json(DESIGN))
        baseline = await self._json(BASELINE)
        before = TargetInventory.from_dict(await self._json(AS_IS))
        stories = [s for s in await self.port.load_stories() if s.status in ACTIVE]
        merged = existing | delta
        sandbox = self.port.sandbox(pack.image)
        await ctx.store.event("started", "running", "Clean build and every test of the extended application",
                              phase=ctx.phase.key)  # fmt: skip
        build = await pack.compile_and_test(sandbox, merged)
        passed = [test_id(t) for t in build.tests if t.status == "passed"]
        criteria = criteria_of(stories)
        broken = contract_broken(before, read_inventory(merged))
        found = [
            checks.regression(baseline["passed"], passed, bool(build.junit_xml)),
            checks.criteria_covered(criteria, [t.name for t in build.tests if t.status == "passed"]),
            checks.contract_kept([f"{e.method} {e.path}" for e in before.endpoints], broken),
            checks.fitness(fitness_violations(existing, delta)),
        ]
        if build.ok and build.passed:
            found.append(checks.canary(await self._canary(ctx, pack, sandbox, existing, delta)))
        else:
            found.append(checks.Check("canary", "not_checked", "the extended application does not pass its tests, so "
                                      "a deliberate change cannot be told apart"))  # fmt: skip
        untraced = [s.key for s in stories if not s.links and not await self._cites_input(s)]
        untraced += [c.name for c in design.changes if not set(c.stories) & {s.key for s in stories}]
        found.append(checks.traced_to_inputs(len(stories) + len(design.changes), untraced))
        not_proven = [
            "The delta is checked through the application's tests; the running application (HTTP, database engine) is "
            "checked by the build, not end to end",
            "The regression covers what the application's own tests cover: behaviour no test exercises is not observed",
        ]
        if baseline["failed"]:
            not_proven.append(f"{len(baseline['failed'])} test(s) already failed before the delta and are not demanded")
        module = f"delta-{(before.main_class or 'application').rsplit('.', 1)[-1].lower()}"
        verdict = checks.compute(module, found, not_proven, required=checks.EXTEND_CHECKS)
        key = await self.port.save_verdict(verdict, proof_pack(verdict, build.junit_xml, {
            "CRITERIA.json": [{"story": s, "criterion": n, "scenario": name} for s, n, name in criteria],
            "BASELINE.json": baseline, "CONTRACT.json": {"broken": broken},
            "DELTA.json": {"added": sorted(p for p in delta if p not in existing),
                           "changed": sorted(p for p in delta if p in existing)},
        }))  # fmt: skip
        await self.port.save_artifacts({REPORT: report(verdict, delta, existing, design)}, {REPORT: "docs"}, {})
        ok = sum(1 for c in verdict.checks if c.status == "passed")
        return {"summary": f"{module}: {verdict.verdict} ({ok} of {len(verdict.checks)} checks passed)",
                "verdict": verdict.verdict, "proof_pack": key}  # fmt: skip

    async def _cites_input(self, story: FeatureStory) -> bool:
        """A story without links is traced when its text is in an accepted input (the request documents)."""
        inputs = await self.port.load_inputs()
        words = re.findall(r"\w{5,}", story.title.lower())[:6]
        return bool(words) and any(all(w in text.lower() for w in words) for text in inputs.values())

    async def _canary(self, ctx: PhaseContext, pack: BackendPack, sandbox: Sandbox, existing: dict[str, str],
                      delta: dict[str, str]) -> list[dict[str, Any]]:  # fmt: skip
        attempts: list[dict[str, Any]] = []
        for target in sorted(p for p in delta if p.startswith("src/main/") and p.endswith(".java")):
            for mutation in pack.mutations(delta[target]) or fallback_mutations(delta[target]):
                build = await pack.compile_and_test(sandbox, existing | delta | {target: mutation.source})
                failing = ["the compiler"] if not build.compiled else [
                    f"test {t.name}" for t in build.tests if t.status == "failed"]  # fmt: skip
                attempts.append({"file": target, "line": mutation.line, "before": mutation.before,
                                 "after": mutation.after, "caught_by": failing[0] if failing else ""})  # fmt: skip
                outcome = f"caught by {failing[0]}" if failing else "not caught"
                await ctx.store.event("info", "running", f"Canary {target}:{mutation.line}: {outcome}",
                                      phase=ctx.phase.key)  # fmt: skip
                if failing:
                    return attempts
        return attempts

    async def delivery(self, ctx: PhaseContext) -> PhaseResult:
        delta = await self.port.load_artifact(DELTA)
        report_text = await self.port.load_artifact(REPORT)
        if delta is None or report_text is None:
            raise PhaseFailedError("There is no validated delta to deliver")
        count = len(json.loads(delta))
        return PhaseResult(summary=f"The delta ({count} file(s)) and DELTA.md are ready: download them from Code, "
                                   "or push them to a new branch of the application's repository")  # fmt: skip
