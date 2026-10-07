"""The .NET 10 pack behind the common backend pack contract (ADR-0017)."""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from nexti_core.spec.characterization import GoldenMaster, Scalar
from nexti_core.spec.design import Design, Port, UseCase
from nexti_core.spec.equivalence import EquivalenceRun
from nexti_pack_dotnet import oracle
from nexti_pack_dotnet.build import IMAGE, compile_and_test
from nexti_pack_dotnet.canary import Mutation, mutations
from nexti_pack_dotnet.equivalence import run_equivalence
from nexti_pack_dotnet.generate import (
    APP,
    SCHEMA,
    adapter_name,
    adapter_path,
    layer_of,
    namespace,
    placeholder_service,
    service_path,
    skeleton,
    test_path,
)
from nexti_sandbox import Sandbox
from nexti_sandbox.build import BuildResult


class DotnetPack:
    name = "dotnet-10"
    image = IMAGE
    developer_prompt = "backend-dev-dotnet"
    tester_prompt = "test-engineer-dotnet"

    def configured(self, target: Mapping[str, Any]) -> "DotnetPack":
        """The pack has one version per image (ADR-0040): the target changes nothing."""
        return self

    def skeleton(self, design: Design) -> dict[str, str]:
        return skeleton(design)

    def held_back(self, path: str) -> bool:
        """The controllers, the wiring and the host use the services and adapters: they join once those exist."""
        return path.endswith("Controller.cs") or path in (f"{APP}/Wiring.cs", f"{APP}/Program.cs")

    def code_block(self, content: str) -> str:
        match = re.search(r"```(?:csharp|cs|c#)?\s*\n(.*?)```", content, re.DOTALL | re.IGNORECASE)
        code = (match.group(1) if match else content).strip()
        if not re.search(r"\b(class|record|interface)\s+\w+", code):
            raise ValueError("the answer has no C# class in a ```csharp block")
        return code + "\n"

    def service_path(self, design: Design, use_case: UseCase) -> str:
        return service_path(design, use_case)

    def test_path(self, design: Design, use_case: UseCase) -> str:
        return test_path(design, use_case)

    async def probe_sql(self, sandbox: Sandbox, files: Mapping[str, str], path: str) -> str:
        """The SQL of a generated adapter resolved against the schema before it is accepted (P32, step 12)."""
        from nexti_pack_dotnet.sqlprobe import probe_sql

        return await probe_sql(sandbox, files, path)

    def placeholder_service(self, design: Design, use_case: UseCase) -> dict[str, str]:
        """The service the tests compile against before the real one exists (P31, step 12)."""
        path, text = placeholder_service(design, use_case)
        return {path: text}

    def adapter_path(self, design: Design, port: Port) -> str:
        return adapter_path(design, port)

    def adapter_name(self, port: str) -> str:
        return adapter_name(port)

    def layer_of(self, path: str, design: Design) -> str:
        return layer_of(path, design)

    def existing(self, files: Mapping[str, str], design: Design) -> str:
        """The files the agents see: the domain, the REST contracts and the database session."""
        wanted = [
            p for p in files if "/Domain/" in p or p.endswith(("Request.cs", "Response.cs", "/Infrastructure/Db.cs"))
        ]
        return "\n\n".join(f"// {p}\n{files[p]}" for p in sorted(wanted))

    def probe(self, design: Design, path: str) -> dict[str, str]:
        """C# does not tie a class to its file: a probe names the service or adapter as the wiring and the
        controllers will, so a wrong namespace or class is a compiler error the agent sees."""
        ns = namespace(design)
        named = {service_path(design, u): f"{ns}.Application.{u.name}Service" for u in design.use_cases}
        named |= {adapter_path(design, p): f"{ns}.Adapters.Out.Sql.{adapter_name(p.name)}" for p in design.ports}
        if path not in named:
            return {}
        probe = (
            f"internal static class Probe\n{{\n    internal static readonly Type Named = typeof({named[path]});\n}}\n"
        )
        return {f"{APP}/Probe.cs": probe}

    def adapter_request(self, design: Design, port: str, files: Mapping[str, str]) -> str:
        return (
            f"Write the ADO.NET adapter {adapter_name(port)} of the port {port}: the class "
            f"`{namespace(design)}.Adapters.Out.Sql.{adapter_name(port)}`, in exactly that namespace (the wiring "
            "uses it).\n\n"
            f"Design:\n{design.model_dump_json(indent=1)}\n\nExisting files:\n{self.existing(files, design)}\n\n"
            f"Target schema (SQL Server):\n{files[SCHEMA]}"
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


class DotnetOraclePack(DotnetPack):
    """The same pack with Oracle as its persistence (ADR-0031): the Oracle schema, the ODP.NET client in the project,
    the adapters asked for Oracle SQL and the golden master run against Oracle in its sandbox."""

    async def probe_sql(self, sandbox: Sandbox, files: Mapping[str, str], path: str) -> str:
        from nexti_pack_dotnet.sqlprobe import probe_oracle

        return await probe_oracle(sandbox, files, path)  # EXPLAIN PLAN in its sandbox (P32, step 12)

    image = oracle.IMAGE
    database = "oracle"

    def skeleton(self, design: Design) -> dict[str, str]:
        return oracle.skeleton(design)

    def adapter_request(self, design: Design, port: str, files: Mapping[str, str]) -> str:
        return (
            f"Write the ADO.NET adapter {adapter_name(port)} of the port {port}: the class "
            f"`{namespace(design)}.Adapters.Out.Sql.{adapter_name(port)}`, in exactly that namespace (the wiring "
            "uses it). The database is Oracle Database 23ai through Oracle.ManagedDataAccess.Client (ODP.NET): "
            "use Oracle SQL (no TOP or LIMIT: FETCH FIRST n ROWS ONLY; booleans are BOOLEAN) and bind parameters as "
            ':name with `command.Parameters.Add(new OracleParameter("name", value))` (the session\'s commands bind '
            "by name; never a reserved word such as :number as a parameter name). Write the identifiers exactly as "
            'the schema does: a column the schema quotes (a reserved word, e.g. "NUMBER") is quoted the same way in '
            "every statement.\n\n"
            f"Design:\n{design.model_dump_json(indent=1)}\n\nExisting files:\n{self.existing(files, design)}\n\n"
            f"Target schema (Oracle):\n{files[SCHEMA]}"
        )

    async def run_equivalence(
        self, sandbox: Sandbox, files: dict[str, str], design: Design, use_case: UseCase, master: GoldenMaster,
        defaults: dict[str, Scalar] | None = None,
    ) -> EquivalenceRun:  # fmt: skip
        return await oracle.run_equivalence(sandbox, files, design, use_case, master, defaults)


PACK = DotnetPack()
ORACLE_PACK = DotnetOraclePack()
