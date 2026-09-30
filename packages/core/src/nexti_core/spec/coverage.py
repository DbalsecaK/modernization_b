"""Coverage of the spec by user stories (spec 7.7), deterministic: every rule, screen and contract must be in at least
one active story; what is not is a gap. Stories without traceability and out-of-scope elements are listed apart."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

StoryStatus = Literal["draft", "review", "question", "approved", "discarded", "merged"]
ACTIVE: tuple[StoryStatus, ...] = ("draft", "review", "question", "approved")


@dataclass(frozen=True)
class StoryLinks:
    key: str
    status: StoryStatus
    elements: frozenset[str]  # RULE-…, SCR-…, CON-… and legacy component ids
    out_of_scope: bool = False  # discarded as "out of scope": its elements migrate as they are, without a story


@dataclass
class Coverage:
    covered: dict[str, list[str]] = field(default_factory=dict)  # element -> active stories
    gaps: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    untraced_stories: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.gaps


def compute(elements: Iterable[str], stories: Iterable[StoryLinks]) -> Coverage:
    wanted = sorted(set(elements))
    result = Coverage()
    story_list = list(stories)
    scoped_out = {e for s in story_list if s.status == "discarded" and s.out_of_scope for e in s.elements}
    for story in story_list:
        if story.status in ACTIVE and not story.elements:
            result.untraced_stories.append(story.key)
    for element in wanted:
        holders = [s.key for s in story_list if s.status in ACTIVE and element in s.elements]
        if holders:
            result.covered[element] = holders
        elif element in scoped_out:
            result.out_of_scope.append(element)
        else:
            result.gaps.append(element)
    result.untraced_stories.sort()
    return result
