"""Design (C3) and generation by layers (spec 6.1 phases 8 and 10) with the project's backend pack (ADR-0017).

- Design: the solution architect proposes the design from the approved rules and the inventory; code validates it
  (structure, neutral types, references, every rule in a use case) and sends the problems back.
- Generation: the pack writes the skeleton; per use case the test engineer writes the tests from the rule scenarios
  first (the oracle), then the backend developer writes the service until those tests pass in the pack's sandbox
  (do -> verify -> correct, 11.1); then the adapters, which must compile; the wiring is generated. Each layer
  compiles before the next. The generated files go to the object store; only references stay in the graph state.

A project whose backend has no pack yet waits in generation (ADR-0010): it never generates another language.
"""

import difflib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast

from pydantic import ValidationError

from nexti_agents import prompt
from nexti_core.adapters import SourceFile
from nexti_core.spec.model import Rule
from nexti_orchestration import frontend, infrastructure
from nexti_orchestration.context import Attempt, PhaseContext, Verification
from nexti_orchestration.extraction import ModelCaller, ReplyError, is_cut, parse_json, raise_if_cut
from nexti_orchestration.guided import enabled as guided_enabled
from nexti_orchestration.guided import stack_guidance
from nexti_orchestration.model import PhaseFailedError, PhaseResult, PhaseUnavailableError
from nexti_orchestration.packs import BackendPack, backend_pack
from nexti_orchestration.store import Usage
from nexti_orchestration.usage import total as _total
from nexti_pack_spring_boot import Design, UseCase
from nexti_pack_spring_boot.pack import PACK as SPRING_BOOT
from nexti_pack_spring_boot.pack import wiring
from nexti_sandbox import Sandbox
from nexti_sandbox.build import BuildResult
from nexti_verification.verdict import criterion_test

ARCHITECT = "solution-architect"
FEATURE_ARCHITECT = "solution-architect-feature"  # the prompt of the design without legacy (Flow 2)
DEVELOPER = "backend-dev"
TESTER = "test-engineer"

__all__ = ["GenerationPhases", "design_problems", "java_block", "legacy_names", "propose_design", "wiring"]


class GenerationPort(Protocol):
    models: ModelCaller

    async def load_rules(self) -> list[Rule]: ...

    async def inventory_digest(self) -> str:
        """Tables, procedures and parameters with neutral types, as text for the architect."""
        ...

    async def source_files(self) -> list[SourceFile]: ...

    async def save_design(self, design: Design) -> None: ...

    async def load_design(self) -> Design | None: ...

    async def save_file(self, path: str, content: str) -> str:
        """Keep a generated file (object store); returns its reference."""
        ...

    async def load_file(self, reference: str) -> str: ...

    async def save_artifacts(
        self, files: dict[str, str], layers: dict[str, str], rules: dict[str, list[str]]
    ) -> None: ...

    def sandbox(self, image: str) -> Sandbox: ...


def code_block(pack: BackendPack, content: str) -> str:
    """The code of an agent's answer in the pack's language; a ReplyError when there is none."""
    try:
        return pack.code_block(content)
    except ValueError as exc:
        raise ReplyError(str(exc)) from exc


def java_block(content: str) -> str:
    return code_block(SPRING_BOOT, content)


_NAME = re.compile(r"[@#]?[A-Za-z_][A-Za-z0-9_$#@]*")
_COBOL_NAME = re.compile(r"\b[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+\b")


def legacy_names(files: Sequence[SourceFile]) -> set[str]:
    """Every identifier of the legacy source, lowercase: what the design may name as legacy. A COBOL name keeps its
    hyphens and is also known with underscores (ORD-NUMERO is ord_numero), the form traces and targets use."""
    names = {m.group(0).lower() for f in files for m in _NAME.finditer(f.text)}
    names |= {m.group(0).lower().replace("-", "_") for f in files for m in _COBOL_NAME.finditer(f.text)}
    return names


_INVISIBLE = re.compile(r"[\u200b-\u200f\u2060\ufeff\u00a0\s]")


