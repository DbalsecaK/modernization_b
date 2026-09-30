"""The canary of the Java pack (spec 11.3 check 5): deliberate one-line changes to a generated class that the tests
or the golden cases must catch. Deterministic: the same source gives the same changes, in line order, one per line,
so the evidence can be recomputed."""

import re
from collections.abc import Callable
from dataclasses import dataclass


def _bump_decimal(match: re.Match[str]) -> str:
    whole, fraction = match.group(1), match.group(2)
    last = (int(fraction[-1]) + 1) % 10
    return f'new BigDecimal("{whole}.{fraction[:-1]}{last}")'


Replacement = str | Callable[[re.Match[str]], str]
_CHANGES: tuple[tuple[re.Pattern[str], Replacement], ...] = (
    (re.compile(r"RoundingMode\.HALF_UP"), "RoundingMode.DOWN"),
    (re.compile(r"RoundingMode\.HALF_EVEN"), "RoundingMode.UP"),
    (re.compile(r'new BigDecimal\("(\d+)\.(\d+)"\)'), _bump_decimal),
    (re.compile(r"\.compareTo\(([^()]*(?:\([^()]*\))?[^()]*)\)\s*<\s*0"), r".compareTo(\1) <= 0"),
    (re.compile(r"\.signum\(\)\s*>\s*0"), ".signum() >= 0"),
    (re.compile(r"\)\s*==\s*0\)"), ") != 0)"),
    (re.compile(r'"([A-Z][A-Z0-9]+)"\.equals\('), r'"\1X".equals('),
)


@dataclass(frozen=True)
class Mutation:
    line: int
    before: str
    after: str
    source: str  # the whole class with the change


def mutations(source: str, limit: int = 3) -> list[Mutation]:
    lines = source.split("\n")
    found: list[Mutation] = []
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "*", "/*", "import ", "package ")):
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
