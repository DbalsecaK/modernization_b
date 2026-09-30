"""The migration plan by waves (spec 7.7): suggested from dependencies, validated by code on every change; coverage of
the spec by stories."""

import pytest

from nexti_core.spec.coverage import StoryLinks, compute
from nexti_core.spec.plan import Dependency, StoryInfo, suggest, validate

STORIES = [
    StoryInfo("US-1", "P1", 3),  # tariffs
    StoryInfo("US-2", "P0", 5),  # debit (reads tariffs)
    StoryInfo("US-3", "P2", 1),  # notification (after the debit)
    StoryInfo("US-4", "P0", 2),  # account validation
]
DEPS = [
    Dependency("US-2", "US-1", "hard", "reads the tariff table"),
    Dependency("US-2", "US-4", "hard", "validates the account first"),
    Dependency("US-3", "US-2", "soft", "notifies after the debit"),
]


def test_the_suggestion_puts_each_story_after_its_dependencies_by_priority_then_size() -> None:
    assert suggest(STORIES, DEPS) == [["US-4", "US-1"], ["US-2"], ["US-3"]]


def test_a_hard_cycle_cannot_be_suggested() -> None:
    with pytest.raises(ValueError, match="cycle"):
        suggest(STORIES, [*DEPS, Dependency("US-1", "US-2", "hard")])


def test_a_soft_cycle_falls_back_to_hard_dependencies() -> None:
    # With the soft ones ignored, US-3 depends on nothing hard: it can start in the first wave.
    waves = suggest(STORIES, [*DEPS, Dependency("US-1", "US-3", "soft")])
    assert waves == [["US-4", "US-1", "US-3"], ["US-2"]]


def test_moving_a_story_before_a_hard_dependency_is_rejected_with_the_reason() -> None:
    check = validate([["US-2", "US-4"], ["US-1"], ["US-3"]], DEPS, [s.key for s in STORIES])
    assert not check.ok
    (error,) = check.errors
    assert (error.code, error.story, error.on) == ("hard_dependency", "US-2", "US-1")
    assert "reads the tariff table" in error.message


def test_before_a_soft_dependency_the_move_is_allowed_with_a_warning() -> None:
    check = validate([["US-1", "US-4"], ["US-3"], ["US-2"]], DEPS, [s.key for s in STORIES])
    assert check.ok
    (warning,) = check.warnings
    assert warning.code == "soft_dependency"
    assert "stub" in warning.message


def test_a_story_may_share_the_wave_of_its_dependency() -> None:
    assert validate([["US-1", "US-4", "US-2", "US-3"]], DEPS, [s.key for s in STORIES]).problems == []


def test_every_story_is_planned_and_only_known_stories() -> None:
    check = validate([["US-1", "US-9"]], [], ["US-1", "US-2"])
    assert {(p.code, p.story) for p in check.errors} == {("unknown_story", "US-9"), ("unplanned", "US-2")}


def test_discarding_a_story_leaves_its_rules_as_a_gap_unless_out_of_scope() -> None:
    rules = ["RULE-001", "RULE-002", "RULE-003"]
    stories = [
        StoryLinks("US-1", "approved", frozenset({"RULE-001"})),
        StoryLinks("US-2", "discarded", frozenset({"RULE-002"})),
        StoryLinks("US-3", "discarded", frozenset({"RULE-003"}), out_of_scope=True),
        StoryLinks("US-4", "draft", frozenset()),
    ]
    coverage = compute(rules, stories)
    assert coverage.covered == {"RULE-001": ["US-1"]}
    assert coverage.gaps == ["RULE-002"]
    assert coverage.out_of_scope == ["RULE-003"]
    assert coverage.untraced_stories == ["US-4"]
    assert not coverage.complete
