"""Characterization model (spec 6.1 phase 9): canonical values by neutral type, suites that validate themselves and
a stable identity for recordings."""

import pytest
from pydantic import ValidationError

from nexti_core.spec.characterization import Case, Schema, Suite, Table, canonical, suite_key


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


def test_a_key_marked_on_the_columns_becomes_the_table_key() -> None:
    table = Table.model_validate({"name": "db..t", "columns": [
        {"name": "a", "type": "int", "key": True}, {"name": "b", "type": "char(3)", "key": False},
        {"name": "c", "type": "int", "primary_key": True}]})  # fmt: skip
    assert table.key == ["a", "c"]
    assert [c.name for c in table.columns] == ["a", "b", "c"]
    both = Table.model_validate({"name": "db..t", "key": ["b"], "columns": [
        {"name": "a", "type": "int", "pk": True}, {"name": "b", "type": "int", "key": False}]})  # fmt: skip
    assert both.key == ["b", "a"]
    with pytest.raises(ValidationError, match="other"):  # anything else on a column is still rejected
        Table.model_validate({"name": "db..t", "columns": [{"name": "a", "type": "int", "other": 1}]})


def test_the_identity_of_a_run_follows_the_code_and_the_suite() -> None:
    suite = Suite(program="dbo.sp_x", schema_=Schema(), cases=[_case("first_case")])
    other = Suite(program="dbo.sp_x", schema_=Schema(), cases=[_case("other_case")])
    assert suite_key("create procedure", suite) == suite_key("create procedure", suite)
    assert suite_key("create procedure", suite) != suite_key("create procedure v2", suite)
    assert suite_key("create procedure", suite) != suite_key("create procedure", other)