def _normal(name: str) -> str:
    """A legacy name as it is compared: Unicode-normalized, without invisible characters, lowercase, without the
    schema or program prefix (`db..tabla.col` -> `col`)."""
    return _INVISIBLE.sub("", unicodedata.normalize("NFKC", name)).lower().rsplit(".", 1)[-1]


def _known(name: str, names: set[str]) -> bool:
    """`@o_trn` and `o_trn` name the same parameter: the design may drop the marker, or add it to a column."""
    plain = _normal(name)
    return plain in names or plain.lstrip("@#") in names or any(f"{marker}{plain}" in names for marker in "@#")


def closest(invented: Sequence[str], names: set[str], count: int = 3) -> str:
    """For each invented name, the real names that look like it: the model corrects the spelling, or learns that the
    name does not exist and must not be cited."""
    by_bare: dict[str, str] = {}
    for known in sorted(names):
        by_bare.setdefault(known.lstrip("@#"), known)
    parts = []
    for name in invented:
        found = difflib.get_close_matches(_normal(name).lstrip("@#"), list(by_bare), n=count, cutoff=0.6)
        parts.append(
            f"{name} -> {', '.join(by_bare[f] for f in found) if found else 'nothing similar: do not cite it'}"
        )
    return "; ".join(parts)


def _invented(design: Design, names: set[str]) -> list[str]:
    """Legacy names of the design that do not exist in the legacy code (the design cannot cite what is not there)."""
    cited = [f.legacy for e in design.entities for f in e.fields]
    cited += [f.legacy for u in design.use_cases for f in [*u.inputs, *u.outputs]]
    cited += [u.legacy_message for u in design.use_cases]
    cited += [f.legacy for p in design.ports for m in p.methods for f in m.inputs]
    cited += [m.legacy_output for p in design.ports for m in p.methods]
    cited += [e.legacy_table for e in design.entities] + [p.legacy_program for p in design.ports]
    cited += [u.legacy_program for u in design.use_cases] + list(design.infrastructure)
    missing = []
    for name in cited:
        if name and not _known(name, names):
            missing.append(name)
    return sorted(set(missing))


GUIDED_DESIGN = (
    "Design constraints, checked by code: every legacy table the program writes needs an entity with its "
    "legacy_table; a `tables:` mask is refused when an approved rule reads or writes that table; a legacy program "
    "called from lines an approved rule cites is business, not infrastructure: give it a port with legacy_program; "
    "list in `infrastructure` only programs that implement no rule (error and event logging, auditing)."
)


def table_of(target: str) -> str:
    """The table in a mask target or a legacy name: `db..tabla.col` -> `tabla`, `db.dbo.tabla` -> `tabla`."""
    parts = [p for p in target.split("..")[-1].split(".") if p]
    if ".." in target:  # db..tabla or db..tabla.col
        return parts[0].lower()
    return (parts[-2] if len(parts) >= 4 else parts[-1]).lower()  # db.dbo.tabla, db.dbo.tabla.col, tabla


# A table read within this many lines before a line a rule cites feeds that rule (the SELECT that loads the values
# the cited IF tests): masking it hides business (ADR-0035, precision of 2026-10-05).
FEEDING_WINDOW = 40


