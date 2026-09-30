"""Evaluation against a reference spec (spec 21.4) with the fictitious application's reference: omissions (P0
apart), hallucinations and precision errors measured by code; rule cards and kits read without copying anything of
them into the metrics (ADR-0011)."""

import json
from pathlib import Path

import pytest

from nexti_core.spec.model import Rule
from nexti_verification.evaluation import evaluate, load_reference, parse_rule_cards, values
from nexti_verification.kit import KitError, load_kit

REFERENCE = Path(__file__).resolve().parents[2] / "adapters/source/sybase/tests/fixtures/pago_orden/reference_spec.json"
RULES = [Rule.model_validate(r) for r in json.loads(REFERENCE.read_text(encoding="utf-8"))["rules"]]
CARD = """# Business Rules - demo

### RULE-001: Web orders pay half the tariff
**Category:** Calculation
**Priority:** P0
**Source:** `sp_demo.sp:80-86`
**Plain English:** Web orders pay half of the tariff, rounded to cents.
**Specification:**
  Given a tariff of 1.25
  When a WEB order is paid
  Then the commission is 0.63
**Parameters:** Channel = 'WEB'; rounding to 2 decimals
**Confidence:** High
"""


def _changed(rule_id: str, **fields: object) -> Rule:
    rule = next(r for r in RULES if r.id == rule_id)
    return Rule.model_validate({**rule.model_dump(), **fields})


def test_values_are_the_concrete_codes_amounts_and_literals() -> None:
    assert values("if channel = 'WEB' and amount + 100.00 < total return 50004") == {"WEB", "100", "50004"}
    assert values("the order is marked A") == set()


def test_the_same_rules_are_a_perfect_score() -> None:
    result = evaluate(load_reference(REFERENCE), RULES)
    assert (result.recall, result.precision) == (1.0, 1.0)
    assert result.omissions == []
    assert result.hallucinations == []
    assert result.precision_errors == []
    assert result.reference_sha256 == __import__("hashlib").sha256(REFERENCE.read_bytes()).hexdigest()


def test_omissions_hallucinations_and_precision_errors_are_measured() -> None:
    invented = Rule.model_validate({
        "id": "RULE-050", "name": "Weekend orders are charged double", "category": "calculation", "priority": "P1",
        "statement": "Orders processed on a weekend pay twice the commission.",
        "sources": [{"file": "sp_pago_orden.sp", "line_start": 5, "line_end": 6}],
    })  # fmt: skip
    wrong_limit = _changed(
        "RULE-006",
        name="Virtual accounts cannot overdraw; others up to 50.00",
        statement="Virtual accounts cannot overdraw; others may overdraw up to 50.00.",
        condition="type = 'VIR' or balance + 50.00 < total",
        action="reject with 50004",
        scenarios=(),
    )
    found = [r for r in RULES if r.id not in ("RULE-004", "RULE-006")] + [wrong_limit, invented]
    result = evaluate(load_reference(REFERENCE), found)
    assert result.omissions == ["RULE-004"]
    assert result.omissions_p0 == ["RULE-004"]
    assert result.hallucinations == ["RULE-050"]
    assert {"reference": "RULE-006", "found": "RULE-006", "missing_values": ["100", "FONDOS INSUFICIENTES"]} in (
        result.precision_errors
    )
    assert result.recall == round(8 / 9, 3)
    metrics = result.metrics()
    assert metrics["reference"] == "pago_orden (Banco Ficticio, fictitious)"
    assert "statement" not in json.dumps(metrics)  # names, ids and values; never the text of the reference


def test_rule_cards_are_a_reference_too() -> None:
    (card,) = parse_rule_cards(CARD)
    assert (card.id, card.priority, card.file, card.line_start, card.line_end) == ("RULE-001", "P0", "sp_demo.sp", 80,
                                                                                  86)  # fmt: skip
    assert card.values == ("WEB",)


def test_a_kit_is_read_from_its_folder_and_a_reviewed_reference_declares_its_bias(tmp_path: Path) -> None:
    kit = tmp_path / "demo"
    (kit / "source").mkdir(parents=True)
    (kit / "source" / "sp_demo.sp").write_text("create procedure dbo.sp_demo as return 0\n", encoding="utf-8")
    (kit / "BUSINESS_RULES.md").write_text(CARD, encoding="utf-8")
    with pytest.raises(KitError, match=r"kit.json is missing"):
        load_kit(kit)
    (kit / "kit.json").write_text(json.dumps({"name": "demo", "program": "dbo.sp_demo", "written_blind": False}),
                                  encoding="utf-8")  # fmt: skip
    loaded = load_kit(kit)
    assert (loaded.name, loaded.program, [s.path for s in loaded.sources]) == ("demo", "dbo.sp_demo", ["sp_demo.sp"])
    result = evaluate(loaded.reference, [])
    assert result.omissions_p0 == ["RULE-001"]
    assert result.known_bias is not None
