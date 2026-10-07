"""The contract of a source adapter (spec 8.1, 8.2): each origin only knows how to reach the spec. An adapter
recognises its inputs, builds the code and data layers of the knowledge graph, maps its types to neutral types,
gives classification hints and slices, and says how to run the legacy for the golden master.

The worker drives adapters through this contract; the graph layer stores what `inventory` returns."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from nexti_core.spec.characterization import GoldenMaster, Suite

# Code and data layers (what adapters produce) and knowledge / target layers (spec 5.1).
NodeLabel = Literal[
    "StoredProcedure", "Program", "Paragraph", "Block", "Statement", "Table", "Column", "Field", "File",
    "Mapset", "BmsMap", "Transaction", "Copybook",
    "Rule", "Capability", "Contract", "Story", "TestCase", "Question", "Domain", "Screen",
    "Service", "Module", "Class", "Method", "Endpoint",
]  # fmt: skip
EdgeType = Literal[
    "CALLS", "READS", "WRITES", "CONTAINS", "DECLARES", "EXEC_SQL",
    "COPIES", "PERFORMS", "EXEC_CICS", "USES_MAP", "STARTS", "REDEFINES",
    "DERIVED_FROM", "BELONGS_TO", "VERIFIES", "COVERS", "DEPENDS_ON", "IMPLEMENTS", "MAPS_TO",
    "NEXT", "GOTO", "ON_ERROR",
]  # fmt: skip


@dataclass(frozen=True)
class Node:
    key: str  # stable within the project: "proc:dbo.sp_x", "table:db..t", "stmt:dbo.sp_x#12"
    label: NodeLabel
    name: str
    file: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    properties: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)


@dataclass(frozen=True)
class Edge:
    source: str
    type: EdgeType
    target: str
    properties: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)


@dataclass
class Inventory:
    adapter: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    metrics: dict[str, int] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)  # what could not be parsed or resolved, with file:line

    def node(self, key: str) -> Node | None:
        return next((n for n in self.nodes if n.key == key), None)


@dataclass(frozen=True)
class SourceFile:
    path: str  # relative to the workspace
    text: str


@dataclass(frozen=True)
class SliceView:
    """What an agent reads for one unit of work: exact line ranges of one file and the context around them."""

    unit: str
    file: str
    lines: tuple[tuple[int, int], ...]
    parameters: tuple[str, ...] = ()
    tables: tuple[str, ...] = ()


class SourceAdapter(Protocol):
    name: str

    def detect(self, files: list[SourceFile]) -> float:
        """Confidence in [0, 1] that the inputs are of this technology."""
        ...

    def inventory(self, files: list[SourceFile]) -> Inventory: ...

    def types(self, files: list[SourceFile]) -> dict[str, str]:
        """Source type (or, for record languages like COBOL, data item) -> neutral type text; unresolved types map
        to an empty string."""
        ...

    def slices(self, files: list[SourceFile]) -> list[SliceView]:
        """The units for rule extraction, each with its slice."""
        ...

    def classification(self, files: list[SourceFile]) -> dict[str, int]:
        """Statements (or paragraphs) by label: infrastructure, control_flow, business."""
        ...

    def data_of(
        self, files: list[SourceFile], file: str, ranges: list[tuple[int, int]]
    ) -> tuple[frozenset[str], frozenset[str]]:
        """Tables (or files) read and written by the code inside the line ranges."""
        ...

    def digest(self, files: list[SourceFile]) -> str:
        """The inventory in a few lines for the agents (entry points, their inputs, the data they use, the external
        programs they call, and how the legacy can be observed)."""
        ...


class LegacyUnavailableError(RuntimeError):
    """The legacy cannot be run now: its engine is missing or did not start, or a replay has no recording.
    `transient` says a new try may work (the engine did not start or answer in time, typically a busy host)."""

    transient: bool = False


class LegacyRunner(Protocol):
    """How to run the legacy for the golden master (8.2 `runner()`): each case in an isolated engine, observed
    through `nexti_core.spec.characterization`."""

    engine: str

    async def run(self, files: list[SourceFile], suite: "Suite") -> "GoldenMaster": ...
