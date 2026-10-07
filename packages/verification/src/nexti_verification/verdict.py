"""The verdict of a module (spec 11.3), computed by code with fixed rules:

| # | Check | Passes when |
|---|---|---|
| 1 | Tests ran | a clean build ran tests, counted from the JUnit XML, and none failed |
| 2 | Rules traced | every P0 rule has golden cases that ran on the target and matched (P1/P2 per project policy) |
| 3 | Same behaviour | every golden case matched, field by field, with the declared masks only |
| 4 | Fresh inputs | at least 10 new inputs ran on both sides without differences (when the legacy runs) |
| 5 | Canary | a deliberate one-line change turned tests or cases red |
| 6 | Source intact | the legacy is byte for byte the code that was characterized |

PROVEN: all pass. NOT PROVEN: one fails. PARTLY PROVEN: none failed but one could not be checked. Every verdict
lists what it does not prove. PROVEN is evidence, not approval: a person signs off at C4."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from nexti_core.spec.model import Rule
from nexti_verification.compare import Difference

CheckStatus = Literal["passed", "failed", "not_checked"]
VerdictValue = Literal["PROVEN", "PARTLY PROVEN", "NOT PROVEN"]
CHECKS: tuple[tuple[str, str], ...] = (
    ("tests_ran", "Tests ran"),
    ("rules_traced", "Rules traced"),
    ("same_behaviour", "Same behaviour"),
    ("fresh_inputs", "Fresh inputs"),
    ("canary", "Canary"),
    ("source_intact", "Source intact"),
)
# The checks of a generated frontend (ADR-0016): it compiles and every screen meets its contract in the harness.
FRONTEND_CHECKS: tuple[tuple[str, str], ...] = (
    ("compiles", "Compiles"),
    ("screens_mount", "Screens mount"),
    ("fields_covered", "Fields covered"),
    ("validations", "Validations"),
    ("actions", "Actions"),
    ("accessibility", "Accessibility"),
)
# The checks of Flow 2 (11.4, 7.5; ADR-0018): there is no legacy, so the acceptance criteria are the oracle.
FEATURE_CHECKS: tuple[tuple[str, str], ...] = (
    ("tests_ran", "Tests ran"),
    ("criteria_covered", "Criteria covered"),
    ("contracts", "Contracts"),
    ("canary", "Canary"),
    ("questions_closed", "Questions closed"),
    ("traced_to_inputs", "Traced to inputs"),
)
# The checks of a generated IaC (ADR-0021): it validates and meets the fitness functions of the deployment pack.
IAC_CHECKS: tuple[tuple[str, str], ...] = (
    ("validates", "Validates"),
    ("encryption_at_rest", "Encryption at rest"),
    ("db_not_public", "Database not public"),
    ("no_secrets_in_code", "No secrets in code"),
    ("tags", "Tags"),
    ("logs", "Logs"),
)
# The checks of an independent validation (Flow 4, ADR-0025): a third party's target against the legacy's golden
# master, through the approved mapping. There is no canary: the third party's artifact is not mutated.
IVV_CHECKS: tuple[tuple[str, str], ...] = (
    ("target_runs", "Target runs"),
    ("contract_mapped", "Contract mapped"),
    ("same_behaviour", "Same behaviour"),
    ("fresh_inputs", "Fresh inputs"),
    ("rules_covered", "Rules covered"),
    ("source_intact", "Source intact"),
)
# The checks of a delta added to an existing application (Flow 3, ADR-0026): what worked keeps working, the new
# criteria pass, the existing contract is kept and the delta respects the application's architecture.
EXTEND_CHECKS: tuple[tuple[str, str], ...] = (
    ("regression", "Regression"),
    ("criteria_covered", "Criteria covered"),
    ("contract_kept", "Contract kept"),
    ("fitness", "Fitness functions"),
    ("canary", "Canary"),
    ("traced_to_inputs", "Traced to inputs"),
)
# The legacy covered (ADR-0050): only in a verdict whose golden master measured the legacy's coverage.
LEGACY_CHECKS: tuple[tuple[str, str], ...] = (("legacy_covered", "Legacy covered"),)
_TITLES = (dict(CHECKS) | dict(FRONTEND_CHECKS) | dict(FEATURE_CHECKS) | dict(IAC_CHECKS) | dict(IVV_CHECKS)
           | dict(EXTEND_CHECKS) | dict(LEGACY_CHECKS))  # fmt: skip
_CRITERION = re.compile(r"(?i)ac_?us-?_?0*(\d{1,4})_(\d{1,3})(?![0-9])")


@dataclass(frozen=True)
class Check:
    key: str
    status: CheckStatus
    detail: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return _TITLES[self.key]


@dataclass(frozen=True)
class CaseOutcome:
    """A case run on both sides: its rules and its differences, or why it could not be compared."""

    name: str
    rules: Sequence[str]
    differences: Sequence[Difference] = ()
    failure: str | None = None

    @property
    def matched(self) -> bool:
        return self.failure is None and not self.differences


@dataclass(frozen=True)
class RuleTrace:
    rule: str
    priority: str
    sources: list[str]
    target_files: list[str]
    cases: list[tuple[str, bool]]

    @property
    def verified(self) -> bool:
        return bool(self.cases) and all(matched for _, matched in self.cases)


@dataclass(frozen=True)
class Verdict:
    module: str
    verdict: VerdictValue
    checks: list[Check]
    not_proven: list[str]


def tests_ran(passed: int, failed: int, report_found: bool) -> Check:
    if not report_found:
        return Check("tests_ran", "failed", "no JUnit report: the tests did not run")
    evidence = {"passed": passed, "failed": failed}
    if failed:
        return Check("tests_ran", "failed", f"{failed} test(s) failed of {passed + failed}", evidence)
    if not passed:
        return Check("tests_ran", "failed", "the build ran no test", evidence)
    return Check("tests_ran", "passed", f"{passed} test(s) passed in a clean build (JUnit XML)", evidence)


def trace_rules(
    rules: Sequence[Rule], outcomes: Sequence[CaseOutcome], target_files: Mapping[str, Sequence[str]]
) -> list[RuleTrace]:
    return [
        RuleTrace(
            rule.id,
            rule.priority,
            [str(s) for s in rule.sources],
            sorted(target_files.get(rule.id, [])),
            [(o.name, o.matched) for o in outcomes if rule.id in o.rules],
        )
        for rule in rules
    ]


def rules_traced(traces: Sequence[RuleTrace], required: Sequence[str] = ("P0",)) -> tuple[Check, list[str]]:
    """The rules of the required priorities must be verified; the others are reported as not proven."""
    missing = [t.rule for t in traces if t.priority in required and not t.verified]
    optional = [
        f"{t.rule} ({t.priority}) is not backed by a golden case that matched"
        for t in traces
        if t.priority not in required and not t.verified
    ]
    evidence = {
        "verified": [t.rule for t in traces if t.verified],
        "unverified": [t.rule for t in traces if not t.verified],
    }
    if missing:
        return Check(
            "rules_traced", "failed", f"rules without a matching golden case: {', '.join(missing)}", evidence
        ), optional
    verified = sum(1 for t in traces if t.verified)
    return Check(
        "rules_traced", "passed", f"{verified} of {len(traces)} rule(s) verified by golden cases", evidence
    ), optional


def same_behaviour(outcomes: Sequence[CaseOutcome], masks: Sequence[str]) -> Check:
    if not outcomes:
        return Check("same_behaviour", "not_checked", "there is no golden master to compare with")
    different = [o for o in outcomes if not o.matched]
    evidence = {"cases": len(outcomes), "different": [o.name for o in different], "masks": list(masks)}
    if different:
        first = different[0]
        reason = first.failure or "; ".join(f"{d.path}: {d.expected} != {d.actual}" for d in first.differences[:3])
        return Check(
            "same_behaviour",
            "failed",
            f"{len(different)} of {len(outcomes)} case(s) differ; {first.name}: {reason}"[:1000],
            evidence,
        )
    return Check("same_behaviour", "passed", f"{len(outcomes)} golden case(s) reproduced", evidence)


def fresh_inputs(outcomes: Sequence[CaseOutcome] | None, unavailable: str = "", minimum: int = 10) -> Check:
    if outcomes is None:
        return Check("fresh_inputs", "not_checked", unavailable or "the legacy cannot run fresh inputs")
    different = [o.name for o in outcomes if not o.matched]
    evidence = {"cases": len(outcomes), "different": different}
    if different:
        return Check(
            "fresh_inputs", "failed", f"{len(different)} fresh input(s) differ: {', '.join(different[:5])}", evidence
        )
    if len(outcomes) < minimum:
        return Check(
            "fresh_inputs", "not_checked", f"only {len(outcomes)} fresh input(s), {minimum} required", evidence
        )
    return Check("fresh_inputs", "passed", f"{len(outcomes)} fresh input(s) matched on both sides", evidence)


def canary(attempts: Sequence[Mapping[str, Any]]) -> Check:
    """Each attempt: the mutated line and what caught it (`caught_by`, empty when nothing did)."""
    if not attempts:
        return Check("canary", "not_checked", "no line of the service could be mutated")
    caught = next((a for a in attempts if a.get("caught_by")), None)
    if caught is None:
        return Check(
            "canary",
            "failed",
            f"{len(attempts)} deliberate change(s) went unnoticed by tests and cases",
            {"attempts": list(attempts)},
        )
    return Check(
        "canary",
        "passed",
        f"line {caught['line']} changed ({caught['after'].strip()[:80]}) turned {caught['caught_by']} red",
        {"attempts": list(attempts)},
    )


def source_intact(characterized: str | None, current: str) -> Check:
    evidence = {"characterized": characterized, "current": current}
    if characterized is None:
        return Check("source_intact", "not_checked", "the source was never characterized", evidence)
    if characterized != current:
        return Check("source_intact", "failed", "the legacy changed after it was characterized", evidence)
    return Check("source_intact", "passed", "the legacy is the code that was characterized (SHA-256)", evidence)


def legacy_covered(gaps: Sequence[str], decision: str | None, by: str | None, comment: str = "") -> Check:
    """Every branch of the legacy entered and every engine quirk reached, or each gap with a signed decision
    (ADR-0050): signed unreachable, the check passes; accepted as a gap, the verdict stays PARTLY PROVEN."""
    evidence = {"gaps": list(gaps), "decision": decision, "by": by, "comment": comment}
    if not gaps:
        return Check("legacy_covered", "passed", "every measurable branch of the legacy was entered and every engine "
                     "quirk reached by a case", evidence)  # fmt: skip
    signer = by or "the analyst"
    if decision == "unreachable":
        return Check("legacy_covered", "passed", f"{len(gaps)} gap(s) no input can reach, signed by {signer}",
                     evidence)  # fmt: skip
    return Check("legacy_covered", "not_checked", f"{len(gaps)} gap(s) of the legacy no case covers"
                 + (f", accepted as not proven by {signer}" if decision else ", without a signed decision"),
                 evidence)  # fmt: skip


def criterion_test(story: str, number: int) -> str:
    """The prefix of the test of a story's criterion, e.g. ac_US001_2_."""
    return f"ac_{story.replace('-', '')}_{number}_"