def mask_problems(
    design: Design, rules: Sequence[Rule], files: Sequence[SourceFile], written: set[str], read: set[str] | None = None
) -> list[str]:
    """Guided design (ADR-0035): a mask or an `infrastructure` entry cannot hide business. A table the approved rules
    read or write stays as an entity, and so does a table the program reads just before the lines a rule cites (its
    values feed the rule); a program called from lines a rule cites is a port, not infrastructure; every table the
    program writes is kept by an entity or masked with a reason."""
    lines = {f.path.rsplit("/", 1)[-1].lower(): f.text.splitlines() for f in files}

    def cited(rule: Rule, before: int = 0) -> str:
        parts = []
        for ref in rule.sources:
            text = lines.get(ref.file.rsplit("/", 1)[-1].lower())
            if text:
                parts.append("\n".join(text[max(ref.line_start - 1 - before, 0) : ref.line_end]))
        return "\n".join(parts).lower()

    cited_by = {r.id: cited(r) for r in rules}
    feeding = {r.id: cited(r, FEEDING_WINDOW) for r in rules}

    def users(name: str, texts: Mapping[str, str] | None = None) -> list[str]:
        pattern = re.compile(rf"(?<![a-z0-9_]){re.escape(name)}(?![a-z0-9_])")
        return sorted(rid for rid, text in (texts or cited_by).items() if pattern.search(text))

    problems = []
    for mask in design.masks:
        kind, _, target = mask.path.partition(":")
        if kind != "tables":
            continue
        if ids := users(table_of(target)):
            problems.append(f"mask {mask.path} hides a table the rules use ({', '.join(ids)}): keep it as an entity "
                            "with its legacy_table")  # fmt: skip
        elif table_of(target) in (read or set()) and (ids := users(table_of(target), feeding)):
            problems.append(f"mask {mask.path} hides a table the program reads right before lines the rules cite "
                            f"({', '.join(ids)}): the values it loads feed those rules, so keep it as an entity with "
                            "its legacy_table (a lookup the target replaces is still an entity)")  # fmt: skip
    for program in design.infrastructure:
        if ids := users(_normal(program)):
            problems.append(f"{program} is listed as infrastructure, but the rules cite its call ({', '.join(ids)}): "
                            "give it a port with legacy_program")  # fmt: skip
    kept = {table_of(e.legacy_table) for e in design.entities if e.legacy_table}
    masked = {table_of(m.path.partition(":")[2]) for m in design.masks if m.path.startswith("tables:")}
    missing = sorted(t for t in written if t not in kept and t not in masked)
    if missing:
        problems.append("legacy tables the program writes need an entity with legacy_table (or an explained "
                        f"tables: mask): {', '.join(missing)}")  # fmt: skip
    return problems


def design_problems(
    design: Design, rules: Sequence[Rule], names: set[str] | None = None, *, hints: bool = False,
    files: Sequence[SourceFile] = (), written: set[str] | None = None, package_root: str | None = None,
    read: set[str] | None = None,
) -> list[str]:  # fmt: skip
    """What is wrong with a design, for the model to correct. With `hints` (guided extraction, ADR-0033) an invented
    legacy name comes with the closest real names, and the masks are checked against the rules (ADR-0035)."""
    missing = sorted({r.id for r in rules} - design.rules())
    unknown = sorted(design.rules() - {r.id for r in rules})
    problems = []
    if missing:
        problems.append(f"these rules are in no use case: {', '.join(missing)}")
    if unknown:
        problems.append(f"use cases list rules that do not exist: {', '.join(unknown)}")
    # Traceability to the legacy: without it the golden master cannot be replayed on the target (spec 11.3).
    unmapped = [f"{e.name}.{f.name}" for e in design.entities if e.legacy_table for f in e.fields if not f.legacy]
    if unmapped:
        problems.append(f"fields of entities with a legacy table need their legacy column: {', '.join(unmapped)}")
    not_columns = [f"{e.name}.{f.name} = {f.legacy}" for e in design.entities for f in e.fields
                   if f.legacy and f.legacy[:1] in "@#"]  # fmt: skip
    if not_columns:
        problems.append("entity fields map to columns of their legacy table, not to parameters or variables: "
                        f"{', '.join(not_columns)}")  # fmt: skip
    for use_case in design.use_cases:
        loose = [f.name for f in [*use_case.inputs, *use_case.outputs] if not f.legacy]
        if use_case.legacy_program and loose:
            problems.append(f"{use_case.name}: inputs and outputs need their legacy parameter: {', '.join(loose)}")
    external = [p.name for p in design.ports if p.legacy_program for m in p.methods for f in m.inputs if not f.legacy]
    if external:
        problems.append(f"methods of ports that replace a legacy program need the argument of each input: "
                        f"{', '.join(sorted(set(external)))}")  # fmt: skip
    invented = _invented(design, names) if names is not None else []
    if invented:
        problems.append(f"these legacy names are not in the legacy code (check the exact spelling): "
                        f"{', '.join(invented)}")  # fmt: skip
        if hints and names:
            problems.append(f"closest names in the legacy code: {closest(invented, names)}")
    if hints:
        problems += mask_problems(design, rules, files, written or set(), read)
        root = (package_root or "").strip().lower()
        if root and not (design.base_package == root or design.base_package.startswith(root + ".")):
            problems.append(f"base_package must be {root} or start with {root}. (the pack profile of the project)")
    return problems


