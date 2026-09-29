"""Which executor runs each phase in this version (plan M3 decision 3, M4). Real pipelines have the preflight and,
when the worker gives them a project port, the analysis phases of the modernization flow (M4); the other phases
arrive with the next steps and, until then, the run waits in them. Demo runs have deterministic executors for every
phase."""

from collections.abc import Mapping

from nexti_orchestration.demo import demo_executors
from nexti_orchestration.graph import Executor
from nexti_orchestration.model import RunContext
from nexti_orchestration.modernization import ModernizationPhases, ProjectPort
from nexti_orchestration.preflight import Preflight, PreflightProbe


def executors_for(run: RunContext, probe: PreflightProbe, port: ProjectPort | None = None) -> Mapping[str, Executor]:
    if run.kind == "demo":
        return demo_executors(run)
    executors: dict[str, Executor] = {"preflight": Preflight(probe)}
    if port is not None and run.flow == "modernization":
        phases = ModernizationPhases(port)
        executors.update({
            "inventory": phases.inventory,
            "domains": phases.domains,
            "classification": phases.classification,
            "ruleExtraction": phases.rule_extraction,
            "ruleReview": phases.rule_review,
            "ui": phases.ui,
        })  # fmt: skip
    return executors
