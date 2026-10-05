"""A declared source adapter (ADR-0039) on a fictitious language: the specification is validated, and the adapter
inventories, classifies, slices and digests the samples with its patterns alone."""

import pytest
from pydantic import ValidationError

from nexti_core.adapters import SourceFile
from nexti_core.declarative_adapter import AdapterSpec, DeclarativeAdapter, summary

SPEC = {
    "key": "toy-lang",
    "name": "Toy language",
    "extensions": ["toy"],
    "comment_prefixes": ["--"],
    "unit": r"^\s*PROCEDURE\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
    "parameter": r"^\s*PARAM\s+(?P<name>\w+)\s+(?P<type>\w+)",
    "call": r"\bCALL\s+(?P<callee>[A-Za-z_][A-Za-z0-9_]*)",
    "reads": [r"\bFROM\s+(?P<table>[A-Za-z_][A-Za-z0-9_.]*)"],
    "writes": [r"\bUPDATE\s+(?P<table>[A-Za-z_][A-Za-z0-9_.]*)"],
    "infrastructure_keywords": ["LOG", "COMMIT"],
    "control_keywords": ["IF", "ELSE", "RETURN"],
    "type_map": {"INT": "integer(32,signed)", "MONEY": "decimal(19,4,signed)"},
}
SOURCE = """-- a toy program
PROCEDURE pay_order
  PARAM order_id INT
  PARAM amount MONEY
  SELECT total FROM db.orders
  IF total > amount
    LOG 'short'
    RETURN
  UPDATE db.orders
  CALL post_ledger
  COMMIT
PROCEDURE refund
  PARAM order_id INT
  UPDATE db.refunds
"""
FILES = [SourceFile("src/pay.toy", SOURCE), SourceFile("README.md", "not code")]


def test_the_specification_is_validated_before_anything_runs() -> None:
    with pytest.raises(ValidationError, match="needs the named group"):
        AdapterSpec.model_validate({**SPEC, "unit": r"^\s*PROCEDURE\s+(\w+)"})
    with pytest.raises(ValidationError, match="not a valid regular expression"):
        AdapterSpec.model_validate({**SPEC, "call": r"\bCALL\s+(?P<callee>[A-Z"})
    with pytest.raises(ValidationError):
        AdapterSpec.model_validate({**SPEC, "key": "Toy Lang"})
    assert AdapterSpec.model_validate(SPEC).extensions == [".toy"]


def test_the_adapter_inventories_classifies_and_slices_with_the_patterns() -> None:
    adapter = DeclarativeAdapter(AdapterSpec.model_validate(SPEC))
    assert 0.4 < adapter.detect(FILES) <= 0.5  # one of two files is of this technology, and it has units
    assert adapter.detect([SourceFile("x.cbl", "IDENTIFICATION DIVISION.")]) == 0.0
    inventory = adapter.inventory(FILES)
    programs = [n for n in inventory.nodes if n.label == "Program" and not n.properties.get("external")]
    assert [(n.name, n.line_start, n.line_end) for n in programs] == [("pay_order", 2, 11), ("refund", 12, 14)]
    assert {n.name for n in inventory.nodes if n.label == "Table"} == {"db.orders", "db.refunds"}
    assert [n.name for n in inventory.nodes if n.properties.get("external")] == ["post_ledger"]
    kinds = {(e.source, e.type, e.target) for e in inventory.edges}
    assert ("program:pay_order", "CALLS", "program:post_ledger") in kinds
    assert ("program:pay_order", "WRITES", "table:db.orders") in kinds
    assert ("program:refund", "WRITES", "table:db.refunds") in kinds
    assert inventory.metrics == {"programs": 2, "statements": 11, "tables": 2, "files": 1}
    assert inventory.problems == []
    assert adapter.classification(FILES) == {"business": 7, "control_flow": 2, "infrastructure": 2}
    slices = adapter.slices(FILES)
    assert [(s.unit, s.lines, s.parameters, s.tables) for s in slices] == [
        ("pay_order#1", ((2, 11),), ("order_id", "amount"), ("db.orders",)),
        ("refund#1", ((12, 14),), ("order_id",), ("db.refunds",)),
    ]
    assert adapter.data_of(FILES, "pay.toy", [(5, 9)]) == (frozenset({"db.orders"}), frozenset({"db.orders"}))
    assert adapter.types(FILES)["MONEY"] == "decimal(19,4,signed)"
    digest = adapter.digest(FILES)
    assert "Program pay_order (src/pay.toy:2-11)" in digest
    assert "PARTLY PROVEN" in digest  # the adapter says how (little) the legacy can be observed
    found = summary(adapter, FILES)
    assert (found["metrics"]["programs"], found["calls"], found["tables"]) == (
        2,
        ["post_ledger"],
        ["db.orders", "db.refunds"],
    )


def test_a_file_without_a_unit_line_is_one_unit_named_after_the_file() -> None:
    adapter = DeclarativeAdapter(AdapterSpec.model_validate(SPEC))
    inventory = adapter.inventory([SourceFile("jobs/nightly.toy", "SELECT x FROM db.jobs\nUPDATE db.jobs\n")])
    (program,) = [n for n in inventory.nodes if n.label == "Program"]
    assert (program.name, program.line_start, program.line_end) == ("nightly", 1, 2)


def test_first_json_reads_a_fenced_or_wrapped_reply() -> None:
    from nexti_core.declarative_adapter import first_json

    assert first_json('Here it is:\n```json\n{"key": "x"}\n```') == {"key": "x"}
    assert first_json("[1, 2] and more") == [1, 2]
    with pytest.raises(ValueError, match="no JSON object"):
        first_json("no json here")
