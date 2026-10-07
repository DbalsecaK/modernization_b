"""Characterization model (spec 6.1 phase 9): canonical values by neutral type, suites that validate themselves and
a stable identity for recordings."""

import pytest
from pydantic import ValidationError

from nexti_core.spec.characterization import Case, GoldenMaster, Suite, Table, canonical


@pytest.mark.parametrize(
    ("neutral", "raw", "expected"),
    [
        ("decimal(19,4,signed)", "0.63", "0.6300"),
        ("decimal(19,4,signed)", "1,234.5", "1234.5000"),
        ("integer(32,signed)", "0042", "42"),
        ("integer(32,signed)", 7, "7"),
        ("text(fixed,10,iso8859-1)", "ABC       ", "ABC"),
        ("text(var,10,iso8859-1)", "ABC  ", "ABC  "),
        ("timestamp(local)", "2026-03-02 09:30:00", "2026-03-02T09:30:00.000"),
        ("timestamp(local)", "2026-03-02T09:30:00.123", "2026-03-02T09:30:00.123"),
        ("date(yyyy-MM-dd)", "2026-03-02T00:00:00", "2026-03-02"),
        ("boolean", "1", "true"),
        ("boolean", "N", "false"),
        ("binary(4)", "0xDEADBEEF", "deadbeef"),
        ("decimal(19,4,signed)", "not a number", "not a number"),
        (None, "as given", "as given"),
        ("text(var,10,utf8)", None, None),
    ],
)
def test_values_are_canonical_by_neutral_type(neutral: str | None, raw: object, expected: str | None) -> None:
    assert canonical(neutral, raw) == expected


def _case(name: str) -> Case:
    return Case(name=name, rules=["RULE-001"], inputs={"@i_x": 1})


def test_a_suite_rejects_repeated_case_names_and_undeclared_keys() -> None:
    with pytest.raises(ValidationError, match="duplicate case names: same_case"):
        Suite(program="dbo.sp_x", cases=[_case("same_case"), _case("same_case")])
    with pytest.raises(ValidationError, match="key columns not declared: b"):
        Table.model_validate({"name": "db..t", "columns": [{"name": "a", "type": "int"}], "key": ["b"]})
    with pytest.raises(ValidationError):
        Case(name="Not Snake", rules=["RULE-001"])


def _quirk_master() -> GoldenMaster:
    # M28: two cases, one entering the branch at lines 10-14; quirks at the top level, inside that branch, and inside
    # a branch no case enters.
    from nexti_core.spec.characterization import (
        Coverage,
        CoveredBranch,
        EngineQuirk,
        EnvironmentItem,
        GoldenMaster,
        Observation,
        Recorded,
        Schema,
    )

    def quirk(qid: str, severity: str, lines: list[int], observed: str | None = None) -> EngineQuirk:
        return EngineQuirk(id=qid, severity=severity, behavior="b.", target="t.", lines=lines, probe="p",
                           expected="1", observed=observed)  # fmt: skip

    branches = [CoveredBranch(id="10-14:if-true", kind="if-true", line_start=10, line_end=14),
                CoveredBranch(id="8-14:if-false", kind="if-false", line_start=8, line_end=14),
                CoveredBranch(id="20-22:else", kind="else", line_start=20, line_end=22)]  # fmt: skip
    cases = [Case(name="enters", rules=["RULE-001"]), Case(name="skips", rules=["RULE-001"])]
    return GoldenMaster(
        program="p", source_sha256="0" * 64, engine="e", schema_=Schema(),
        results=[Recorded(case=c, observation=Observation()) for c in cases],
        coverage=Coverage(branches=branches, executed={"enters": ["10-14:if-true"], "skips": ["8-14:if-false"]}),
        quirks=[quirk("top", "high", [3], "1"), quirk("inside", "critical", [12], "2"),
                quirk("beside", "high", [11]), quirk("unreached", "high", [21])],
        environment=[EnvironmentItem(key="language", value="us_english", source="engine")],
    )  # fmt: skip


def test_a_quirk_is_reached_by_the_cases_entering_the_branch_that_holds_it() -> None:
    from nexti_core.spec.characterization import quirk_cases, unresolved_quirks

    master = _quirk_master()
    cases = quirk_cases(master)
    assert cases["top"] == ["enters", "skips"]  # top level: every reliable case
    assert cases["inside"] == ["enters"]  # the innermost body, never the implicit ELSE spanning the IF
    assert cases["unreached"] == []
    assert [q.id for q in unresolved_quirks(master)] == ["unreached"]


def test_severe_quirks_meeting_in_a_branch_need_one_case_running_it() -> None:
    from nexti_core.spec.characterization import engine_not_proven, quirk_combinations

    combos = quirk_combinations(_quirk_master())
    assert ("beside", "inside", "10-14:if-true", ["enters"]) in combos
    lines = engine_not_proven(_quirk_master())
    assert lines == ["Engine quirk no case reaches: unreached (high) at lines 21"]


def test_the_engine_notes_say_what_this_engine_does_and_empty_registers_serialise_as_before() -> None:
    from nexti_core.spec.characterization import engine_notes

    master = _quirk_master()
    notes = engine_notes(master)
    assert "[high] top (lines 3; confirmed on the legacy engine)" in notes
    assert "this engine does NOT behave so (it answered '2')" in notes
    assert "language = us_english (engine)" in notes
    bare = master.model_copy(update={"quirks": [], "environment": []})
    assert engine_notes(bare) == ""
    data = bare.model_dump(by_alias=True)
    assert "quirks" not in data
    assert "environment" not in data


def test_the_gaps_are_the_branches_without_a_case_and_the_quirks_no_case_reaches() -> None:
    # ADR-0050: what of the legacy the golden master does not prove; nothing when coverage was not measured.
    from nexti_core.spec.characterization import legacy_gaps

    master = _quirk_master()
    assert legacy_gaps(master) == ["branch 20-22 (else)", "quirk unreached (high) at lines 21"]
    assert legacy_gaps(master.model_copy(update={"coverage": None})) == []
