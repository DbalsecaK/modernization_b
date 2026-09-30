"""Design (C3) and generation by layers (spec 6.1 phases 8 and 10) with the Java Spring Boot pack.

- Design: the solution architect proposes the design from the approved rules and the inventory; code validates it
  (structure, neutral types, references, every rule in a use case) and sends the problems back.
- Generation: the pack writes the skeleton; per use case the test engineer writes the tests from the rule scenarios
  first (the oracle), then the backend developer writes the service until those tests pass in the Java sandbox
  (do -> verify -> correct, 11.1); then the adapters, which must compile; the wiring is generated. Each layer
  compiles before the next. The generated files go to the object store; only references stay in the graph state.

A project whose backend has no pack yet waits in generation (ADR-0010): it never generates another language.
"""

import json
import re
from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import ValidationError

from nexti_agents import prompt
from nexti_core.adapters import SourceFile
from nexti_core.spec.model import Rule
from nexti_orchestration.context import Attempt, PhaseContext, Verification
from nexti_orchestration.extraction import ModelCaller, ReplyError, parse_json
from nexti_orchestration.model import PhaseFailedError, PhaseResult, PhaseUnavailableError
from nexti_orchestration.store import Usage
from nexti_orchestration.usage import total as _total
from nexti_pack_spring_boot import (
    IMAGE,
    NAME,
    BuildResult,
    Design,
    UseCase,
    adapter_path,
    compile_and_test,
    junit_path,
    layer_of,
    service_path,
    skeleton,
)
from nexti_sandbox import Sandbox

ARCHITECT = "solution-architect"
DEVELOPER = "backend-dev"
TESTER = "test-engineer"
PACKS = {NAME: IMAGE}


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


def java_block(content: str) -> str:
    match = re.search(r"```(?:java)?\s*\n(.*?)```", content, re.DOTALL)
    code = (match.group(1) if match else content).strip()
    if "class " not in code and "interface " not in code:
        raise ReplyError("the answer has no Java class in a ```java block")
    return code + "\n"


_NAME = re.compile(r"[@#]?[A-Za-z_][A-Za-z0-9_$#@]*")


def legacy_names(files: Sequence[SourceFile]) -> set[str]:
    """Every identifier of the legacy source, lowercase: what the design may name as legacy."""
    return {m.group(0).lower() for f in files for m in _NAME.finditer(f.text)}


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
        if name and name.rsplit(".", 1)[-1].lower() not in names:
            missing.append(name)
    return sorted(set(missing))


def design_problems(design: Design, rules: Sequence[Rule], names: set[str] | None = None) -> list[str]:
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
    return problems


def _rules_text(rules: Sequence[Rule]) -> str:
    return json.dumps(
        [r.model_dump(mode="json", include={"id", "name", "category", "priority", "statement", "condition", "action",
                                            "inputs", "outputs", "scenarios", "sources"}) for r in rules],
        ensure_ascii=False, indent=1,
    )  # fmt: skip


async def propose_design(
    caller: ModelCaller, rules: Sequence[Rule], inventory: str, *, max_iterations: int = 3,
    names: set[str] | None = None, source: str = "",
) -> tuple[Design, list[Usage]]:  # fmt: skip
    messages = [
        {"role": "system", "content": prompt(ARCHITECT)},
        {
            "role": "user",
            "content": f"Inventory:\n{inventory}\n\nApproved rules:\n{_rules_text(rules)}"
            + (f"\n\nLegacy source (the columns and parameters to map):\n{source}" if source else ""),
        },
    ]
    usage: list[Usage] = []
    last = ""
    for iteration in range(1, max_iterations + 1):
        reply = await caller.complete(ARCHITECT, "design", messages, iteration=iteration)
        usage.append(reply.usage)
        try:
            data = parse_json(reply.content)
            design = Design.model_validate(data)
            problems = design_problems(design, rules, names)
            if problems:
                raise ReplyError("\n".join(problems))
            return design, usage
        except (ReplyError, ValidationError) as exc:
            detail = str(exc) if isinstance(exc, ReplyError) else "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:10])  # fmt: skip
            last = detail
            messages += [
                {"role": "assistant", "content": reply.content},
                {"role": "user", "content": f"The design has these problems; fix them and answer again:\n{detail}"},
            ]
    raise ReplyError(f"no valid design after {max_iterations} attempts: {last}")


