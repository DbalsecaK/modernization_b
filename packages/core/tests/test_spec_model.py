"""Neutral types (spec 4.3) and the spec elements with their traceable origin (4.1, 4.2)."""

import pytest
from pydantic import ValidationError

from nexti_core.spec import neutral_types as nt
from nexti_core.spec.model import Rule, SourceRef, Spec


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("decimal(9,2,signed)", nt.Decimal(9, 2, True)),
        ("decimal(18, 4)", nt.Decimal(18, 4, True)),
        ("integer(32,unsigned)", nt.Integer(32, False)),
        ("text(fixed,10,ebcdic)", nt.Text("fixed", 10, "ebcdic")),
        ("text(var,max)", nt.Text("var", None, "utf8")),
        ("date(yyyyMMdd)", nt.Date("yyyyMMdd")),
        ("timestamp(tz)", nt.Timestamp(True)),
        ("boolean", nt.Boolean()),
        ("binary(16)", nt.Binary(16)),
        ("enum(CTE|AHO|VIR)", nt.Enum(("CTE", "AHO", "VIR"))),
    ],
)
def test_neutral_types_parse_and_print_back(text: str, value: nt.NeutralType) -> None:
    assert nt.parse(text) == value
    assert nt.parse(str(value)) == value


@pytest.mark.parametrize(
    "text", ["decimal(2,5)", "decimal(40,2)", "integer(12)", "text(wide,10)", "enum(A|A)", "money", "int32", ""]
)
def test_invalid_neutral_types_are_refused(text: str) -> None:
    assert not nt.is_valid(text)


def test_a_source_reference_round_trips() -> None:
    ref = SourceRef.parse("`debit_order.sp:120-148`")
    assert (ref.file, ref.line_start, ref.line_end) == ("debit_order.sp", 120, 148)
    assert str(ref) == "debit_order.sp:120-148"
    assert str(SourceRef.parse("a.sp:7")) == "a.sp:7"
    with pytest.raises(ValidationError):
        SourceRef(file="a.sp", line_start=9, line_end=3)


def rule(**extra: object) -> dict[str, object]:
    return {
        "id": "RULE-001",
        "name": "Only company accounts can be debited",
        "category": "validation",
        "priority": "P0",
        "statement": "A debit is only made on current, savings or virtual company accounts.",
        "inputs": [{"name": "account_type", "type": "enum(CTE|AHO|VIR)"}],
        "sources": [{"file": "debit_order.sp", "line_start": 40, "line_end": 52}],
        **extra,
    }


def test_a_rule_needs_an_id_a_citation_and_neutral_types() -> None:
    parsed = Rule.model_validate(rule(inputs=[{"name": "amount", "type": "decimal(18, 2)"}]))
    assert parsed.inputs[0].type == "decimal(18,2,signed)"
    bad_values: list[dict[str, object]] = [
        {"id": "R1"},
        {"sources": []},
        {"inputs": [{"name": "x", "type": "money"}]},
        {"priority": "P9"},
    ]
    for bad in bad_values:
        with pytest.raises(ValidationError):
            Rule.model_validate(rule(**bad))


def test_a_spec_has_unique_ids() -> None:
    one = Rule.model_validate(rule())
    assert Spec(rules=(one,)).rule("RULE-001") == one
    with pytest.raises(ValidationError, match="duplicate rule"):
        Spec(rules=(one, one))


def test_an_entity_key_written_with_the_legacy_column_means_its_field() -> None:
    import pytest
    from pydantic import ValidationError

    from nexti_core.spec.design import Entity

    fields = [{"name": "orderBank", "type": "integer(32,signed)", "column": "order_bank", "legacy": "or_orden_banco"},
              {"name": "amount", "type": "decimal(19,4,signed)", "legacy": "or_monto"}]  # fmt: skip
    assert Entity.model_validate({"name": "Order", "key": ["or_orden_banco"], "fields": fields}).key == ["orderBank"]
    assert Entity.model_validate({"name": "Order", "key": ["ORDER_BANK"], "fields": fields}).key == ["orderBank"]
    assert Entity.model_validate({"name": "Order", "key": ["orderBank"], "fields": fields}).key == ["orderBank"]
    with pytest.raises(ValidationError, match=r"key fields not declared: or_secuencial \(the key lists names of its "
                                              r"fields, one of: amount, orderBank"):  # fmt: skip
        Entity.model_validate({"name": "Order", "key": ["or_secuencial"], "fields": fields})


def test_a_port_method_returning_void_returns_nothing_and_a_scalar_is_explained() -> None:
    import pytest
    from pydantic import ValidationError

    from nexti_core.spec.design import Design

    def design(returns: str) -> dict[str, object]:
        return {"context": "payments", "base_package": "com.example.payments", "entities": [],
                "ports": [{"name": "CommissionGateway", "methods": [{"name": "calculate", "returns": returns}]}],
                "use_cases": [{"name": "PayOrder", "rules": ["RULE-001"], "ports": ["CommissionGateway"]}]}  # fmt: skip

    assert Design.model_validate(design("void")).ports[0].methods[0].returns is None
    assert Design.model_validate(design("long")).ports[0].methods[0].returns == "long"
    with pytest.raises(ValidationError, match=r"returns unknown type decimal\(19,4,signed\) \(a port method returns an "
                                              r"entity of the design, boolean, int, long or null"):  # fmt: skip
        Design.model_validate(design("decimal(19,4,signed)"))
