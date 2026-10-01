"""The backend packs the orchestration can generate and verify with (ADR-0017), chosen by `target.backend`. A pack
implements this contract; the orchestration never names a language. A backend without a pack waits (ADR-0010)."""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from nexti_core.spec.characterization import GoldenMaster, Scalar
from nexti_core.spec.design import Design, Port, UseCase
from nexti_core.spec.equivalence import EquivalenceRun
from nexti_pack_dotnet.pack import PACK as DOTNET
from nexti_pack_spring_boot.pack import PACK as SPRING_BOOT
from nexti_sandbox import Sandbox
from nexti_sandbox.build import BuildResult

DEFAULT = SPRING_BOOT.name


class Mutation(Protocol):
    line: int
    before: str
    after: str
    source: str


class BackendPack(Protocol):
    name: str
    image: str
    developer_prompt: str
    tester_prompt: str

    def skeleton(self, design: Design) -> dict[str, str]:
        """The deterministic files: contracts, domain, REST adapters, schema, build files and the wiring."""
        ...

    def held_back(self, path: str) -> bool:
        """Files that use the services (controllers, wiring): they join once every service exists."""
        ...

    def code_block(self, content: str) -> str:
        """The code of an agent's answer; raises ValueError when there is none in the pack's language."""
        ...

    def service_path(self, design: Design, use_case: UseCase) -> str: ...

    def test_path(self, design: Design, use_case: UseCase) -> str: ...

    def adapter_path(self, design: Design, port: Port) -> str: ...

    def adapter_name(self, port: str) -> str: ...

    def layer_of(self, path: str, design: Design) -> str: ...

    def existing(self, files: Mapping[str, str], design: Design) -> str:
        """The files the agents see as context."""
        ...

    def probe(self, design: Design, path: str) -> dict[str, str]:
        """Files compiled with a piece under verification that name it as the rest of the project will (its
        namespace and class), so a wrong name is a compiler error the agent sees; empty when nothing needs it."""
        ...

    def adapter_request(self, design: Design, port: str, files: Mapping[str, str]) -> str:
        """What the developer is asked for to write the adapter of a port."""
        ...

    async def compile_and_test(
        self, sandbox: Sandbox, files: Mapping[str, str], *, run_tests: bool = True
    ) -> BuildResult: ...

    async def run_equivalence(
        self, sandbox: Sandbox, files: dict[str, str], design: Design, use_case: UseCase, master: GoldenMaster,
        defaults: dict[str, Scalar] | None = None,
    ) -> EquivalenceRun: ...  # fmt: skip

    def mutations(self, source: str) -> Sequence[Any]: ...


PACKS: dict[str, BackendPack] = {SPRING_BOOT.name: SPRING_BOOT, DOTNET.name: DOTNET}


def backend_pack(target: Mapping[str, Any]) -> BackendPack | None:
    """The pack of a project's backend (Spring Boot when none is chosen); None when that backend has no pack yet."""
    return PACKS.get(str(target.get("backend") or DEFAULT))