def wiring(design: Design) -> tuple[str, str]:
    """The orchestration layer: one bean per use case service, built from the port beans (the adapters)."""
    package = f"{design.base_package}.config"
    beans = []
    for use_case in design.use_cases:
        params = ", ".join(f"{design.base_package}.domain.port.{p} {p[:1].lower() + p[1:]}" for p in use_case.ports)
        args = ", ".join(p[:1].lower() + p[1:] for p in use_case.ports)
        service = f"{design.base_package}.application.{use_case.name}Service"
        name = use_case.name[:1].lower() + use_case.name[1:] + "Service"
        beans.append(
            f"    @Bean\n    public {service} {name}({params}) {{\n        return new {service}({args});\n    }}"
        )
    path = f"src/main/java/{package.replace('.', '/')}/Wiring.java"
    body = "\n\n".join(beans)
    return path, (
        f"package {package};\n\nimport org.springframework.context.annotation.Bean;\n"
        "import org.springframework.context.annotation.Configuration;\n\n"
        "/** The application services as beans (the domain classes have no framework annotations). */\n"
        f"@Configuration\npublic class Wiring {{\n\n{body}\n}}\n"
    )


def _existing(files: dict[str, str], design: Design) -> str:
    wanted = [p for p in files if "/domain/" in p or ("/adapters/in/rest/" in p and p.endswith(("Request.java",
              "Response.java")))]  # fmt: skip
    return "\n\n".join(f"// {p}\n{files[p]}" for p in sorted(wanted))