def _tables(files: Sequence[SourceFile], edge_type: str) -> set[str]:
    from nexti_orchestration.modernization import pick_adapter

    try:
        inventory = pick_adapter(list(files)).inventory(list(files))
    except Exception:
        return set()
    return {table_of(e.target.split(":", 1)[-1]) for e in inventory.edges if str(e.type) == edge_type}


def written_tables(files: Sequence[SourceFile]) -> set[str]:
    """The tables the legacy writes, from the inventory of the source adapter (bare names, lowercase)."""
    return _tables(files, "WRITES")


def read_tables(files: Sequence[SourceFile]) -> set[str]:
    """The tables the legacy reads, from the inventory of the source adapter (bare names, lowercase)."""
    return _tables(files, "READS")


def _rules_text(rules: Sequence[Rule]) -> str:
    return json.dumps(
        [r.model_dump(mode="json", include={"id", "name", "category", "priority", "statement", "condition", "action",
                                            "inputs", "outputs", "scenarios", "sources"}) for r in rules],
        ensure_ascii=False, indent=1,
    )  # fmt: skip


async def propose_design(
    caller: ModelCaller, rules: Sequence[Rule], inventory: str, *, max_iterations: int = 3,
    names: set[str] | None = None, source: str = "", system: str = ARCHITECT, label: str = "Inventory",
    hints: bool = False, files: Sequence[SourceFile] = (), written: set[str] | None = None, guidance: str = "",
    package_root: str | None = None, read: set[str] | None = None,
) -> tuple[Design, list[Usage]]:  # fmt: skip
    """The design from the rules. Flow 1 gives the inventory of the legacy; Flow 2 gives the approved screens and
    stories (`label`) and its own prompt (`system`), with no legacy to map."""
    messages = [
        {"role": "system", "content": prompt(system)},
        {
            "role": "user",
            "content": f"{label}:\n{inventory}\n\nApproved rules:\n{_rules_text(rules)}"
            + (f"\n\nLegacy source (the columns and parameters to map):\n{source}" if source else "")
            + (f"\n\n{GUIDED_DESIGN}" if hints else "")
            + (f"\n\n{guidance}" if hints and guidance else ""),
        },
    ]
    usage: list[Usage] = []
    last = ""
    cut_before = False
    for iteration in range(1, max_iterations + 1):
        reply = await caller.complete(ARCHITECT, "design", messages, iteration=iteration)
        usage.append(reply.usage)
        try:
            data = parse_json(reply.content)
            design = Design.model_validate(data)
            problems = design_problems(design, rules, names, hints=hints, files=files, written=written,
                                       package_root=package_root, read=read)  # fmt: skip
            if problems:
                raise ReplyError("\n".join(problems))
            return design, usage
        except (ReplyError, ValidationError) as exc:
            raise_if_cut(reply, "Target design", exc, repeated=cut_before)
            cut_before = is_cut(reply, exc)
            detail = str(exc) if isinstance(exc, ReplyError) else "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:10])  # fmt: skip
            last = detail
            messages += [
                {"role": "assistant", "content": reply.content},
                {"role": "user", "content": f"The design has these problems; fix them and answer again:\n{detail}"},
            ]
    raise ReplyError(f"no valid design after {max_iterations} attempts: {last}")


