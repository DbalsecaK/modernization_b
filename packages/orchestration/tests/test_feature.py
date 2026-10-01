"""Flow 2, analysis half (spec 7.2 phases 1-3, ADR-0018), on the fictitious "Simulador de crédito": code checks every
citation, the Gherkin and the coverage of what the analyst answers, and finds the gaps of 7.3; each gap becomes a
question whose recommended answer is applied when a person answers."""

import json

import pytest

from nexti_core.spec.model import Rule
from nexti_core.spec.screens import ScreenSpec
from nexti_orchestration.extraction import ReplyError
from nexti_orchestration.feature import (
    FeatureStory,
    apply_gaps,
    gaps,
    numbered,
    parse_contradictions,
    parse_normalized,
    stories_of,
)
from nexti_orchestration.model import Answer

from .feature_example import FIGMA, FIGMA_FILE, INPUTS, normalized


def test_the_inputs_go_to_the_agent_with_numbered_lines() -> None:
    text = numbered(INPUTS)
    assert "=== docs/requisitos.md (" in text
    assert f"=== figma/{FIGMA_FILE} (" in text
    assert f"figma/{FIGMA_FILE}.json" not in text  # the raw file is evidence, not citable
    assert " 1| # Simulador de crédito de consumo — Requisitos" in text


def test_a_valid_answer_becomes_the_specification() -> None:
    result = parse_normalized(json.dumps(normalized()), INPUTS)
    assert [r.id for r in result.rules] == [f"RULE-00{i}" for i in range(1, 7)]
    assert [s.id for s in result.screens] == ["SCR-SIMULADOR", "SCR-RESULTADO"]
    assert str(result.rules[0].sources[0]).startswith("docs/requisitos.md:")
    assert len(result.stories) == 2
    assert result.stories[0].criteria[0].startswith("Escenario: Cuota de un crédito a 12 meses")
    plan = stories_of(result.stories)
    assert (plan.origin, plan.waves) == ("document", [["US-001", "US-002"]])


def test_citations_gherkin_and_coverage_are_checked_by_code() -> None:
    answer = normalized()
    answer["rules"][0]["sources"] = ["docs/requisitos.md:900-901"]
    answer["rules"][1]["sources"] = ["docs/otro.md:1"]
    answer["stories"][1]["criteria"] = ["Escenario: sin pasos"]
    answer["stories"][1]["links"] = ["RULE-099"]
    with pytest.raises(ReplyError) as problems:
        parse_normalized(json.dumps(answer), INPUTS)
    text = str(problems.value)
    assert "RULE-001: cites docs/requisitos.md:900-901, but docs/requisitos.md has" in text
    assert "RULE-002: cites docs/otro.md, which is not an input" in text
    assert "story 2 'Guardar cada simulación', criterion 1:" in text
    assert "links elements that do not exist: RULE-099" in text
    assert "these rules and screens are in no story: RULE-006" in text


def _spec() -> tuple[list[ScreenSpec], list[Rule], list[FeatureStory]]:
    result = parse_normalized(json.dumps(normalized()), INPUTS)
    stories = [FeatureStory(f"US-00{i}", d.title, d.criteria, d.links, "review")
               for i, d in enumerate(result.stories, start=1)]  # fmt: skip
    return result.screens, result.rules, stories


def test_the_gaps_of_7_3_are_found_by_code() -> None:
    screens, rules, stories = _spec()
    found = {g.key: g for g in gaps(screens, rules, stories, [(FIGMA_FILE, FIGMA)])}
    assert set(found) == {
        "gap-validation-SCR-SIMULADOR",  # monto and plazo have no validation
        "gap-states-SCR-SIMULADOR",  # an input screen without error and empty states
        f"gap-button-{FIGMA_FILE}-2-8",  # "Botón Descargar PDF" navigates nowhere
    }
    assert found[f"gap-button-{FIGMA_FILE}-2-8"].affects == ("SCR-RESULTADO",)
    assert found["gap-validation-SCR-SIMULADOR"].recommended.key == "validate"


def test_the_recommended_answers_are_applied() -> None:
    screens, rules, stories = _spec()
    found = gaps(screens, rules, stories, [(FIGMA_FILE, FIGMA)])
    answers = {g.key: Answer(g.recommended.key, g.recommended.label) for g in found}
    fixed, kept = apply_gaps(answers, found, screens, rules, [(FIGMA_FILE, FIGMA)])
    simulator, result = fixed
    assert all(f.required and f.validation for f in simulator.inputs())
    assert set(simulator.states) == {"error", "empty"}
    assert [a.key for a in result.actions] == ["nueva"]  # the dead button left the screen
    assert kept == rules
    assert gaps(fixed, kept, stories, []) == []


def test_a_person_may_keep_the_gap() -> None:
    screens, rules, stories = _spec()
    found = gaps(screens, rules, stories, [(FIGMA_FILE, FIGMA)])
    answers = {g.key: Answer(g.alternative.key, g.alternative.label) for g in found}
    fixed, _ = apply_gaps(answers, found, screens, rules, [(FIGMA_FILE, FIGMA)])
    assert fixed == screens


def test_a_contradiction_must_cite_both_sides_and_known_elements() -> None:
    known = {"RULE-001", "SCR-SIMULADOR"}
    sources = ["docs/requisitos.md:13", f"figma/{FIGMA_FILE}:13"]
    good = {"contradictions": [{"text": "El mensaje difiere", "sources": sources, "affects": ["RULE-001"],
                                "recommended": "El del documento", "alternative": "El de Figma"}]}  # fmt: skip
    (found,) = parse_contradictions(json.dumps(good), INPUTS, known)
    assert found.affects == ("RULE-001",)
    bad = {"contradictions": [{"text": "x", "sources": ["docs/nada.md:1"], "affects": ["RULE-404"],
                               "recommended": "y"}]}  # fmt: skip
    with pytest.raises(ReplyError, match="RULE-404"):
        parse_contradictions(json.dumps(bad), INPUTS, known)
    assert parse_contradictions('{"contradictions": []}', INPUTS, known) == []
