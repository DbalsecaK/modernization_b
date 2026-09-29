"""The migration plan by waves (spec 7.7, D-25): suggested from the dependencies between user stories, changed by
people, and validated by code on every change.

- A story goes in the wave after the latest wave of the stories it depends on; inside a wave, by priority and then
  by size (smaller first).
- A story may share a wave with a dependency (they are built together), never go before it.
- Before a **hard** dependency the move is rejected with the reason; before a **soft** one it is allowed with a
  warning (an ACL or temporary stub is planned, 6.3).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

Strength = Literal["hard", "soft"]
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2}


@dataclass(frozen=True)
class Dependency:
    story: str  # depends on ...
    on: str
    strength: Strength
    reason: str = ""


@dataclass(frozen=True)
class StoryInfo:
    key: str
    priority: str = "P1"
    size: int = 1


@dataclass(frozen=True)
class PlanProblem:
    code: Literal["hard_dependency", "soft_dependency", "cycle", "unknown_story", "unplanned"]
    story: str
    on: str | None
    message: str

    @property
    def blocking(self) -> bool:
        return self.code != "soft_dependency"


@dataclass
class PlanCheck:
    problems: list[PlanProblem] = field(default_factory=list)

    @property
    def errors(self) -> list[PlanProblem]:
        return [p for p in self.problems if p.blocking]

    @property
    def warnings(self) -> list[PlanProblem]:
        return [p for p in self.problems if not p.blocking]

    @property
    def ok(self) -> bool:
        return not self.errors


def _cycle(stories: Iterable[str], edges: Iterable[tuple[str, str]]) -> list[str] | None:
    graph: dict[str, list[str]] = {s: [] for s in stories}
    for story, on in edges:
        if story in graph and on in graph:
            graph[story].append(on)
    state: dict[str, int] = {}
    path: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        path.append(node)
        for nxt in graph[node]:
            if state.get(nxt) == 1:
                return [*path[path.index(nxt) :], nxt]
            if nxt not in state and (found := visit(nxt)):
                return found
        path.pop()
        state[node] = 2
        return None

    for node in sorted(graph):
        if node not in state and (found := visit(node)):
            return found
    return None


def find_cycle(stories: Iterable[str], dependencies: Iterable[Dependency]) -> list[str] | None:
    """A cycle of hard dependencies (stories in order) or None: only hard dependencies constrain the plan."""
    return _cycle(stories, [(d.story, d.on) for d in dependencies if d.strength == "hard"])


def suggest(stories: Sequence[StoryInfo], dependencies: Iterable[Dependency]) -> list[list[str]]:
    """Waves (first wave first), each ordered by priority and then size. Soft dependencies also order the suggestion
    when they add no cycle (so it needs no stubs); a cycle of hard dependencies raises ValueError."""
    deps = list(dependencies)
    keys = [s.key for s in stories]
    if cycle := find_cycle(keys, deps):
        raise ValueError("dependency cycle: " + " -> ".join(cycle))
    edges = [(d.story, d.on) for d in deps]
    if _cycle(keys, edges):
        edges = [(d.story, d.on) for d in deps if d.strength == "hard"]
    requires: dict[str, set[str]] = {k: set() for k in keys}
    for story, on in edges:
        if story in requires and on in requires:
            requires[story].add(on)
    wave: dict[str, int] = {}

    def wave_of(key: str) -> int:
        if key not in wave:
            wave[key] = 1 + max((wave_of(r) for r in requires[key]), default=0)
        return wave[key]

    for key in keys:
        wave_of(key)
    info = {s.key: s for s in stories}
    waves: list[list[str]] = [[] for _ in range(max(wave.values(), default=0))]
    for key, number in wave.items():
        waves[number - 1].append(key)
    for group in waves:
        group.sort(key=lambda k: (PRIORITY_ORDER.get(info[k].priority, 9), info[k].size, k))
    return waves


def validate(waves: Sequence[Sequence[str]], dependencies: Iterable[Dependency], stories: Iterable[str]) -> PlanCheck:
    """Check a plan made or changed by people. Every story must be planned exactly once."""
    check = PlanCheck()
    position: dict[str, int] = {}
    for index, group in enumerate(waves):
        for key in group:
            position[key] = index
    all_stories = set(stories)
    for key in position:
        if key not in all_stories:
            check.problems.append(PlanProblem("unknown_story", key, None, f"{key} is not a story of the project"))
    for key in sorted(all_stories - set(position)):
        check.problems.append(PlanProblem("unplanned", key, None, f"{key} is not in any wave"))
    deps = list(dependencies)
    if cycle := find_cycle(all_stories, deps):
        check.problems.append(PlanProblem("cycle", cycle[0], cycle[1], "dependency cycle: " + " -> ".join(cycle)))
    for d in deps:
        if d.story not in position or d.on not in position:
            continue
        if position[d.story] < position[d.on]:
            why = f" ({d.reason})" if d.reason else ""
            if d.strength == "hard":
                message = f"{d.story} cannot go before {d.on}, a hard dependency{why}"
                check.problems.append(PlanProblem("hard_dependency", d.story, d.on, message))
            else:
                message = f"{d.story} goes before {d.on}, a soft dependency{why}: plan an ACL or a temporary stub"
                check.problems.append(PlanProblem("soft_dependency", d.story, d.on, message))
    return check
