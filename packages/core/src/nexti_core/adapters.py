"""The contract of a source adapter (spec 8.1, 8.2): each origin only knows how to reach the spec. An adapter
recognises its inputs, builds the code and data layers of the knowledge graph, maps its types to neutral types,
gives classification hints and slices, and says how to run the legacy for the golden master.

The worker drives adapters through this contract; the graph layer stores what `inventory` returns."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

NodeLabel = Literal["StoredProcedure", "Program", "Paragraph", "Statement", "Table", "Column", "Field", "File"]
EdgeType = Literal["CALLS", "READS", "WRITES", "CONTAINS", "DECLARES", "EXEC_SQL"]


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
        """Source type -> neutral type text; unresolved types map to an empty string."""
        ...

    def slices(self, files: list[SourceFile]) -> list[SliceView]:
        """The units for rule extraction, each with its slice."""
        ...
