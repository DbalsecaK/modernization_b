"""The verdict by fixed rules (spec 11.3): differences field by field, fresh inputs derived deterministically, the
three outcomes and what each verdict does not prove, and a proof pack that recomputes to the same bytes."""

import io
import json
import zipfile
from datetime import UTC, datetime

from nexti_verification import CaseOutcome, build_proof_pack, compute, differences, fresh_suite, trace_rules
from nexti_verification import verdict as checks

from nexti_core.spec.characterization import Call, Case, Observation, Suite
from nexti_core.spec.model import Rule

BASE = Observation(returns=0, outputs={"@o_msg": "OK"}, tables={"db..t": [{"a": "1.0000"}]},
                   calls=[Call(program="db..debit", arguments={"@v": "100.6300"})])  # fmt: skip


def _rule(rule_id: str, priority: str) -> Rule:
    return Rule.model_validate({"id": rule_id, "name": "A rule name", "category": "calculation",
                                "priority": priority, "statement": "A statement long enough.",
                                "sources": [{"file": "sp.sp", "line_start": 1, "line_end": 2}]})  # fmt: skip


def test_differences_are_listed_field_by_field() -> None:
    assert differences(BASE, BASE) == []
    other = Observation(returns=50004, outputs={"@o_msg": "NO"}, tables={"db..t": [{"a": "2.0000"}]},
                        calls=[Call(program="db..debit", arguments={"@v": "100.6200"})])  # fmt: skip
    assert [(d.path, d.expected, d.actual) for d in differences(BASE, other)] == [
        ("returns", "0", "50004"), ("outputs:@o_msg", "OK", "NO"), ("tables:db..t[0].a", "1.0000", "2.0000"),
        ("calls[0]:db..debit.@v", "100.6300", "100.6200"),
    ]  # fmt: skip
    fewer = Observation(returns=0, outputs={"@o_msg": "OK"}, tables={"db..t": []}, calls=[])
    assert [d.path for d in differences(BASE, fewer)] == ["tables:db..t", "calls"]


def test_fresh_inputs_scale_amounts_and_keep_keys() -> None:
    suite = Suite(program="dbo.sp_x", cases=[Case(name="base_case", rules=["RULE-001"],
                                                  inputs={"@i_orden": 7, "@i_valor": 100.0, "@i_canal": "WEB"},
                                                  setup={"db..t": [{"saldo": "0.63", "id": 7}]})])  # fmt: skip
    fresh = fresh_suite(suite)
    assert len(fresh.cases) == 12
    assert fresh == fresh_suite(suite)  # deterministic: it can be recorded
    first = fresh.cases[0]
    assert first.name == "fresh_01_base_case"
    assert first.inputs == {"@i_orden": 7, "@i_valor": 50.0, "@i_canal": "WEB"}
    assert first.setup["db..t"] == [{"saldo": "0.32", "id": 7}]


def test_the_verdict_follows_fixed_rules() -> None:
    rules = [_rule("RULE-001", "P0"), _rule("RULE-002", "P2")]
    matched = [CaseOutcome("one", ["RULE-001"])]
    traces = trace_rules(rules, matched, {"RULE-001": ["src/A.java"]})
    traced, optional = checks.rules_traced(traces)
    assert traced.status == "passed"
    assert optional == ["RULE-002 (P2) is not backed by a golden case that matched"]
    passing = [checks.tests_ran(7, 0, True), traced, checks.same_behaviour(matched, []),
               checks.fresh_inputs([CaseOutcome(f"f{i}", ["RULE-001"]) for i in range(10)]),
               checks.canary([{"line": 3, "after": "x", "caught_by": "test a"}]),
               checks.source_intact("abc", "abc")]  # fmt: skip
    assert compute("PayOrder", passing, optional).verdict == "PROVEN"
    partly = compute("PayOrder", [*passing[:3], checks.fresh_inputs(None, "no engine"), *passing[4:]], [])
    assert partly.verdict == "PARTLY PROVEN"
    assert partly.not_proven == ["Fresh inputs: no engine"]
    changed = compute("PayOrder", [*passing[:5], checks.source_intact("abc", "abd")], [])
    assert changed.verdict == "NOT PROVEN"
    assert compute("PayOrder", passing[:2], []).verdict == "PARTLY PROVEN"  # checks that did not run
    unnoticed = checks.canary([{"line": 3, "after": "x", "caught_by": ""}])
    assert unnoticed.status == "failed"
    assert checks.tests_ran(0, 0, True).status == "failed"
    missing, _ = checks.rules_traced(trace_rules(rules, [CaseOutcome("one", ["RULE-001"], failure="boom")], {}))
    assert missing.status == "failed"


def test_the_proof_pack_holds_the_evidence_and_recomputes_the_same() -> None:
    outcome = [CaseOutcome("one", ["RULE-001"])]
    verdict = compute("PayOrder", [checks.tests_ran(1, 0, True)], ["a note"])
    moment = datetime(2026, 9, 29, tzinfo=UTC)
    traces = trace_rules([_rule("RULE-001", "P0")], outcome, {})
    pack = build_proof_pack(verdict, outcome, None, traces, "<testsuite/>", {"MASKS.json": []}, moment)
    assert pack == build_proof_pack(verdict, outcome, None, traces, "<testsuite/>", {"MASKS.json": []}, moment)
    archive = zipfile.ZipFile(io.BytesIO(pack))
    assert sorted(archive.namelist()) == ["EQUIVALENCE.json", "MASKS.json", "TRACE.json", "VERIFICATION.json",
                                          "junit.xml"]  # fmt: skip
    document = json.loads(archive.read("VERIFICATION.json"))
    assert document["verdict"] == "PARTLY PROVEN"
    assert document["not_proven"][0] == "a note"
    assert json.loads(archive.read("TRACE.json"))[0]["verified"] is True
