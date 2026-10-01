"""The checks of the Flow 2 verdict (ADR-0018): computed by code from the evidence, with fixed rules."""

from nexti_verification import verdict as v


def test_every_criterion_needs_a_passing_test_with_its_id() -> None:
    criteria = [("US-001", 1, "Cuota a 12 meses"), ("US-001", 12, "Otro"), ("US-002", 1, "Se guarda")]
    passed = ["ac_US001_1_cuota_a_12_meses", "Ac_US001_12_otro", "com.x.Tests.ac_us002_1_saves"]
    assert v.criteria_covered(criteria, passed).status == "passed"
    missing = v.criteria_covered(criteria, passed[:1])
    assert missing.status == "failed"
    assert "US-001 #12 (Otro)" in missing.detail
    assert v.criteria_covered(criteria[:1], ["ac_US001_11_x"]).status == "failed"  # 11 is not 1
    assert v.criteria_covered([], []).status == "not_checked"
    assert v.criterion_test("US-007", 3) == "ac_US007_3_"


def test_the_feature_verdict_has_its_six_checks() -> None:
    found = [
        v.tests_ran(9, 0, True),
        v.criteria_covered([("US-001", 1, "a")], ["ac_US001_1_a"]),
        v.contracts(["POST /api/loans/simulations"], []),
        v.canary([{"line": 3, "after": "x", "caught_by": "test t"}]),
        v.questions_closed([]),
        v.traced_to_inputs(9, []),
    ]
    verdict = v.compute("loans", found, [], required=v.FEATURE_CHECKS)
    assert verdict.verdict == "PROVEN"
    assert [c.title for c in verdict.checks][1:3] == ["Criteria covered", "Contracts"]
    open_question = v.compute("loans", [*found[:4], v.questions_closed(["¿Monto?"]), found[5]], [],
                              required=v.FEATURE_CHECKS)  # fmt: skip
    assert open_question.verdict == "NOT PROVEN"
    assert v.compute("loans", found[:5], [], required=v.FEATURE_CHECKS).verdict == "PARTLY PROVEN"
