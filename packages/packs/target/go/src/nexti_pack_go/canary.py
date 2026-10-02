"""The canary of the Go pack (spec 11.3 check 5): deliberate one-line changes to a generated file that the tests or
the golden cases must catch, the ones Go code with shopspring/decimal makes: a decimal constant, a rounding, a
comparison, a zero check and a code compared. Deterministic: the same source gives the same changes, in line order,
one per line, so the evidence can be recomputed."""

import re
from collections.abc import Callable
from dataclasses import dataclass


def _bump_decimal(match: re.Match[str]) -> str:
    whole, fraction = match.group(2), match.group(3)
    last = (int(fraction[-1]) + 1) % 10
    return f'{match.group(1)}("{whole}.{fraction[:-1]}{last}")'


Replacement = str | Callable[[re.Match[str]], str]
_CHANGES: tuple[tuple[re.Pattern[str], Replacement], ...] = (
    (re.compile(r'(decimal\.(?:RequireFromString|NewFromString))\("(\d+)\.(\d+)"\)'), _bump_decimal),
    (re.compile(r"\.DivRound\(([^,()]+(?:\([^()]*\))?),\s*(\d+)\)"), r".Div(\1).Truncate(\2)"),
    (re.compile(r"\.RoundBank\("), ".Round("),
    (re.compile(r"\.Round\("), ".Truncate("),
    (re.compile(r"\.LessThan\("), ".LessThanOrEqual("),
    (re.compile(r"\.GreaterThan\("), ".GreaterThanOrEqual("),
    (re.compile(r"\.IsPositive\(\)"), ".IsNegative() == false"),
    (re.compile(r"\.Cmp\(([^()]*(?:\([^()]*\))?[^()]*)\)\s*<\s*0"), r".Cmp(\1) <= 0"),
    (re.compile(r"(\w|\))\s*==\s*0\s*\{"), r"\1 != 0 {"),
    (re.compile(r'(==|!=)\s*"([A-Z][A-Z0-9]+)"'), r'\1 "\2X"'),
)


@dataclass(frozen=True)
class Mutation:
    line: int
    before: str
    after: str
    source: str  # the whole file with the change


def mutations(source: str, limit: int = 3) -> list[Mutation]:
    lines = source.split("\n")
    found: list[Mutation] = []
    in_imports = False
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("import ("):
            in_imports = True
        if in_imports:
            in_imports = stripped != ")"
            continue
        if not stripped or stripped.startswith(("//", "/*", "*", "package ", "import ")):
            continue
        for pattern, replacement in _CHANGES:
            changed = pattern.sub(replacement, line, count=1)
            if changed != line:
                mutated = [*lines[: number - 1], changed, *lines[number:]]
                found.append(Mutation(number, line, changed, "\n".join(mutated)))
                break
        if len(found) == limit:
            break
    return found
