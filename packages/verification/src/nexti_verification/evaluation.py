"""Evaluation against a reference spec (spec 21.3, 21.4): the rules the platform extracted, compared by code with
the rules an expert wrote for a reference application.

- **Omissions:** reference rules no extracted rule matches (the most serious metric; P0 omissions apart).
- **Hallucinations:** extracted rules that match no reference rule.
- **Precision errors:** matched rules that lack a concrete value of the reference (a code, an amount, a limit).

A match is one to one, best first, on where the rule is (overlap of line ranges in the same file) and what it says
(shared words). The reference comes from a kit outside the repository (ADR-0011): metrics keep its name and
SHA-256, never its content. It may be JSON (the spec model of rules) or rule cards in Markdown."""

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any

from nexti_core.spec.model import Rule

MATCH_THRESHOLD = 0.3
_WORD = re.compile(r"[a-záéíóúñ0-9]+", re.IGNORECASE)
_QUOTED = re.compile(r"'([^']{1,40})'")
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w])")
_CODE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
_NOT_CODES = {"AND", "OR", "NOT", "NULL", "IF", "THEN", "WHEN", "GIVEN", "ELSE", "SCENARIO", "EXAMPLES", "THE",
              "IS", "IN", "SELECT", "FROM", "WHERE", "UPDATE", "SET", "INSERT", "BEGIN", "END", "RULE"}  # fmt: skip
_STOP = {"the", "a", "an", "of", "to", "and", "or", "is", "are", "be", "in", "on", "for", "with", "by", "it", "its",
         "that", "this", "as", "at", "from", "not", "no", "el", "la", "de", "y", "o", "en", "que"}  # fmt: skip
_CARD = re.compile(r"^###\s+(RULE-\d{3,}):\s*(.+)$", re.MULTILINE)
_SOURCE = re.compile(r"`?([^`\s:]+):(\d+)(?:-(\d+))?`?")


@dataclass(frozen=True)
class ReferenceRule:
    id: str
    name: str
    priority: str
    text: str  # statement, condition, result and scenarios: what the expert wrote
    file: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    values: tuple[str, ...] = ()


@dataclass(frozen=True)
class Reference:
    name: str
    sha256: str
    rules: list[ReferenceRule]
    written_blind: bool = True  # written before seeing any extraction (21.2)


@dataclass
class Evaluation:
    reference: str
    reference_sha256: str
    reference_rules: int
    found_rules: int
    matched: list[tuple[str, str]] = field(default_factory=list)  # (reference id, found id)
    omissions: list[str] = field(default_factory=list)
    omissions_p0: list[str] = field(default_factory=list)
    hallucinations: list[str] = field(default_factory=list)
    precision_errors: list[dict[str, Any]] = field(default_factory=list)
    known_bias: str | None = None

    @property
    def recall(self) -> float:
        return round(len(self.matched) / self.reference_rules, 3) if self.reference_rules else 0.0

    @property
    def precision(self) -> float:
        return round(len(self.matched) / self.found_rules, 3) if self.found_rules else 0.0

    def metrics(self) -> dict[str, Any]:
        data = asdict(self)
        data["matched"] = [list(pair) for pair in self.matched]
        data.update(recall=self.recall, precision=self.precision)
        return data


def values(text: str) -> set[str]:
    """The concrete values in a text: quoted literals, amounts, long numbers (codes) and upper-case codes."""
    found = {v.strip().upper() for v in _QUOTED.findall(text)}
    unquoted = _QUOTED.sub(" ", text)  # a quoted message counts once, not word by word
    for number in _NUMBER.findall(unquoted):
        if "." in number or len(number.lstrip("-")) >= 3:
            try:
                found.add(format(Decimal(number).normalize(), "f"))
            except InvalidOperation:
                continue
    found |= {c for c in _CODE.findall(unquoted) if c not in _NOT_CODES}
    return found


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text) if w.lower() not in _STOP and len(w) > 2}


def _rule_text(rule: Rule) -> str:
    parts = [rule.name, rule.statement, rule.condition, rule.action, *rule.scenarios, *rule.hardcoded]
    return "\n".join(p for p in parts if p)


def from_rules(rules: Sequence[Rule]) -> list[ReferenceRule]:
    references = []
    for rule in rules:
        source = rule.sources[0] if rule.sources else None
        text = _rule_text(rule)
        references.append(ReferenceRule(
            rule.id, rule.name, rule.priority, text, source.file if source else None,
            source.line_start if source else None, source.line_end if source else None,
            tuple(sorted(values(" ".join([rule.condition, rule.action, *rule.hardcoded])) or values(rule.statement))),
        ))  # fmt: skip
    return references


