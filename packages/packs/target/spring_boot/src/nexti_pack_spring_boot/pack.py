"""The Java Spring Boot pack behind the common backend pack contract (ADR-0017): what the orchestration needs to
generate and verify a target without naming the language. The texts sent to the agents are exactly those of M4, so
its recordings stay valid."""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from nexti_core.spec.characterization import GoldenMaster, Scalar
from nexti_core.spec.equivalence import EquivalenceRun
from nexti_pack_spring_boot.build import IMAGE, compile_and_test
from nexti_pack_spring_boot.canary import Mutation, mutations
from nexti_pack_spring_boot.design import Design, Port, UseCase
from nexti_pack_spring_boot.equivalence import run_equivalence
from nexti_pack_spring_boot.generate import adapter_path, junit_path, layer_of, service_path, skeleton
from nexti_sandbox import Sandbox
from nexti_sandbox.build import BuildResult

SCHEMA = "src/main/resources/db/schema.sql"


class ReplyFormatError(ValueError):
    """The answer has no code block of the pack's language."""


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


class SpringBootPack:
    name = "spring-boot"
    image = IMAGE
    developer_prompt = "backend-dev"
    tester_prompt = "test-engineer"

    def skeleton(self, design: Design) -> dict[str, str]:
        files = skeleton(design)
        path, content = wiring(design)
        files[path] = content
        return files

    def held_back(self, path: str) -> bool:
        """The REST controllers and the wiring use the services, so they join once every service exists."""
        return path.endswith("Controller.java") or path.endswith("/config/Wiring.java")

    def code_block(self, content: str) -> str:
        match = re.search(r"```(?:java)?\s*\n(.*?)```", content, re.DOTALL)
        code = (match.group(1) if match else content).strip()
        if "class " not in code and "interface " not in code:
            raise ReplyFormatError("the answer has no Java class in a ```java block")
        return code + "\n"

    def service_path(self, design: Design, use_case: UseCase) -> str:
        return service_path(design, use_case)

    def test_path(self, design: Design, use_case: UseCase) -> str:
        return junit_path(design, use_case)

    def adapter_path(self, design: Design, port: Port) -> str:
        return adapter_path(design, port)

    def adapter_name(self, port: str) -> str:
        return f"Jdbc{port}"

    def layer_of(self, path: str, design: Design) -> str:
        return layer_of(path, design)

    def existing(self, files: Mapping[str, str], design: Design) -> str:
        """The files the agents see: the domain and the REST contracts."""
        wanted = [p for p in files if "/domain/" in p or ("/adapters/in/rest/" in p and p.endswith(("Request.java",
                  "Response.java")))]  # fmt: skip
        return "\n\n".join(f"// {p}\n{files[p]}" for p in sorted(wanted))

    def probe(self, design: Design, path: str) -> dict[str, str]:
        """Java names a class by its file: the path already pins the package and the name."""
        return {}

    def adapter_request(self, design: Design, port: str, files: Mapping[str, str]) -> str:
        return (
            f"Write the JDBC adapter Jdbc{port} of the port {port}.\n\n"
            f"Design:\n{design.model_dump_json(indent=1)}\n\nExisting files:\n{self.existing(files, design)}\n\n"
            f"Target schema:\n{files[SCHEMA]}"
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
        return {"name": self.name, "image": self.image}


PACK = SpringBootPack()