class GenerationPhases:
    def __init__(self, port: GenerationPort) -> None:
        self.port = port

    async def design(self, ctx: PhaseContext) -> PhaseResult:
        rules = await self.port.load_rules()
        if not rules:
            raise PhaseFailedError("There are no approved rules to design from")

        async def work() -> Attempt:
            try:
                files = await self.port.source_files()
                design, usage = await propose_design(
                    self.port.models, rules, await self.port.inventory_digest(),
                    max_iterations=ctx.run.max_iterations, names=legacy_names(files),
                    source="\n\n".join(f"// {f.path}\n{f.text}" for f in files),
                )  # fmt: skip
            except ReplyError as exc:
                raise PhaseFailedError(str(exc)[:1500]) from exc
            await self.port.save_design(design)
            summary = (f"{len(design.use_cases)} use case(s), {len(design.entities)} entities, "
                       f"{len(design.ports)} ports, {len(design.decisions)} decisions")  # fmt: skip
            return Attempt({"context": design.context}, summary, _total(usage))

        attempt = await ctx.invoke(ARCHITECT, work, what="Target design")
        return PhaseResult(summary=attempt.summary)

    async def generation(self, ctx: PhaseContext) -> PhaseResult:
        backend = ctx.run.target.get("backend")
        if backend and backend not in PACKS:
            raise PhaseUnavailableError(f"The {backend} pack is not available yet: generation waits for it")
        design = await self.port.load_design()
        if design is None:
            raise PhaseFailedError("There is no approved design to generate from")
        rules = {r.id: r for r in await self.port.load_rules()}
        sandbox = self.port.sandbox(PACKS[NAME])
        files = skeleton(design)
        path, content = wiring(design)
        files[path] = content
        # The REST controllers and the wiring use the services, so they join once every service exists.
        held = {p: files.pop(p) for p in list(files) if p.endswith("Controller.java") or p == path}
        build = await compile_and_test(sandbox, files, run_tests=False)
        if not build.compiled:
            raise PhaseFailedError(f"The generated skeleton does not compile: {build.compile_errors[:1500]}")
        await ctx.store.event("info", "succeeded", "Layers contracts and domain model compile", phase=ctx.phase.key)
        tests_run = 0
        for use_case in design.use_cases:
            # One shard per piece: its invocations and journal entries never mix with another piece's.
            piece = ctx.for_shard(f"use-case:{use_case.name}")
            files[junit_path(design, use_case)] = await self._tests(piece, design, use_case, rules, files)
            files[service_path(design, use_case)] = await self._service(piece, design, use_case, rules, files, sandbox)
        files.update(held)
        for port_spec in design.ports:
            piece = ctx.for_shard(f"adapter:{port_spec.name}")
            files[adapter_path(design, port_spec)] = await self._adapter(piece, design, port_spec.name, files, sandbox)
        final = await compile_and_test(sandbox, files)
        if not final.ok:
            raise PhaseFailedError(f"The complete project does not pass: {final.diagnostic(1500)}")
        tests_run = final.passed
        layers = {p: layer_of(p, design) for p in files}
        traced = {service_path(design, u): u.rules for u in design.use_cases}
        traced.update({junit_path(design, u): u.rules for u in design.use_cases})
        await self.port.save_artifacts(files, layers, traced)
        return PhaseResult(summary=f"{len(files)} files in {len(set(layers.values()))} layers; "
                                   f"{tests_run} tests pass in the sandbox")  # fmt: skip

    async def _tests(
        self, ctx: PhaseContext, design: Design, use_case: UseCase, rules: dict[str, Rule], files: dict[str, str]
    ) -> str:
        async def work() -> Attempt:
            messages = [
                {"role": "system", "content": prompt(TESTER)},
                {"role": "user", "content": (
                    f"Design:\n{design.model_dump_json(indent=1)}\n\nUse case: {use_case.name}\n\n"
                    f"Rules:\n{_rules_text([rules[r] for r in use_case.rules if r in rules])}\n\n"
                    f"Existing files:\n{_existing(files, design)}")},
            ]  # fmt: skip
            reply = await self.port.models.complete(TESTER, "generation", messages)
            code = java_block(reply.content)
            reference = await self.port.save_file(junit_path(design, use_case), code)
            return Attempt({"file": reference}, f"tests of {use_case.name}", reply.usage)

        attempt = await ctx.invoke(TESTER, work, what=f"Tests of {use_case.name} from the rule scenarios")
        return await self.port.load_file(attempt.artifact["file"])

    async def _service(
        self, ctx: PhaseContext, design: Design, use_case: UseCase, rules: dict[str, Rule], files: dict[str, str],
        sandbox: Sandbox,
    ) -> str:  # fmt: skip
        base = [
            {"role": "system", "content": prompt(DEVELOPER)},
            {"role": "user", "content": (
                f"Write the application service of {use_case.name}.\n\nDesign:\n{design.model_dump_json(indent=1)}\n\n"
                f"Rules:\n{_rules_text([rules[r] for r in use_case.rules if r in rules])}\n\n"
                f"Existing files:\n{_existing(files, design)}\n\nThe tests it must pass:\n"
                f"{files[junit_path(design, use_case)]}")},
        ]  # fmt: skip
        target = service_path(design, use_case)

        async def work(iteration: int, feedback: str | None) -> Attempt:
            messages = list(base)
            if feedback:
                messages.append({"role": "user", "content": f"The previous version failed:\n{feedback}\nFix it."})
            reply = await self.port.models.complete(DEVELOPER, "generation", messages, iteration=iteration)
            code = java_block(reply.content)
            return Attempt({"file": await self.port.save_file(target, code)}, f"{use_case.name}Service", reply.usage)

        async def verify(artifact: dict[str, Any]) -> Verification:
            candidate = dict(files)
            candidate[target] = await self.port.load_file(artifact["file"])
            build: BuildResult = await compile_and_test(sandbox, candidate)
            if build.ok and build.passed:
                return Verification(True)
            if build.compiled and not build.tests:
                return Verification(False, "no test ran: the test class did not compile or was not found")
            return Verification(False, build.diagnostic())

        attempt = await ctx.do_verify_correct(DEVELOPER, work, verify, what=f"{use_case.name}Service")
        return await self.port.load_file(attempt.artifact["file"])

    async def _adapter(
        self, ctx: PhaseContext, design: Design, port_name: str, files: dict[str, str], sandbox: Sandbox
    ) -> str:
        port_spec = next(p for p in design.ports if p.name == port_name)
        target = adapter_path(design, port_spec)
        base = [
            {"role": "system", "content": prompt(DEVELOPER)},
            {"role": "user", "content": (
                f"Write the JDBC adapter Jdbc{port_name} of the port {port_name}.\n\n"
                f"Design:\n{design.model_dump_json(indent=1)}\n\nExisting files:\n{_existing(files, design)}\n\n"
                f"Target schema:\n{files['src/main/resources/db/schema.sql']}")},
        ]  # fmt: skip

        async def work(iteration: int, feedback: str | None) -> Attempt:
            messages = list(base)
            if feedback:
                messages.append({"role": "user", "content": f"The previous version failed:\n{feedback}\nFix it."})
            reply = await self.port.models.complete(DEVELOPER, "generation", messages, iteration=iteration)
            code = java_block(reply.content)
            return Attempt({"file": await self.port.save_file(target, code)}, f"Jdbc{port_name}", reply.usage)

        async def verify(artifact: dict[str, Any]) -> Verification:
            candidate = dict(files)
            candidate[target] = await self.port.load_file(artifact["file"])
            build = await compile_and_test(sandbox, candidate, run_tests=False)
            return Verification(build.compiled, build.compile_errors[:4000])

        attempt = await ctx.do_verify_correct(DEVELOPER, work, verify, what=f"Adapter Jdbc{port_name}")
        return await self.port.load_file(attempt.artifact["file"])