def criteria_passed(passed_tests: Sequence[str]) -> set[tuple[int, int]]:
    """(story number, criterion number) of every passing test that carries a criterion id (ac_US001_2_...)."""
    return {(int(m.group(1)), int(m.group(2))) for name in passed_tests for m in _CRITERION.finditer(name)}


def criteria_covered(criteria: Sequence[tuple[str, int, str]], passed_tests: Sequence[str]) -> Check:
    """Every criterion (story key, number, scenario name) has a test that carries its id and passed (7.5)."""
    if not criteria:
        return Check("criteria_covered", "not_checked", "no story has criteria that tests can cover")
    found = criteria_passed(passed_tests)
    missing = [f"{story} #{n} ({name})" for story, n, name in criteria
               if (int(story.split("-")[-1]), n) not in found]  # fmt: skip
    evidence = {"criteria": len(criteria), "missing": missing}
    if missing:
        detail = f"{len(missing)} of {len(criteria)} criteria without a passing test: {'; '.join(missing[:5])}"
        return Check("criteria_covered", "failed", detail[:1000], evidence)
    return Check("criteria_covered", "passed", f"{len(criteria)} acceptance criteria covered by passing tests",
                 evidence)  # fmt: skip


def contracts(operations: Sequence[str], missing: Sequence[str]) -> Check:
    """Every operation of the contract derived from the design has its endpoint in the generated code."""
    if not operations:
        return Check("contracts", "not_checked", "the design has no operations")
    evidence = {"operations": list(operations), "missing": list(missing)}
    if missing:
        return Check("contracts", "failed", f"operations without an endpoint: {', '.join(missing)}", evidence)
    return Check("contracts", "passed", f"{len(operations)} operation(s) of the contract have their endpoint", evidence)


