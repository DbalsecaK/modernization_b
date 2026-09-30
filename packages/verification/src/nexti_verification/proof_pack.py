"""The proof pack (spec 11.3, 6.1 phase 11): the evidence of a verdict in one archive a reviewer can keep and
recompute. It holds the verdict with its checks and what it does not prove, every case with its differences, the
rule by rule comparison of source and target, the raw JUnit report and the canary attempts. Built by code only."""

import io
import json
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from nexti_verification.verdict import CaseOutcome, RuleTrace, Verdict

_FIXED_TIME = (2026, 1, 1, 0, 0, 0)  # entries carry a fixed time: the same evidence gives the same archive


def _json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _outcomes(outcomes: Sequence[CaseOutcome]) -> list[dict[str, Any]]:
    return [
        {
            "name": o.name,
            "rules": list(o.rules),
            "matched": o.matched,
            "failure": o.failure,
            "differences": [asdict(d) for d in o.differences],
        }
        for o in outcomes
    ]


def verification_document(verdict: Verdict, computed_at: datetime | None = None) -> dict[str, Any]:
    return {
        "module": verdict.module,
        "verdict": verdict.verdict,
        "checks": [
            {"key": c.key, "title": c.title, "status": c.status, "detail": c.detail, "evidence": dict(c.evidence)}
            for c in verdict.checks
        ],
        "not_proven": verdict.not_proven,
        "computed_at": (computed_at or datetime.now(UTC)).isoformat(timespec="seconds"),
        "computed_by": "nexti_verification (fixed rules, spec 11.3)",
    }


def build_proof_pack(
    verdict: Verdict,
    golden: Sequence[CaseOutcome],
    fresh: Sequence[CaseOutcome] | None,
    traces: Sequence[RuleTrace],
    junit_xml: str,
    extra: Mapping[str, Any] | None = None,
    computed_at: datetime | None = None,
) -> bytes:
    documents: dict[str, bytes] = {
        "VERIFICATION.json": _json(verification_document(verdict, computed_at)),
        "EQUIVALENCE.json": _json(
            {"golden_master": _outcomes(golden), "fresh_inputs": _outcomes(fresh) if fresh is not None else None}
        ),
        "TRACE.json": _json([{**asdict(t), "verified": t.verified} for t in traces]),
        "junit.xml": junit_xml.encode("utf-8"),
    }
    for name, value in (extra or {}).items():
        documents[name] = value if isinstance(value, bytes) else _json(value)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(documents):
            archive.writestr(zipfile.ZipInfo(name, _FIXED_TIME), documents[name])
    return buffer.getvalue()
