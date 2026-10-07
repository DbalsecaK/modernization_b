"""The SQL statements a generated adapter builds from its string literals, and the report of a probe that prepared
them against the target schema in the sandbox (P32 for every pack, step 12 of the plan).

Each pack gives the literal syntax of its language (`text_of` says the text of a literal and whether it is built at
run time, like an interpolated C# string) and the engine script; this module joins adjacent literals into
statements, skips the ones concatenated with code (P38: only known when they run) and maps the engine's errors back
to the statement they refer to, by a marker line printed before each statement or by the line of the probe file."""

import re
from collections.abc import Callable

STATEMENT_START = re.compile(r"^\s*(select|insert|update|delete|with|merge)\b", re.I)
JOINER = re.compile(r"^[\s+]*$")
LITERAL_START = ('"', "`", '@"', '$"')
PROBE_PATH = "sql-probe.sql"
START = "===SQL-PROBE==="
END = "===SQL-PROBE-END==="
MARK = "NXSQL|"


def statements(
    source: str, literal: re.Pattern[str], text_of: Callable[[re.Match[str]], tuple[str, bool]]
) -> list[str]:
    """The SQL statements of a source file: adjacent literals joined by `+` are one statement; a statement that
    goes on with an expression, or uses an interpolated literal, is built at run time and is not returned."""
    found: list[tuple[str, bool]] = []
    current = ""
    dynamic = False
    last_end = 0
    for match in literal.finditer(source):
        text, built = text_of(match)
        between = source[last_end : match.start()]
        if current and JOINER.match(between):
            current += text
            dynamic = dynamic or built
        elif current and between.strip().startswith("+"):  # literal + expression + literal: built at run time
            current += text
            dynamic = True
        else:
            if current:
                found.append((current, dynamic))
            current, dynamic = text, built
        last_end = match.end()
        after = source[match.end() : match.end() + 200].lstrip()
        if after.startswith("+") and not after[1:].lstrip().startswith(LITERAL_START):
            dynamic = True  # the literal goes on with an expression
    if current:
        found.append((current, dynamic))
    return [" ".join(text.split()) for text, built in found if STATEMENT_START.match(text) and not built]


def _body(after_output: str) -> str:
    if START not in after_output:
        return ""
    return after_output.split(START, 1)[1].split(END, 1)[0].strip()


def _report(errors: dict[int, list[str]], found: list[str], extra: list[str]) -> str:
    lines = [
        f"{' '.join(errors[i])}\n  statement: {found[i - 1][:400]}" for i in sorted(errors) if 1 <= i <= len(found)
    ]
    return "\n".join([*lines, *extra])


def by_marker(after_output: str, found: list[str]) -> str:
    """The errors printed after each `NXSQL|<n>` marker, each with its statement; empty when all prepared."""
    errors: dict[int, list[str]] = {}
    current = 0
    extra: list[str] = []
    for line in _body(after_output).splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith(MARK) and text[len(MARK) :].isdigit():
            current = int(text[len(MARK) :])
        elif current:
            errors.setdefault(current, []).append(text)
        else:
            extra.append(text)  # before any statement: the database or the schema
    return _report(errors, found, extra)


def by_line(after_output: str, found: list[str], pattern: re.Pattern[str]) -> str:
    """The errors that name the line of the probe file (one statement per line), each with its statement."""
    errors: dict[int, list[str]] = {}
    extra: list[str] = []
    for line in _body(after_output).splitlines():
        text = line.strip()
        if not text:
            continue
        match = pattern.search(text)
        if match:
            errors.setdefault(int(match.group(1)), []).append(match.group(2).strip())
        else:
            extra.append(text)
    return _report(errors, found, extra)
