"""The order in which the programs of a legacy are migrated (ADR-0055, point 12): from the leaves of the call graph
upwards, so that when a program is characterized the programs it calls are already real on the target (or stay in
the legacy as substitutes), and the characterization runs in batches, one level at a time. Programs that call
each other (a cycle) form one group and go in the same level."""

from collections.abc import Iterable
from dataclasses import dataclass

from nexti_core.adapters import Inventory

PROGRAM_LABELS = ("Program", "StoredProcedure")


@dataclass(frozen=True)
class Level:
    """One batch of the migration: programs whose callees are all in earlier levels (or external to the legacy)."""

    number: int
    programs: tuple[str, ...]
    external: tuple[str, ...] = ()  # programs the inputs do not contain: they stay where they are (substitutes)
    groups: tuple[tuple[str, ...], ...] = ()  # programs that call each other, migrated together


def migration_order(inventory: Inventory) -> list[Level]:
    """The levels of the call graph, leaves first. External programs (the inputs have no code for them) are the
    leaves of level 0 and are named apart: on a live customer system they run for real, on the platform's engine
    they are transactional substitutes."""
    nodes = {n.key: n for n in inventory.nodes if n.label in PROGRAM_LABELS}
    calls: dict[str, set[str]] = {key: set() for key in nodes}
    for edge in inventory.edges:
        if edge.type == "CALLS" and edge.source in nodes and edge.target in nodes and edge.source != edge.target:
            calls[edge.source].add(edge.target)
    components = _strongly_connected(calls)
    component_of = {key: index for index, component in enumerate(components) for key in component}
    depth: dict[int, int] = {}

    def level_of(index: int) -> int:
        if index in depth:
            return depth[index]
        depth[index] = 0  # guards the recursion; the condensation has no cycles
        callees = {component_of[t] for key in components[index] for t in calls[key]} - {index}
        depth[index] = 1 + max((level_of(c) for c in callees), default=-1)
        return depth[index]

    for index in range(len(components)):
        level_of(index)
    levels: list[Level] = []
    for number in range(max(depth.values(), default=-1) + 1):
        members = [components[i] for i in range(len(components)) if depth[i] == number]
        names = sorted(nodes[key].name for component in members for key in component)
        external = sorted(nodes[key].name for component in members for key in component
                          if nodes[key].properties.get("external"))  # fmt: skip
        groups = tuple(tuple(sorted(nodes[key].name for key in component)) for component in members
                       if len(component) > 1)  # fmt: skip
        levels.append(Level(number, tuple(names), tuple(external), tuple(sorted(groups))))
    return levels


def _strongly_connected(calls: dict[str, set[str]]) -> list[tuple[str, ...]]:
    """Tarjan's components, iteratively (a legacy may have thousands of programs)."""
    index = 0
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []
    for root in calls:
        if root in indices:
            continue
        work: list[tuple[str, Iterable[str]]] = [(root, iter(sorted(calls[root])))]
        indices[root] = low[root] = index
        index += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, callees = work[-1]
            advanced = False
            for callee in callees:
                if callee not in indices:
                    indices[callee] = low[callee] = index
                    index += 1
                    stack.append(callee)
                    on_stack.add(callee)
                    work.append((callee, iter(sorted(calls[callee]))))
                    advanced = True
                    break
                if callee in on_stack:
                    low[node] = min(low[node], indices[callee])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == indices[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(tuple(sorted(component)))
    return components


def order_text(levels: list[Level]) -> str:
    """The order in words, for the digest the agents and the people read."""
    if not levels:
        return ""
    lines = ["Migration order (leaves of the call graph first; a level is one batch of characterization):"]
    for level in levels:
        own = [p for p in level.programs if p not in level.external]
        parts = []
        if own:
            parts.append(", ".join(own))
        if level.external:
            parts.append("external, stay where they are or run as substitutes: " + ", ".join(level.external))
        text = f"- level {level.number}: " + "; ".join(parts)
        if level.groups:
            text += (
                " (migrated together, they call each other: "
                + "; ".join(" <-> ".join(group) for group in level.groups)
                + ")"
            )
        lines.append(text)
    return "\n".join(lines)
