"""Phases of the flows and agent roles (spec 6.1, 7.2, 9.3): the axes of the model assignment matrix (12.5).
Keys match the prototype (`apps/web`)."""

# Flow 1 (modernization), flow 2 (new feature from documents) and flow 4 (independent validation, ADR-0025).
PHASES: tuple[str, ...] = (
    "preflight",
    "inventory",
    "domains",
    "classification",
    "ruleExtraction",
    "ruleReview",
    "ui",
    "design",
    "characterization",
    "generation",
    "verification",
    "hardening",
    "delivery",
    "ingestion",
    "normalization",
    "consolidation",
    "specReview",
    "validation",
    "targetIntake",
    "mapping",
    "targetRules",
    "report",
)

AGENT_ROLES: tuple[str, ...] = (
    "legacy-analyst",
    "rules-extractor",
    "data-analyst",
    "ui-analyst",
    "functional-analyst",
    "solution-architect",
    "data-architect",
    "ux-designer",
    "backend-dev",
    "frontend-dev",
    "fullstack-dev",
    "data-migration",
    "devops",
    "test-engineer",
    "code-reviewer",
    "security-auditor",
    "rules-verifier",
    "equivalence-validator",
    "acceptance-judge",
)

# Label of the ledger rows produced by "test profile" in the AI configuration screen.
TEST_PHASE = "connection-test"