def _field(card: str, name: str) -> str:
    match = re.search(rf"^\*\*{re.escape(name)}:\*\*\s*(.*)$", card, re.MULTILINE)
    return match.group(1).strip() if match else ""


def parse_rule_cards(markdown: str) -> list[ReferenceRule]:
    """Rule cards (`### RULE-NNN: name` with **Priority:**, **Source:**, **Plain English:**, **Specification:**
    and **Parameters:**), the format of the analysis a reviewer approved."""
    heads = list(_CARD.finditer(markdown))
    rules = []
    for index, head in enumerate(heads):
        end = heads[index + 1].start() if index + 1 < len(heads) else len(markdown)
        card = markdown[head.end() : end]
        spec = card.split("**Specification:**", 1)[1].split("**", 1)[0] if "**Specification:**" in card else ""
        plain, parameters = _field(card, "Plain English"), _field(card, "Parameters")
        source = _SOURCE.search(_field(card, "Source"))
        priority = _field(card, "Priority").split()[0] if _field(card, "Priority") else "P2"
        rules.append(ReferenceRule(
            head.group(1), head.group(2).strip(), priority, "\n".join([head.group(2), plain, spec, parameters]),
            source.group(1) if source else None, int(source.group(2)) if source else None,
            int(source.group(3) or source.group(2)) if source else None,
            tuple(sorted(values(parameters) or values(plain))),
        ))  # fmt: skip
    return rules


def load_reference(path: Path, name: str | None = None, written_blind: bool = True) -> Reference:
    """A reference spec file: JSON with `rules` in the spec model, or rule cards in Markdown."""
    data = path.read_bytes()
    text = data.decode("utf-8")
    if path.suffix.lower() == ".json":
        document = json.loads(text)
        rules = from_rules([Rule.model_validate(r) for r in document["rules"]])
        label = name or str(document.get("application") or path.parent.name)
    else:
        rules = parse_rule_cards(text)
        label = name or path.parent.name
    return Reference(label, hashlib.sha256(data).hexdigest(), rules, written_blind)


def _overlap(reference: ReferenceRule, rule: Rule) -> float:
    if reference.file is None or reference.line_start is None or reference.line_end is None:
        return 0.0
    best = 0.0
    for source in rule.sources:
        if PurePosixPath(source.file).name.lower() != PurePosixPath(reference.file).name.lower():
            continue
        shared = min(reference.line_end, source.line_end) - max(reference.line_start, source.line_start) + 1
        smaller = min(reference.line_end - reference.line_start, source.line_end - source.line_start) + 1
        best = max(best, max(shared, 0) / smaller)
    return best


def score(reference: ReferenceRule, rule: Rule) -> float:
    ours, theirs = _words(reference.text), _words(_rule_text(rule))
    similarity = len(ours & theirs) / len(ours | theirs) if ours | theirs else 0.0
    if reference.file is None:
        return similarity
    return round(0.6 * _overlap(reference, rule) + 0.4 * similarity, 4)


def evaluate(reference: Reference, found: Sequence[Rule]) -> Evaluation:
    result = Evaluation(reference.name, reference.sha256, len(reference.rules), len(found))
    if not reference.written_blind:
        result.known_bias = ("The reference was reviewed from a previous extraction, not written before seeing one "
                             "(21.2): omissions and hallucinations may be underestimated")  # fmt: skip
    candidates = sorted(((score(r, f), r.id, f.id) for r in reference.rules for f in found), reverse=True)
    taken_reference: set[str] = set()
    taken_found: set[str] = set()
    for value, reference_id, found_id in candidates:
        if value < MATCH_THRESHOLD or reference_id in taken_reference or found_id in taken_found:
            continue
        taken_reference.add(reference_id)
        taken_found.add(found_id)
        result.matched.append((reference_id, found_id))
    by_found = {f.id: f for f in found}
    for reference_rule in reference.rules:
        if reference_rule.id not in taken_reference:
            result.omissions.append(reference_rule.id)
            if reference_rule.priority == "P0":
                result.omissions_p0.append(reference_rule.id)
    result.hallucinations = [f.id for f in found if f.id not in taken_found]
    by_reference = {r.id: r for r in reference.rules}
    for reference_id, found_id in sorted(result.matched):
        missing = sorted(set(by_reference[reference_id].values) - values(_rule_text(by_found[found_id])))
        if missing:
            result.precision_errors.append({"reference": reference_id, "found": found_id, "missing_values": missing})
    result.matched.sort()
    return result
