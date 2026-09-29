"""Field by field differences between two observations already put in one view (legacy names, canonical target
types, masks applied by the pack): the return code, every output, every row of every table and every call to an
external program, in order."""

import json
from dataclasses import dataclass

from nexti_core.spec.characterization import Observation


@dataclass(frozen=True)
class Difference:
    path: str  # returns, outputs:@x, tables:db..t[2].col, tables:db..t (rows), calls[1]:db..p.@arg, calls (count)
    expected: str | None
    actual: str | None


def _text(value: object) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)


def differences(expected: Observation, actual: Observation) -> list[Difference]:
    found: list[Difference] = []
    if expected.returns != actual.returns:
        found.append(Difference("returns", _text(expected.returns), _text(actual.returns)))
    for name in sorted(set(expected.outputs) | set(actual.outputs)):
        if expected.outputs.get(name) != actual.outputs.get(name):
            found.append(Difference(f"outputs:{name}", expected.outputs.get(name), actual.outputs.get(name)))
    for table in sorted(set(expected.tables) | set(actual.tables)):
        rows, got = expected.tables.get(table, []), actual.tables.get(table, [])
        if len(rows) != len(got):
            found.append(Difference(f"tables:{table}", f"{len(rows)} row(s)", f"{len(got)} row(s)"))
            continue
        for index, (row, other) in enumerate(zip(rows, got, strict=True)):
            for column in sorted(set(row) | set(other)):
                if row.get(column) != other.get(column):
                    found.append(Difference(f"tables:{table}[{index}].{column}", row.get(column), other.get(column)))
    if len(expected.calls) != len(actual.calls):
        found.append(Difference("calls", _text([c.program for c in expected.calls]),
                                _text([c.program for c in actual.calls])))  # fmt: skip
        return found
    for position, (call, made) in enumerate(zip(expected.calls, actual.calls, strict=True)):
        if call.program != made.program:
            found.append(Difference(f"calls[{position}]", call.program, made.program))
            continue
        for name in sorted(set(call.arguments) | set(made.arguments)):
            if call.arguments.get(name) != made.arguments.get(name):
                found.append(Difference(f"calls[{position}]:{call.program}.{name}", call.arguments.get(name),
                                        made.arguments.get(name)))  # fmt: skip
    return found
