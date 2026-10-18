"""The certainty index of a verdict (ADR-0056, point 6): what share of the behaviour of the legacy the evidence
covers, computed from the artefacts of the run with declared weights, never estimated by a model. It comes with its
frontier: the components that are not complete, in one sentence, so the customer reads the number and its limit
together. PROVEN still needs every check; the index says how far PARTLY PROVEN is from it and why."""

from dataclasses import dataclass
from typing import Any, Literal

Engine = Literal["customer", "same_local", "other", "traces", "none"]

# The weights, declared (they sum 100). The golden master is the core of the proof; the rest measures how much of
# what the legacy does the golden master was able to ask about.
WEIGHTS: dict[str, int] = {
    "cases_matched": 35,
    "target_coverage": 10,
    "rollbacks_with_case": 10,
    "quirks_with_case": 10,
    "called_programs_real": 10,
    "omitted_vs_null": 5,
    "concurrency": 5,
    "contract": 5,
    "engine": 10,
}
assert sum(WEIGHTS.values()) == 100  # noqa: S101 - a declared invariant of the index

# How much the engine the target was verified on is worth: the customer's own engine proves the most; the same
# product in a local container almost as much; another engine (GnuCOBOL for COBOL) proves the logic but not the
# product; recorded traces only the traced cases; nothing observed proves nothing.
ENGINE_RATIO: dict[str, float] = {"customer": 1.0, "same_local": 0.8, "other": 0.5, "traces": 0.3, "none": 0.0}

_ENGINE_TEXT = {
    "customer": ("el motor del cliente", "the customer's engine"),
    "same_local": ("el mismo motor, en local", "the same engine, locally"),
    "other": ("otro motor", "another engine"),
    "traces": ("solo trazas grabadas", "recorded traces only"),
    "none": ("sin observar", "not observed"),
}


@dataclass(frozen=True)
class Component:
    key: str
    weight: int
    ratio: float  # 0..1, how complete this component is
    detail_es: str
    detail_en: str

    @property
    def score(self) -> float:
        return self.weight * max(0.0, min(1.0, self.ratio))

    def as_json(self) -> dict[str, Any]:
        return {"key": self.key, "weight": self.weight, "ratio": round(self.ratio, 4), "score": round(self.score, 2),
                "detail_es": self.detail_es, "detail_en": self.detail_en}  # fmt: skip


@dataclass(frozen=True)
class Certainty:
    percent: int
    components: list[Component]
    frontier_es: str
    frontier_en: str

    def as_json(self) -> dict[str, Any]:
        return {"percent": self.percent, "components": [c.as_json() for c in self.components],
                "frontier_es": self.frontier_es, "frontier_en": self.frontier_en}  # fmt: skip


def _ratio(part: int, whole: int, when_empty: float = 1.0) -> float:
    return when_empty if whole <= 0 else part / whole


def compute_certainty(
    *,
    cases_matched: int,
    cases_total: int,
    target_lines_covered: int | None,
    target_lines_total: int | None,
    rollbacks_total: int,
    rollbacks_without_case: int,
    quirks_confirmed: int,
    quirks_without_case: int,
    called_programs: int,
    substituted_programs: int,
    omitted_vs_null: bool,
    concurrency_case: bool,
    contract_exercised: bool,
    engine: Engine,
) -> Certainty:
    """The index from the measures of the run. Every measure is a count the platform made (cases, lines, rollback
    points, quirks, called programs) or a fact of how the run was made (what distinguished omitted from NULL, whether
    a concurrency case and endpoint cases ran, on which engine)."""
    covered = (target_lines_covered or 0, target_lines_total or 0)
    yes_no = {True: ("sí", "yes"), False: ("no", "no")}
    components = [
        Component("cases_matched", WEIGHTS["cases_matched"], _ratio(cases_matched, cases_total, 0.0),
                  f"casos del golden master que coinciden: {cases_matched} de {cases_total}",
                  f"golden master cases that match: {cases_matched} of {cases_total}"),
        Component("target_coverage", WEIGHTS["target_coverage"],
                  _ratio(*covered, 0.0) if target_lines_total else 0.0,
                  f"líneas del destino ejecutadas por el golden master: {covered[0]} de {covered[1]}"
                  if target_lines_total else "líneas del destino ejecutadas por el golden master: no medidas",
                  f"target lines run by the golden master: {covered[0]} of {covered[1]}"
                  if target_lines_total else "target lines run by the golden master: not measured"),
        Component("rollbacks_with_case", WEIGHTS["rollbacks_with_case"],
                  _ratio(rollbacks_total - rollbacks_without_case, rollbacks_total),
                  f"puntos de rollback con caso: {rollbacks_total - rollbacks_without_case} de {rollbacks_total}",
                  f"rollback points with a case: {rollbacks_total - rollbacks_without_case} of {rollbacks_total}"),
        Component("quirks_with_case", WEIGHTS["quirks_with_case"],
                  _ratio(quirks_confirmed - quirks_without_case, quirks_confirmed),
                  f"peculiaridades del motor con caso: {quirks_confirmed - quirks_without_case} de {quirks_confirmed}",
                  f"engine quirks with a case: {quirks_confirmed - quirks_without_case} of {quirks_confirmed}"),
        Component("called_programs_real", WEIGHTS["called_programs_real"],
                  _ratio(called_programs - substituted_programs, called_programs),
                  f"programas llamados reales: {called_programs - substituted_programs} de {called_programs}",
                  f"called programs real: {called_programs - substituted_programs} of {called_programs}"),
        Component("omitted_vs_null", WEIGHTS["omitted_vs_null"], 1.0 if omitted_vs_null else 0.0,
                  f"«omitido» distinguible de «NULL» en las llamadas: {yes_no[omitted_vs_null][0]}",
                  f"omitted told apart from NULL in the calls: {yes_no[omitted_vs_null][1]}"),
        Component("concurrency", WEIGHTS["concurrency"], 1.0 if concurrency_case else 0.0,
                  f"caso de concurrencia: {yes_no[concurrency_case][0]}",
                  f"concurrency case: {yes_no[concurrency_case][1]}"),
        Component("contract", WEIGHTS["contract"], 1.0 if contract_exercised else 0.0,
                  f"contrato de entrada ejercitado por el oráculo: {yes_no[contract_exercised][0]}",
                  f"input contract exercised by the oracle: {yes_no[contract_exercised][1]}"),
        Component("engine", WEIGHTS["engine"], ENGINE_RATIO[engine],
                  f"motor de verificación: {_ENGINE_TEXT[engine][0]}",
                  f"verification engine: {_ENGINE_TEXT[engine][1]}"),
    ]  # fmt: skip
    percent = round(sum(c.score for c in components))
    if engine == "none" or cases_total == 0:
        percent = 0  # nothing observed proves nothing, whatever the other components say
    short = [c for c in components if c.ratio < 1.0]
    frontier_es = (f"{percent} %: " + ("completo en todos los componentes" if not short else
                   "sin completar: " + "; ".join(c.detail_es for c in short)))  # fmt: skip
    frontier_en = (f"{percent}%: " + ("complete in every component" if not short else
                   "not complete: " + "; ".join(c.detail_en for c in short)))  # fmt: skip
    return Certainty(percent, components, frontier_es, frontier_en)
