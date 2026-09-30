"""Which executor runs each phase in this version (plan M3 decision 3, M4). Real pipelines have the preflight and,
when the worker gives them a project port, the analysis phases of the modernization flow (M4); the other phases
arrive with the next steps and, until then, the run waits in them. Demo runs have deterministic executors for every
phase."""

from collections.abc import Mapping
from typing import Protocol, cast

from nexti_orchestration.characterization import CharacterizationPhases, CharacterizationPort
from nexti_orchestration.demo import demo_executors
from nexti_orchestration.generation import GenerationPhases, GenerationPort
from nexti_orchestration.graph import Executor
from nexti_orchestration.model import RunContext
from nexti_orchestration.modernization import ModernizationPhases, ProjectPort
from nexti_orchestration.preflight import Preflight, PreflightProbe
from nexti_orchestration.verification import VerificationPhases, VerificationPort


class PipelinePort(ProjectPort, GenerationPort, Protocol):
    """What the worker gives the executors of a real pipeline."""


def executors_for(
    run: RunContext, probe: PreflightProbe, port: ProjectPort | PipelinePort | None = None
) -> Mapping[str, Executor]:
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
        if hasattr(port, "legacy_runner"):  # a port that can also run the legacy for the golden master
            characterization = CharacterizationPhases(cast(CharacterizationPort, port))
            executors["characterization"] = characterization.characterization
        if hasattr(port, "save_design"):  # a port that can also keep designs and generated files
            generation = GenerationPhases(cast(GenerationPort, port))
            executors.update({"design": generation.design, "generation": generation.generation})
        if hasattr(port, "save_verdict"):  # a port that can also keep verdicts and proof packs
            executors["verification"] = VerificationPhases(cast(VerificationPort, port)).verification
    return executors
