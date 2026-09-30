"""The scope of a golden master (spec 11.3): the code a characterized program exercises, i.e. its own file and the
files of the programs it calls and waits for (CALL, LINK). A transfer of control (XCTL) leaves the program: what
happens next belongs to another program and to its own golden master. Rules outside the scope are not required of
this golden master and are reported as not proven, never silently dropped."""

from collections.abc import Sequence
from pathlib import PurePosixPath

from nexti_core.adapters import Inventory, SourceFile
from nexti_core.spec.model import Rule

UNIT_LABELS = ("StoredProcedure", "Program")


def _short(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower()


def program_files(inventory: Inventory, program: str) -> set[str]:
    """The files of the program and of what it calls (not what it transfers to). Empty when the program is not in
    the inventory: then nothing can be scoped."""
    units = [n for n in inventory.nodes if n.label in UNIT_LABELS and n.file]
    start = next((n for n in units if _short(n.name) == _short(program)), None)
    if start is None or start.file is None:
        return set()
    files = {start.file}
    seen = {start.key}
    pending = [start.key]
    while pending:
        key = pending.pop()
        for edge in inventory.edges:
            if edge.source != key or edge.type != "CALLS" or edge.properties.get("kind") == "XCTL":
                continue
            if edge.target in seen:
                continue
            seen.add(edge.target)
            node = inventory.node(edge.target)
            if node is not None and node.file:
                files.add(node.file)
                pending.append(node.key)
    return files


def scope_files(files: list[SourceFile], program: str) -> set[str]:
    """The scope of `program` in these inputs (empty when no adapter recognises them)."""
    from nexti_orchestration.model import PhaseFailedError
    from nexti_orchestration.modernization import pick_adapter

    try:
        adapter = pick_adapter(files)
    except PhaseFailedError:
        return set()
    return program_files(adapter.inventory(files), program)


def split_rules(rules: Sequence[Rule], files: set[str]) -> tuple[list[Rule], list[Rule]]:
    """(inside, outside) the scope: a rule is inside when one of its citations is in the scope's files."""
    if not files:
        return list(rules), []
    names = {PurePosixPath(f).name.lower() for f in files}
    inside = [r for r in rules if any(PurePosixPath(s.file).name.lower() in names for s in r.sources)]
    outside = [r for r in rules if r not in inside]
    return inside, outside
