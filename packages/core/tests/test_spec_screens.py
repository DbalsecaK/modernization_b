"""The screen spec (spec 4.1, 7.4): fields with neutral types, attributes consistent with their kind, and a terminal
layout where fields fit the grid and never overlap (the attribute byte included)."""

import pytest
from pydantic import ValidationError

from nexti_core.spec.screens import ScreenSpec


def _field(name: str, row: int, column: int, length: int, kind: str = "output", **extra: object) -> dict[str, object]:
    return {"name": name, "kind": kind, "position": {"row": row, "column": column}, "length": length, **extra}


def _screen(*fields: dict[str, object]) -> ScreenSpec:
    return ScreenSpec.model_validate({"id": "SCR-PAYORD", "name": "Pay an order", "rows": 24, "columns": 80,
                                      "fields": list(fields)})  # fmt: skip


def test_a_terminal_screen_keeps_positions_attributes_and_neutral_types() -> None:
    screen = _screen(
        _field("TITLE", 1, 30, 20, "literal", initial="PAGO DE ORDENES", attributes=["protected", "bright"]),
        _field("ORDEN", 5, 20, 7, "input", attributes=["unprotected", "numeric", "cursor"],
               type="integer(32,signed)", required=True, format="9(7)"),
        _field("VALOR", 7, 20, 12, "output", type="decimal(11,2,signed)", format="ZZZ,ZZZ,ZZ9.99"),
    )  # fmt: skip
    orden = screen.field("ORDEN")
    assert orden is not None
    assert orden.attributes == ("unprotected", "numeric", "cursor")
    assert orden.type == "integer(32,signed)"
    assert [f.name for f in screen.inputs()] == ["ORDEN"]


def test_fields_must_fit_the_grid_and_not_overlap() -> None:
    with pytest.raises(ValidationError, match="does not fit in a 24x80 screen"):
        _screen(_field("WIDE", 3, 70, 12))
    with pytest.raises(ValidationError, match="B overlaps A at row 3, column 14"):
        _screen(_field("A", 3, 10, 5), _field("B", 3, 15, 5))  # B's attribute byte is column 14
    assert _screen(_field("A", 3, 10, 5), _field("B", 3, 16, 5)).field("B") is not None


def test_kinds_and_attributes_agree_and_names_are_unique() -> None:
    with pytest.raises(ValidationError, match="an input field cannot be protected"):
        _screen(_field("X", 2, 2, 3, "input", attributes=["protected"]))
    with pytest.raises(ValidationError, match="a literal cannot be unprotected"):
        _screen(_field("X", 2, 2, 3, "literal", attributes=["unprotected"]))
    with pytest.raises(ValidationError, match="repeated field names: X"):
        _screen(_field("X", 2, 2, 3), _field("X", 4, 2, 3))
    with pytest.raises(ValidationError, match="not a screen id"):
        ScreenSpec.model_validate({"id": "PAYORD", "name": "x", "fields": [{"name": "A", "kind": "output",
                                                                            "length": 1}]})  # fmt: skip
    with pytest.raises(ValidationError):
        _screen(_field("X", 2, 2, 3, type="money"))
