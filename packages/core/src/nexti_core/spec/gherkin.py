"""Validation of the acceptance criteria of user stories (spec 7.7, D-26): each criterion is one Gherkin scenario,
checked by code, the same in the browser and on the server. Keywords are accepted in English and Spanish.

The validation is of form: that the scenario describes the rule well is reviewed by a person, and that it holds is
proven by the test generated from it.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

Code = Literal[
    "missing_header",
    "missing_name",
    "missing_given",
    "missing_when",
    "missing_then",
    "continuation_first",
    "out_of_order",
    "two_behaviours",
    "empty_step",
    "free_text",
    "missing_examples",
    "empty_examples",
    "unknown_placeholder",
    "duplicate_name",
    "empty",
]

MESSAGES: dict[str, str] = {
    "missing_header": "The scenario must start with 'Scenario:' or 'Scenario Outline:' (or 'Escenario:').",
    "missing_name": "The scenario needs a name after the keyword.",
    "missing_given": "The scenario needs at least one Given step.",
    "missing_when": "The scenario needs at least one When step.",
    "missing_then": "The scenario needs at least one Then step.",
    "continuation_first": "And/But can only continue a previous step.",
    "out_of_order": "Steps must go Given, then When, then Then.",
    "two_behaviours": "A Given or When after a Then describes a second behaviour: split the scenario.",
    "empty_step": "A step has a keyword and no text.",
    "free_text": "Every line must be a step, a table row, a doc string, a comment or a tag.",
    "missing_examples": "A Scenario Outline needs an Examples table.",
    "empty_examples": "The Examples table needs a header and at least one row.",
    "unknown_placeholder": "A <placeholder> is not a column of the Examples table.",
    "duplicate_name": "Two scenarios of the story have the same name.",
    "empty": "The criterion is empty.",
}

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "outline": ("Scenario Outline", "Scenario Template", "Esquema del escenario"),
    "scenario": ("Scenario", "Example", "Escenario", "Ejemplo"),
    "examples": ("Examples", "Scenarios", "Ejemplos"),
    "given": ("Given", "Dado", "Dada", "Dados", "Dadas"),
    "when": ("When", "Cuando"),
    "then": ("Then", "Entonces"),
    "and": ("And", "Y", "E"),
    "but": ("But", "Pero"),
}
_ORDER = {"given": 0, "when": 1, "then": 2}
_PLACEHOLDER = re.compile(r"<([^<>\s][^<>]*)>")


@dataclass(frozen=True)
class Problem:
    code: Code
    line: int  # 1-based line of the criterion text (0 for the whole criterion)
    message: str

    @staticmethod
    def of(code: Code, line: int = 0) -> "Problem":
        return Problem(code, line, MESSAGES[code])


def _header(line: str) -> tuple[str, str] | None:
    """('outline'|'scenario', name) when the line is a scenario header."""
    for kind in ("outline", "scenario"):
        for keyword in _KEYWORDS[kind]:
            if line.lower().startswith(keyword.lower() + ":"):
                return kind, line[len(keyword) + 1 :].strip()
    return None


def _step(line: str) -> tuple[str, str] | None:
    """(kind, text) when the line starts with a step keyword followed by a space (or nothing)."""
    for kind in ("given", "when", "then", "and", "but"):
        for keyword in _KEYWORDS[kind]:
            if line == keyword or line.startswith(keyword + " "):
                return kind, line[len(keyword) :].strip()
    return None


def _is_examples(line: str) -> bool:
    return any(line.lower().startswith(k.lower() + ":") for k in _KEYWORDS["examples"])


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def scenario_name(text: str) -> str | None:
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith(("#", "@")):
            header = _header(line)
            return header[1] if header else None
    return None


def validate_scenario(text: str) -> list[Problem]:
    """The problems of one criterion; an empty list means it can be saved."""
    lines = text.splitlines()
    if not any(line.strip() for line in lines):
        return [Problem.of("empty")]
    problems: list[Problem] = []
    kind: str | None = None
    seen = {"given": False, "when": False, "then": False}
    last_main: str | None = None
    in_doc = False
    examples_header: list[str] | None = None
    examples_rows = 0
    in_examples = False
    placeholders: list[tuple[str, int]] = []
    header_seen = False

    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if in_doc:
            if line.startswith(('"""', "```")):
                in_doc = False
            continue
        if not line or line.startswith(("#", "@")):
            continue
        if not header_seen:
            header = _header(line)
            if header is None:
                problems.append(Problem.of("missing_header", number))
                return problems
            header_seen = True
            kind, name = header
            if not name:
                problems.append(Problem.of("missing_name", number))
            continue
        if line.startswith(('"""', "```")):
            in_doc = True
            continue
        if line.startswith("|"):
            if in_examples:
                if examples_header is None:
                    examples_header = _cells(line)
                else:
                    examples_rows += 1
            continue
        if _is_examples(line):
            in_examples = True
            continue
        if in_examples:
            problems.append(Problem.of("free_text", number))
            continue
        step = _step(line)
        if step is None:
            problems.append(Problem.of("free_text", number))
            continue
        step_kind, step_text = step
        if not step_text:
            problems.append(Problem.of("empty_step", number))
        placeholders += [(p, number) for p in _PLACEHOLDER.findall(step_text)]
        if step_kind in ("and", "but"):
            if last_main is None:
                problems.append(Problem.of("continuation_first", number))
            continue
        if last_main == "then" and step_kind in ("given", "when"):
            problems.append(Problem.of("two_behaviours", number))
        elif last_main is not None and _ORDER[step_kind] < _ORDER[last_main]:
            problems.append(Problem.of("out_of_order", number))
        seen[step_kind] = True
        last_main = step_kind

    for step_kind, code in (("given", "missing_given"), ("when", "missing_when"), ("then", "missing_then")):
        if not seen[step_kind]:
            problems.append(Problem.of(code))  # type: ignore[arg-type]
    if kind == "outline":
        if not in_examples:
            problems.append(Problem.of("missing_examples"))
        elif examples_header is None or examples_rows == 0:
            problems.append(Problem.of("empty_examples"))
        else:
            columns = set(examples_header)
            problems += [Problem.of("unknown_placeholder", n) for p, n in placeholders if p.strip() not in columns]
    return problems


def validate_criteria(criteria: Sequence[str]) -> dict[int, list[Problem]]:
    """Problems by criterion index for a whole story, including duplicate scenario names."""
    result = {i: validate_scenario(text) for i, text in enumerate(criteria)}
    names: dict[str, int] = {}
    for i, text in enumerate(criteria):
        name = scenario_name(text)
        if not name:
            continue
        key = name.casefold()
        if key in names:
            result[i].append(Problem.of("duplicate_name"))
        else:
            names[key] = i
    return {i: problems for i, problems in result.items() if problems}


def is_valid(criteria: Iterable[str]) -> bool:
    return not validate_criteria(list(criteria))
