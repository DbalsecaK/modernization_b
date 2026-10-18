"""Independent verification of a migrated module (spec 11.3): the verdict is computed by code with fixed rules from
evidence produced by runs, never from what an agent says. Language neutral: it works on observations of the
characterization model (`nexti_core.spec.characterization`), JUnit counts and the rules of the spec.

- `compare`: differences between what the legacy did and what the target did, field by field.
- `fresh`: new inputs derived from the golden master, run on both sides.
- `verdict`: the six checks and PROVEN / PARTLY PROVEN / NOT PROVEN, with what the verdict does not prove.
- `proof_pack`: the evidence in one archive, and the rule by rule comparison of source and target."""

from nexti_verification.certainty import Certainty, Component, compute_certainty
from nexti_verification.compare import Difference, differences
from nexti_verification.fresh import fresh_suite
from nexti_verification.proof_pack import build_proof_pack
from nexti_verification.report import ReportItems, SubstituteAnswer, programmer_report
from nexti_verification.verdict import (
    CHECKS,
    CaseOutcome,
    Check,
    CheckStatus,
    RuleTrace,
    Verdict,
    compute,
    trace_rules,
)

__all__ = [
    "CHECKS",
    "CaseOutcome",
    "Certainty",
    "Check",
    "CheckStatus",
    "Component",
    "Difference",
    "ReportItems",
    "RuleTrace",
    "SubstituteAnswer",
    "Verdict",
    "build_proof_pack",
    "compute",
    "compute_certainty",
    "differences",
    "fresh_suite",
    "programmer_report",
    "trace_rules",
]
