"""The Go pack behind the common backend pack contract (ADR-0017, ADR-0029)."""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from nexti_core.spec.characterization import GoldenMaster, Scalar
from nexti_core.spec.design import Design, Port, UseCase
from nexti_core.spec.equivalence import EquivalenceRun
from nexti_pack_go.build import IMAGE, compile_and_test
from nexti_pack_go.canary import Mutation, mutations
from nexti_pack_go.equivalence import run_equivalence
from nexti_pack_go.generate import (
    APP,
    DOMAIN,
    HTTP,
    PG,
    PORTS,
    SCHEMA,
    SERVER,
    adapter_name,
    adapter_path,
    constructor,
    layer_of,
    module_path,
    probe_file,
    service_path,
    skeleton,
    test_path,
)
from nexti_sandbox import Sandbox
from nexti_sandbox.build import BuildResult

NAME = "go"


class GoPack:
    name = NAME
    image = IMAGE
    database = "postgresql"
    developer_prompt = "backend-dev-go"
    tester_prompt = "test-engineer-go"

    def configured(self, target: Mapping[str, Any]) -> "GoPack":
        """The pack has one version per image (ADR-0040): the target changes nothing."""
        return self

    def skeleton(self, design: Design) -> dict[str, str]:
        return skeleton(design)

    def held_back(self, path: str) -> bool:
        """The handlers and the wiring use the services and the adapters: they join once those exist."""
        return path == SERVER or (path.startswith(f"{HTTP}/") and path.endswith("_handler.go"))

    def code_block(self, content: str) -> str:
        match = re.search(r"```(?:go|golang)?\s*\n(.*?)```", content, re.DOTALL | re.IGNORECASE)
        code = (match.group(1) if match else content).strip()
        if not re.search(r"^package\s+\w+", code, re.MULTILINE):
            raise ValueError("the answer has no Go file (a package clause) in a ```go block")
        return code + "\n"

    def service_path(self, design: Design, use_case: UseCase) -> str:
        return service_path(design, use_case)

    def test_path(self, design: Design, use_case: UseCase) -> str:
        return test_path(design, use_case)

    def adapter_path(self, design: Design, port: Port) -> str:
        return adapter_path(design, port)

    def adapter_name(self, port: str) -> str:
        return adapter_name(port)

    def layer_of(self, path: str, design: Design) -> str:
        return layer_of(path, design)

    def existing(self, files: Mapping[str, str], design: Design) -> str:
        """The files the agents see: the module (its path is the import prefix), the domain, the ports, the
        contracts and the database session."""
        wanted = [
            p for p in files
            if p == "go.mod" or p.startswith((f"{DOMAIN}/", f"{PORTS}/")) or p == f"{PG}/db.go"
            or (p.startswith(f"{APP}/") and p.endswith("_contract.go"))
        ]  # fmt: skip
        return "\n\n".join(f"// {p}\n{files[p]}" for p in sorted(wanted))

    def probe(self, design: Design, path: str) -> dict[str, str]:
        """Go ties a type to its package, not to its file: a probe package names the service or the adapter as the
        wiring and the harness will (constructor and signatures), so a wrong name is a compiler error."""
        return probe_file(design, path)

    def adapter_request(self, design: Design, port: str, files: Mapping[str, str]) -> str:
        name = adapter_name(port)
        return (
            f"Write the PostgreSQL adapter of the port {port}: the type `{name}` in the package `pg` "
            f"(`{module_path(design)}/{PG}`, file {PG}/), with the constructor `func {constructor(name)}(db *DB) "
            f"*{name}` (the wiring and the harness call exactly that) and pointer receivers implementing "
            f"`ports.{port}`.\n\n"
            f"Design:\n{design.model_dump_json(indent=1)}\n\nExisting files:\n{self.existing(files, design)}\n\n"
            f"Target schema (PostgreSQL):\n{files[SCHEMA]}"
        )

    async def compile_and_test(
        self, sandbox: Sandbox, files: Mapping[str, str], *, run_tests: bool = True
    ) -> BuildResult:
        return await compile_and_test(sandbox, files, run_tests=run_tests)

    async def run_equivalence(
        self, sandbox: Sandbox, files: dict[str, str], design: Design, use_case: UseCase, master: GoldenMaster,
        defaults: dict[str, Scalar] | None = None,
    ) -> EquivalenceRun:  # fmt: skip
        return await run_equivalence(sandbox, files, design, use_case, master, defaults)

    def mutations(self, source: str) -> Sequence[Mutation]:
        return mutations(source)

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "image": self.image, "database": self.database}


PACK = GoPack()
