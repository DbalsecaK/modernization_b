"""Validation of acceptance criteria (spec 7.7, D-26): the checks of the table, in English and in Spanish."""

import pytest

from nexti_core.spec.gherkin import is_valid, validate_criteria, validate_scenario


def codes(text: str) -> list[str]:
    return [p.code for p in validate_scenario(text)]


VALID_EN = """\
@P0
Scenario: A company account can be debited
  Given a company "ACME" with a current account 0012345678
  And the order has a debit value of 150.25
  When the debit is processed
  Then the account balance decreases by 150.25
  But no commission movement is recorded
"""

VALID_ES = """\
Escenario: Una cuenta de empresa se puede debitar
  Dado una empresa "ACME" con una cuenta corriente 0012345678
  Y la orden tiene un valor de débito de 150.25
  Cuando se procesa el débito
  Entonces el saldo de la cuenta baja en 150.25
"""

OUTLINE = """\
Scenario Outline: Only some account types may be debited
  Given an account of type <type>
  When the debit is processed
  Then the result is <result>

  Examples:
    | type    | result   |
    | CTE     | accepted |
    | CREDIT  | rejected |
"""


@pytest.mark.parametrize("text", [VALID_EN, VALID_ES, OUTLINE])
def test_valid_scenarios_pass(text: str) -> None:
    assert validate_scenario(text) == []


def test_tables_doc_strings_and_comments_are_allowed() -> None:
    text = """\
# the header row is optional in the legacy file
Scenario: A file is parsed
  Given the file
    \"\"\"
    ACME;0012345678;150.25
    \"\"\"
  And the tariffs
    | service | tariff |
    | PAGOS   | 0.50   |
  When it is parsed
  Then one order is created
"""
    assert validate_scenario(text) == []


def test_a_scenario_without_when_is_rejected() -> None:
    assert "missing_when" in codes("Scenario: X\n  Given a thing\n  Then it holds\n")


def test_steps_out_of_order_are_rejected() -> None:
    assert "out_of_order" in codes("Scenario: X\n  When it runs\n  Given a thing\n  Then it holds\n")


def test_a_given_after_then_asks_to_split() -> None:
    text = "Scenario: X\n  Given a\n  When b\n  Then c\n  When d\n  Then e\n"
    assert "two_behaviours" in codes(text)


def test_a_placeholder_outside_examples_is_rejected_in_spanish_too() -> None:
    text = """\
Esquema del escenario: Tipos de cuenta
  Dado una cuenta de tipo <tipo>
  Cuando se procesa el débito
  Entonces el resultado es <salida>

  Ejemplos:
    | tipo | resultado |
    | CTE  | aceptado  |
"""
    problems = validate_scenario(text)
    assert [p.code for p in problems] == ["unknown_placeholder"]
    assert problems[0].line == 4


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Given a\nWhen b\nThen c\n", "missing_header"),
        ("Scenario:\n  Given a\n  When b\n  Then c\n", "missing_name"),
        ("Scenario: X\n  And a\n  When b\n  Then c\n", "continuation_first"),
        ("Scenario: X\n  Given\n  When b\n  Then c\n", "empty_step"),
        ("Scenario: X\n  Given a\n  this line is prose\n  When b\n  Then c\n", "free_text"),
        ("Scenario Outline: X\n  Given <a>\n  When b\n  Then c\n", "missing_examples"),
        ("Scenario Outline: X\n  Given <a>\n  When b\n  Then c\n  Examples:\n    | a |\n", "empty_examples"),
        ("   \n", "empty"),
    ],
)
def test_each_check_has_its_code(text: str, code: str) -> None:
    assert code in codes(text)


def test_two_scenarios_with_the_same_name_in_a_story_are_rejected() -> None:
    other = VALID_EN.replace("150.25", "10.00")
    problems = validate_criteria([VALID_EN, other, VALID_ES])
    assert list(problems) == [1]
    assert problems[1][0].code == "duplicate_name"
    assert not is_valid([VALID_EN, other])
    assert is_valid([VALID_EN, VALID_ES])