def questions_closed(open_questions: Sequence[str]) -> Check:
    if open_questions:
        return Check("questions_closed", "failed", f"{len(open_questions)} question(s) still open: "
                     f"{'; '.join(open_questions[:3])}"[:1000], {"open": list(open_questions)})  # fmt: skip
    return Check("questions_closed", "passed", "no question is open", {"open": []})


def traced_to_inputs(elements: int, untraced: Sequence[str]) -> Check:
    """Every rule, screen and story cites an accepted input (directly, or through what it links)."""
    evidence = {"elements": elements, "untraced": list(untraced)}
    if untraced:
        return Check("traced_to_inputs", "failed", f"not traced to an input: {', '.join(untraced[:10])}", evidence)
    return Check("traced_to_inputs", "passed", f"{elements} element(s) traced to the lines of their inputs", evidence)


def compute(
    module: str, checks: Sequence[Check], not_proven: Sequence[str], required: Sequence[tuple[str, str]] = CHECKS
) -> Verdict:
    """`required` is the set of checks of this kind of verdict (the backend's six by default)."""
    statuses = {c.status for c in checks}
    missing = [key for key, _ in required if key not in {c.key for c in checks}]
    value: VerdictValue
    if "failed" in statuses:
        value = "NOT PROVEN"
    elif "not_checked" in statuses or missing:
        value = "PARTLY PROVEN"
    else:
        value = "PROVEN"
    notes = list(not_proven) + [f"{c.title}: {c.detail}" for c in checks if c.status == "not_checked"]
    notes += [f"{_TITLES[key]}: not run" for key in missing]
    return Verdict(module, value, list(checks), notes)


