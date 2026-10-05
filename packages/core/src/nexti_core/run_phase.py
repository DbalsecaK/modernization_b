"""The phase a worker task is executing, for the stores that record what a phase produced (ADR-0035): a retried
phase replaces its own files and nothing else. The graph sets it before it calls the phase's executor."""

from contextvars import ContextVar

CURRENT_PHASE: ContextVar[str] = ContextVar("nexti_current_phase", default="")
