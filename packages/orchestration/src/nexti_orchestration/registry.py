"""Which executor runs each phase in this version (plan M3 decision 3, M4). Real pipelines have the preflight and,
when the worker gives them a project port, the analysis phases of the modernization flow (M4); the other phases
arrive with the next steps and, until then, the run waits in them. Demo runs have deterministic executors for every
phase."""

from collections.abc import Mapping
from typing import Protocol, cast

from nexti_orchestration.characterization import CharacterizationPhases, CharacterizationPort
from nexti_orchestration.demo import demo_executors
from nexti_orchestration.feature import FeaturePhases, FeaturePort
from nexti_orchestration.feature_build import FeatureBuildPhases, FeatureBuildPort
from nexti_orchestration.generation import GenerationPhases, GenerationPort
from nexti_orchestration.graph import Executor
from nexti_orchestration.ivv import IvvPhases, IvvPort
from nexti_orchestration.model import RunContext
from nexti_orchestration.modernization import ModernizationPhases, ProjectPort
from nexti_orchestration.preflight import Preflight, PreflightProbe
from nexti_orchestration.release import ReleasePhases, ReleasePort
from nexti_orchestration.ui import UiPhases, UiPort
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
        if hasattr(port, "save_prototype"):  # a port that can also keep screens and prototypes (M5)
            executors["ui"] = UiPhases(cast(UiPort, port)).ui
        if hasattr(port, "legacy_runner"):  # a port that can also run the legacy for the golden master
            characterization = CharacterizationPhases(cast(CharacterizationPort, port))
            executors["characterization"] = characterization.characterization
        if hasattr(port, "save_design"):  # a port that can also keep designs and generated files
            generation = GenerationPhases(cast(GenerationPort, port))
            executors.update({"design": generation.design, "generation": generation.generation})
        if hasattr(port, "save_verdict"):  # a port that can also keep verdicts and proof packs
            executors["verification"] = VerificationPhases(cast(VerificationPort, port)).verification
        if hasattr(port, "save_release"):  # hardening and delivery (M9a, ADR-0023)
            release = ReleasePhases(cast(ReleasePort, port))
            executors.update({"hardening": release.hardening, "delivery": release.delivery})
    if port is not None and run.flow == "newFeature" and hasattr(port, "documents"):  # Flow 2 (M7)
        feature = FeaturePhases(cast(FeaturePort, port))
        build = FeatureBuildPhases(cast(FeatureBuildPort, port))
        generation = GenerationPhases(cast(GenerationPort, port))
        executors.update({
            "ingestion": feature.ingestion,
            "normalization": feature.normalization,
            "consolidation": feature.consolidation,
            "specReview": build.spec_review,
            "ui": UiPhases(cast(UiPort, port)).ui,
            "design": generation.design,
            "generation": generation.generation,
            "validation": build.validation,
            "delivery": build.delivery,
        })  # fmt: skip
        if hasattr(port, "save_release"):
            executors["delivery"] = ReleasePhases(cast(ReleasePort, port)).delivery
    if port is not None and run.flow == "independentValidation":  # Flow 4 (M10, ADR-0025)
        phases = ModernizationPhases(port)
        executors.update({"inventory": phases.inventory, "ruleExtraction": phases.rule_extraction,
                          "ruleReview": phases.rule_review})  # fmt: skip
        if hasattr(port, "legacy_runner"):
            executors["characterization"] = CharacterizationPhases(cast(CharacterizationPort, port)).characterization
        if hasattr(port, "target_archive"):
            ivv = IvvPhases(cast(IvvPort, port))
            executors.update({
                "targetIntake": ivv.target_intake, "mapping": ivv.mapping, "targetRules": ivv.target_rules,
                "validation": ivv.validation, "report": ivv.report,
            })  # fmt: skip
    return executors