# -- independent validation (ADR-0025) ----------------------------------------------------------------------------
def target_runs(ready: bool, diagnostic: str) -> Check:
    if not ready:
        return Check("target_runs", "failed", f"the target did not run: {diagnostic}"[:1000])
    return Check("target_runs", "passed", f"the target started in the sandbox and answered; {diagnostic}")


def contract_mapped(problems: Sequence[str], approved: bool) -> Check:
    if problems:
        detail = f"{len(problems)} problem(s) in the mapping: {'; '.join(problems[:4])}"[:1000]
        return Check("contract_mapped", "failed", detail, {"problems": list(problems)})
    if not approved:
        return Check("contract_mapped", "not_checked", "the mapping was not approved at C2")
    return Check("contract_mapped", "passed", "the approved mapping covers every input, output, table and call")


def rules_covered(traces: Sequence[RuleTrace]) -> Check:
    """Every approved legacy rule needs a golden case the target reproduced (every priority: IV&V judges the whole)."""
    missing = [t.rule for t in traces if not t.verified]
    evidence = {"verified": [t.rule for t in traces if t.verified], "unverified": missing}
    if not traces:
        return Check("rules_covered", "not_checked", "there are no approved rules", evidence)
    if missing:
        return Check("rules_covered", "failed", f"rules the target does not reproduce: {', '.join(missing)}", evidence)
    return Check(
        "rules_covered", "passed", f"{len(traces)} of {len(traces)} rule(s) reproduced by the target", evidence
    )


# -- delta on an existing application (ADR-0026) -------------------------------------------------------------------
def regression(baseline: Sequence[str], passed: Sequence[str], report_found: bool) -> Check:
    """Every test that passed in the baseline (the application before the delta) passes after it."""
    if not report_found:
        return Check("regression", "failed", "the tests of the extended application did not run (no JUnit report)")
    if not baseline:
        return Check("regression", "not_checked", "the application had no passing test before the delta",
                     {"baseline": []})  # fmt: skip
    broken = sorted(set(baseline) - set(passed))
    evidence = {"baseline": len(baseline), "broken": broken}
    if broken:
        return Check("regression", "failed", f"{len(broken)} test(s) that passed before fail now: "
                     f"{', '.join(broken[:5])}"[:1000], evidence)  # fmt: skip
    return Check("regression", "passed", f"the {len(baseline)} test(s) of the baseline still pass", evidence)


def contract_kept(endpoints: Sequence[str], broken: Sequence[str]) -> Check:
    """Every endpoint of the application before the delta keeps its method, path and request fields."""
    if not endpoints:
        return Check("contract_kept", "not_checked", "the application had no endpoint before the delta")
    evidence = {"endpoints": list(endpoints), "broken": list(broken)}
    if broken:
        return Check("contract_kept", "failed", f"endpoints changed or removed: {'; '.join(broken[:5])}"[:1000],
                     evidence)  # fmt: skip
    return Check("contract_kept", "passed", f"the {len(endpoints)} existing endpoint(s) are kept", evidence)


def fitness(violations: Sequence[str]) -> Check:
    """The delta's architecture rules: no file deleted, no existing test or build file touched, no SQL in a
    controller."""
    if violations:
        return Check("fitness", "failed", f"{len(violations)} violation(s): {'; '.join(violations[:5])}"[:1000],
                     {"violations": list(violations)})  # fmt: skip
    return Check("fitness", "passed", "the delta respects the application's architecture rules", {"violations": []})
