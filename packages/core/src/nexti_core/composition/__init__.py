"""Project composition: the catalog model and the deterministic recommendation and validation engine."""

from nexti_core.composition.engine import Evaluation, MissingSkill, Problem, Recommendation, evaluate
from nexti_core.composition.loader import build_catalog, core_data
from nexti_core.composition.model import AXES, FLOWS, Catalog, Request, Target

__all__ = [
    "AXES",
    "FLOWS",
    "Catalog",
    "Evaluation",
    "MissingSkill",
    "Problem",
    "Recommendation",
    "Request",
    "Target",
    "build_catalog",
    "core_data",
    "evaluate",
]