class GenerationPhases:
    def __init__(self, port: GenerationPort) -> None:
        self.port = port

    async def design(self, ctx: PhaseContext) -> PhaseResult:
        rules = await self.port.load_rules()
        if not rules:
            raise PhaseFailedError("There are no approved rules to design from")

        async def work() -> Attempt:
            try:
                if ctx.run.flow == "newFeature":  # Flow 2: contracts first from the screens and stories (ADR-0018)
                    design, usage = await propose_design(
                        self.port.models, rules, await self._feature_context(), max_iterations=ctx.run.max_iterations,
                        system=FEATURE_ARCHITECT, label="Approved screens and user stories (there is no legacy)",
                    )  # fmt: skip
                else:
                    files = await self.port.source_files()
                    design, usage = await propose_design(
                        self.port.models, rules, await self.port.inventory_digest(),
                        max_iterations=ctx.run.max_iterations, names=legacy_names(files),
                        source="\n\n".join(f"// {f.path}\n{f.text}" for f in files),
                        hints=guided_enabled(ctx.run.options), files=files, written=written_tables(files),
                        read=read_tables(files), guidance=stack_guidance(ctx.run.target),
                        package_root=ctx.run.target.get("package_root"),
                    )  # fmt: skip
            except ReplyError as exc:
                raise PhaseFailedError(str(exc)[:1500]) from exc
            await self.port.save_design(design)
            summary = (f"{len(design.use_cases)} use case(s), {len(design.entities)} entities, "
                       f"{len(design.ports)} ports, {len(design.decisions)} decisions")  # fmt: skip
            return Attempt({"context": design.context}, summary, _total(usage))

        attempt = await ctx.invoke(ARCHITECT, work, what="Target design")
        return PhaseResult(summary=attempt.summary)

    async def _feature_context(self) -> str:
        """What the architect designs from in Flow 2: the screens and the stories with their criteria."""
        screens = await self.port.load_screens() if hasattr(self.port, "load_screens") else []
        stories = await self.port.load_stories() if hasattr(self.port, "load_stories") else []
        active = [s for s in stories if s.status not in ("discarded", "merged")]
        return json.dumps({
            "screens": [s.model_dump(mode="json", exclude_none=True, exclude={"sources"}) for s in screens],
            "stories": [{"key": s.key, "title": s.title, "links": s.links, "criteria": s.criteria} for s in active],
        }, ensure_ascii=False, indent=1)  # fmt: skip

    async def _criteria(self, design: Design) -> dict[str, str]:
        """Flow 2: the acceptance criteria each use case must have tests for (the stories that link its rules)."""
        if not hasattr(self.port, "load_stories"):
            return {}
        stories = [s for s in await self.port.load_stories() if s.status not in ("discarded", "merged")]
        found: dict[str, str] = {}
        for use_case in design.use_cases:
            lines = [f"- {criterion_test(s.key, n)}...:\n{c}" for s in stories if set(s.links) & set(use_case.rules)
                     for n, c in enumerate(s.criteria, start=1)]  # fmt: skip
            if lines:
                found[use_case.name] = "\n".join(lines)
        return found

    async def generation(self, ctx: PhaseContext) -> PhaseResult:
        pack = backend_pack(ctx.run.target)
        if pack is None:
            backend = ctx.run.target.get("backend")
            raise PhaseUnavailableError(f"The {backend} pack is not available yet: generation waits for it")
        pack = pack.configured(ctx.run.target)  # the chosen version, when the pack supports it (ADR-0040)
        flavour = frontend.flavour_of(ctx.run.target) if hasattr(self.port, "load_screens") else None
        design = await self.port.load_design()
        if design is None:
            raise PhaseFailedError("There is no approved design to generate from")
        rules = {r.id: r for r in await self.port.load_rules()}
        sandbox = self.port.sandbox(pack.image)
        files = pack.skeleton(design)
        # The REST controllers and the wiring use the services, so they join once every service exists.
        held = {p: files.pop(p) for p in list(files) if pack.held_back(p)}
        build = await pack.compile_and_test(sandbox, files, run_tests=False)
        if not build.compiled:
            raise PhaseFailedError(f"The generated skeleton does not compile: {build.compile_errors[:1500]}")
        await ctx.store.event("info", "succeeded", "Layers contracts and domain model compile", phase=ctx.phase.key)
        tests_run = 0
        criteria = await self._criteria(design) if ctx.run.flow == "newFeature" else {}
        for use_case in design.use_cases:
            # One shard per piece: its invocations and journal entries never mix with another piece's.
            piece = ctx.for_shard(f"use-case:{use_case.name}")
            files[pack.test_path(design, use_case)] = await self._tests(piece, pack, design, use_case, rules, files,
                                                                        criteria.get(use_case.name, ""))  # fmt: skip
            files[pack.service_path(design, use_case)] = await self._service(piece, pack, design, use_case, rules,
                                                                             files, sandbox)  # fmt: skip
        for port_spec in design.ports:
            piece = ctx.for_shard(f"adapter:{port_spec.name}")
            files[pack.adapter_path(design, port_spec)] = await self._adapter(piece, pack, design, port_spec.name,
                                                                              files, sandbox)  # fmt: skip
        # The wiring may name every adapter (the .NET pack does), so the held files join once all of them exist.
        files.update(held)
        final = await pack.compile_and_test(sandbox, files)
        if not final.ok:
            raise PhaseFailedError(f"The complete project does not pass: {final.diagnostic(1500)}")
        tests_run = final.passed
        layers = {p: pack.layer_of(p, design) for p in files}
        traced = {pack.service_path(design, u): u.rules for u in design.use_cases}
        traced.update({pack.test_path(design, u): u.rules for u in design.use_cases})
        await self.port.save_artifacts(files, layers, traced)
        summary = f"{len(files)} files in {len(set(layers.values()))} layers; {tests_run} tests pass in the sandbox"
        if flavour is not None:
            port = cast(frontend.FrontendPort, self.port)
            pages, _, frontend_summary = await frontend.generate(ctx, port, design, flavour)
            if pages:
                contracts = ("openapi.json", "client.ts", "client-runtime.ts")
                await self.port.save_artifacts(pages, {p: "contracts" if p.endswith(contracts) else "adapters"
                                                       for p in pages}, {})  # fmt: skip
            summary += f"; {frontend_summary}"
        iac, iac_summary = infrastructure.generate(design, ctx.run.target)
        if iac:
            await self.port.save_artifacts(iac, dict.fromkeys(iac, "orchestration"), {})
        if iac_summary:
            summary += f"; {iac_summary}"
        return PhaseResult(summary=summary)

    async def _tests(
        self, ctx: PhaseContext, pack: BackendPack, design: Design, use_case: UseCase, rules: dict[str, Rule],
        files: dict[str, str], criteria: str = "",
    ) -> str:  # fmt: skip
        async def work() -> Attempt:
            request = (f"Design:\n{design.model_dump_json(indent=1)}\n\nUse case: {use_case.name}\n\n"
                       f"Rules:\n{_rules_text([rules[r] for r in use_case.rules if r in rules])}\n\n"
                       f"Existing files:\n{pack.existing(files, design)}")  # fmt: skip
            if criteria:  # Flow 2: the approved acceptance criteria are the oracle too (ADR-0018)
                request += (
                    "\n\nAcceptance criteria of the user stories. Besides the tests of the rule scenarios, write one "
                    "test per criterion whose method name starts with the prefix given (for example "
                    "ac_US001_2_rejects_an_amount_below_the_minimum) and checks what the criterion says; when a "
                    "criterion is about a screen only, test the behaviour of the service behind it. Expected values "
                    "come only from the criteria and the rule scenarios: never compute a new expected amount yourself, "
                    f"and do not assert what no scenario states:\n{criteria}"
                )
            messages = [
                {"role": "system", "content": prompt(pack.tester_prompt)},
                {"role": "user", "content": request},
            ]
            reply = await self.port.models.complete(TESTER, "generation", messages)
            try:
                code = code_block(pack, reply.content)
            except ReplyError as exc:
                raise_if_cut(reply, f"Tests of {use_case.name}", exc, repeated=True, json_only=False)
                raise
            reference = await self.port.save_file(pack.test_path(design, use_case), code)
            return Attempt({"file": reference}, f"tests of {use_case.name}", reply.usage)

        attempt = await ctx.invoke(TESTER, work, what=f"Tests of {use_case.name} from the rule scenarios")
        return await self.port.load_file(attempt.artifact["file"])

    async def _service(
        self, ctx: PhaseContext, pack: BackendPack, design: Design, use_case: UseCase, rules: dict[str, Rule],
        files: dict[str, str], sandbox: Sandbox,
    ) -> str:  # fmt: skip
        base = [
            {"role": "system", "content": prompt(pack.developer_prompt)},
            {"role": "user", "content": (
                f"Write the application service of {use_case.name}.\n\nDesign:\n{design.model_dump_json(indent=1)}\n\n"
                f"Rules:\n{_rules_text([rules[r] for r in use_case.rules if r in rules])}\n\n"
                f"Existing files:\n{pack.existing(files, design)}\n\nThe tests it must pass:\n"
                f"{files[pack.test_path(design, use_case)]}"
                + (f"\n\n{stack_guidance(ctx.run.target)}" if guided_enabled(ctx.run.options) else ""))},
        ]  # fmt: skip
        target = pack.service_path(design, use_case)

        async def work(iteration: int, feedback: str | None) -> Attempt:
            messages = list(base)
            if feedback:
                messages.append({"role": "user", "content": f"The previous version failed:\n{feedback}\nFix it."})
            reply = await self.port.models.complete(DEVELOPER, "generation", messages, iteration=iteration)
            try:
                code = code_block(pack, reply.content)
            except ReplyError as exc:
                raise_if_cut(reply, f"{use_case.name}Service", exc, repeated=bool(feedback), json_only=False)
                raise
            return Attempt({"file": await self.port.save_file(target, code)}, f"{use_case.name}Service", reply.usage)

        async def verify(artifact: dict[str, Any]) -> Verification:
            candidate = dict(files)
            candidate[target] = await self.port.load_file(artifact["file"])
            candidate.update(pack.probe(design, target))
            build: BuildResult = await pack.compile_and_test(sandbox, candidate)
            if build.ok and build.passed:
                return Verification(True)
            if build.compiled and not build.tests:
                return Verification(False, "no test ran: the test class did not compile or was not found")
            return Verification(False, build.diagnostic())

        attempt = await ctx.do_verify_correct(DEVELOPER, work, verify, what=f"{use_case.name}Service")
        return await self.port.load_file(attempt.artifact["file"])

    async def _adapter(
        self, ctx: PhaseContext, pack: BackendPack, design: Design, port_name: str, files: dict[str, str],
        sandbox: Sandbox,
    ) -> str:  # fmt: skip
        port_spec = next(p for p in design.ports if p.name == port_name)
        target = pack.adapter_path(design, port_spec)
        adapter = pack.adapter_name(port_name)
        base = [
            {"role": "system", "content": prompt(pack.developer_prompt)},
            {"role": "user", "content": pack.adapter_request(design, port_name, files)},
        ]

        async def work(iteration: int, feedback: str | None) -> Attempt:
            messages = list(base)
            if feedback:
                messages.append({"role": "user", "content": f"The previous version failed:\n{feedback}\nFix it."})
            reply = await self.port.models.complete(DEVELOPER, "generation", messages, iteration=iteration)
            try:
                code = code_block(pack, reply.content)
            except ReplyError as exc:
                raise_if_cut(reply, str(adapter), exc, repeated=bool(feedback), json_only=False)
                raise
            return Attempt({"file": await self.port.save_file(target, code)}, adapter, reply.usage)

        async def verify(artifact: dict[str, Any]) -> Verification:
            candidate = dict(files)
            candidate[target] = await self.port.load_file(artifact["file"])
            candidate.update(pack.probe(design, target))
            build = await pack.compile_and_test(sandbox, candidate, run_tests=False)
            return Verification(build.compiled, build.compile_errors[:4000])

        attempt = await ctx.do_verify_correct(DEVELOPER, work, verify, what=f"Adapter {adapter}")
        return await self.port.load_file(attempt.artifact["file"])
