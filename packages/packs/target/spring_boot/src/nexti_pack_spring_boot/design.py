"""The design, now neutral in `nexti_core.spec.design` (ADR-0017); re-exported for the Java pack's callers."""

from nexti_core.spec.design import (
    Decision,
    Design,
    DesignModel,
    Entity,
    EquivalenceMask,
    ErrorSpec,
    FieldSpec,
    JavaName,
    Port,
    PortMethod,
    UseCase,
)

__all__ = [
    "Decision", "Design", "DesignModel", "Entity", "EquivalenceMask", "ErrorSpec", "FieldSpec", "JavaName", "Port",
    "PortMethod", "UseCase",
]  # fmt: skip
