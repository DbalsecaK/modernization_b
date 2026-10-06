# ruff: noqa: S608 - the SQL is built from the design and runs only in the database inside a sandbox
"""The golden master compared on a target (spec 11.3 check 3), the part that does not depend on the target
language (ADR-0017): each legacy case translated through the design's mappings (parameters, columns, external
programs) into a target case, and both sides put in one comparable view. Each backend pack runs the target cases in
its sandbox with its own harness.

Both views use the legacy names and the canonical text of the target type, so `'S'` in a legacy `char(1)` and `true`
in a target boolean compare equal, and so do `0.63` and `0.6300`. What cannot be compared is declared as a mask
with its reason: infrastructure programs (6.2), legacy columns or tables the target does not keep. A legacy program
the target never calls is not masked: it is a difference."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nexti_core.spec.characterization import Call, Case, GoldenMaster, Observation, Scalar, canonical
from nexti_core.spec.design import Design, Entity, UseCase


def snake(name: str) -> str:
    """The default column of a field: its name in snake_case (every pack names columns the same way)."""
    out = ""
    for index, char in enumerate(name):
        if char.isupper() and index and not name[index - 1].isupper():
            out += "_"
        out += char.lower()
    return out


@dataclass(frozen=True)
class Mask:
    path: str  # outputs:@x, tables:db..t, tables:db..t.column, calls:db..proc
    reason: str
    when: str = "always"  # or "rejected": only in the cases the legacy rejected


@dataclass(frozen=True)
class CaseRun:
    name: str
    expected: Observation
    actual: Observation
    failure: str | None = None


@dataclass(frozen=True)
class EquivalenceRun:
    build: Any  # the pack's build result (nexti_sandbox.build.BuildResult)
    cases: list[CaseRun]
    masks: list[Mask]
    problem: str | None = None  # the harness could not run at all


def column_of(field_name: str, column: str | None) -> str:
    return column or snake(field_name)


def entities_by_legacy(design: Design) -> dict[str, Entity]:
    return {e.legacy_table.lower(): e for e in design.entities if e.legacy_table and e.table}


def sql_literal(value: str | None, sql_type: str) -> str:
    if value is None:
        return "NULL"
    return "CAST('" + value.replace("'", "''") + f"' AS {sql_type})"


def target_case(
    design: Design,
    use_case: UseCase,
    case: Case,
    defaults: dict[str, Scalar] | None,
    sql_type: Callable[[str], str],
) -> dict[str, Any]:
    """A legacy case in target terms: the request, the rows to insert and the answers of each external port."""
    inputs = {k.lower(): v for k, v in {**(defaults or {}), **case.inputs}.items()}
    request = {f.name: canonical(f.type, inputs.get((f.legacy or "").lower())) for f in use_case.inputs}
    entities = entities_by_legacy(design)
    setup = []
    for table, rows in case.setup.items():
        entity = entities.get(table.lower())
        if entity is None:
            continue
        by_legacy = {(f.legacy or "").lower(): f for f in entity.fields if f.legacy}
        for row in rows:
            fields = [(by_legacy[c.lower()], v) for c, v in row.items() if c.lower() in by_legacy]
            columns = ", ".join(column_of(f.name, f.column) for f, _ in fields)
            values = ", ".join(sql_literal(canonical(f.type, v), sql_type(f.type)) for f, v in fields)
            setup.append(f"INSERT INTO {entity.table} ({columns}) VALUES ({values})")
    stubs: dict[str, list[dict[str, Any]]] = {}
    for port in design.ports:
        if not port.legacy_program:
            continue
        answers = next((a for p, a in case.stubs.items() if p.lower() == port.legacy_program.lower()), [])
        output_name = next((m.legacy_output for m in port.methods if m.legacy_output), None)
        # One call, every output (ADR-0043): the entity the method returns carries the program's outputs.
        mapped = {field: legacy for m in port.methods for field, legacy in m.legacy_outputs.items()}
        stubs[port.name] = [
            {
                "returns": a.returns,
                "output": a.outputs.get(output_name) if output_name else None,
                **({"outputs": {field: a.outputs.get(legacy) for field, legacy in mapped.items()}} if mapped else {}),
            }
            for a in answers
        ]
    return {"name": case.name, "request": request, "setup": setup, "stubs": stubs}


def masks(design: Design, use_case: UseCase, master: GoldenMaster) -> list[Mask]:
    found = [Mask(m.path, m.reason, m.when) for m in design.masks]
    found += [Mask(f"calls:{p}", "infrastructure of the legacy: the target framework replaces it (6.2)")
              for p in design.infrastructure]  # fmt: skip
    entities = entities_by_legacy(design)
    for table in master.schema_.tables:
        entity = entities.get(table.name.lower())
        if entity is None:
            found.append(Mask(f"tables:{table.name}", "no entity of the design keeps this legacy table"))
            continue
        kept = {(f.legacy or "").lower() for f in entity.fields}
        found += [Mask(f"tables:{table.name}.{c.name}", "the target does not keep this legacy column")
                  for c in table.columns if c.name.lower() not in kept]  # fmt: skip
    mapped = {(f.legacy or "").lower() for f in use_case.outputs} | {(use_case.legacy_message or "").lower()}
    outputs = {o for r in master.results for o in r.observation.outputs}
    found += [Mask(f"outputs:{o}", "no output of the use case returns this legacy parameter")
              for o in sorted(outputs) if o.lower() not in mapped]  # fmt: skip
    # An output the program never assigns echoes what the caller passed (ADR-0044): not behaviour to reproduce.
    found += [Mask(f"outputs:{o}", "the program never assigns this output parameter: the legacy returns the value "
                   "the caller passed in") for o in sorted(master.unassigned_outputs)
              if o.lower() in mapped and echoed(master, o)]  # fmt: skip
    return found


def echoed(master: GoldenMaster, output: str) -> bool:
    """Every recorded case returned in `output` exactly what it passed in (or nothing when it passed nothing)."""
    for r in master.results:
        given = next((v for k, v in r.case.inputs.items() if k.lower() == output.lower()), None)
        observed = next((v for k, v in r.observation.outputs.items() if k.lower() == output.lower()), None)
        if canonical(None, given) != observed:
            return False
    return True


def _masked(path: str, found: list[Mask], rejected: bool = False) -> bool:
    return any(path.lower() == m.path.lower() and (m.when == "always" or rejected) for m in found)


def expected_view(design: Design, use_case: UseCase, observed: Observation, found: list[Mask]) -> Observation:
    """What the legacy did, in legacy names and canonical target types, without what is masked."""
    outputs = {}
    rejected = observed.returns not in (0, None)
    by_output = {(f.legacy or "").lower(): f for f in use_case.outputs if f.legacy}
    for name, value in observed.outputs.items():
        if _masked(f"outputs:{name}", found, rejected):
            continue
        field = by_output.get(name.lower())
        outputs[name] = canonical(field.type if field else None, value)
    tables = {}
    entities = entities_by_legacy(design)
    for table, rows in observed.tables.items():
        entity = entities.get(table.lower())
        if entity is None or _masked(f"tables:{table}", found):
            continue
        by_legacy = {(f.legacy or "").lower(): f for f in entity.fields if f.legacy}
        tables[table] = _sorted([{c: canonical(by_legacy[c.lower()].type, v) for c, v in row.items()
                                  if c.lower() in by_legacy and not _masked(f"tables:{table}.{c}", found)}
                                 for row in rows])  # fmt: skip
    calls = []
    ports = {(p.legacy_program or "").lower(): p for p in design.ports if p.legacy_program}
    for call in observed.calls:
        if _masked(f"calls:{call.program}", found):
            continue
        port = ports.get(call.program.lower())
        types = {(f.legacy or "").lower(): f.type for m in port.methods for f in m.inputs} if port else {}
        calls.append(Call(program=call.program, arguments={
            n: canonical(types.get(n.lower()), v) for n, v in call.arguments.items() if not port or n.lower() in types
        }))  # fmt: skip
    return Observation(returns=observed.returns, outputs=outputs, tables=tables, calls=calls)


def actual_view(
    design: Design, use_case: UseCase, raw: dict[str, Any], found: list[Mask], rejected: bool = False
) -> Observation:
    """What the target did, in the same view as `expected_view`; `rejected` says whether the legacy rejected."""
    outputs: dict[str, str | None] = {}
    error = raw.get("error")
    for field in use_case.outputs:
        if field.legacy and not _masked(f"outputs:{field.legacy}", found, rejected):
            value = (raw.get("response") or {}).get(field.name) if error is None else None
            outputs[field.legacy] = canonical(field.type, value)
    if (
        error is not None
        and use_case.legacy_message
        and not _masked(f"outputs:{use_case.legacy_message}", found, rejected)
    ):
        message = next((f for f in use_case.outputs if f.legacy == use_case.legacy_message), None)
        outputs[use_case.legacy_message] = canonical(message.type if message else None, error.get("message"))
    returns = 0
    if error is not None:
        code = str(error.get("legacy_code") or "")
        returns = int(code) if code.lstrip("-").isdigit() else -1
    tables = {}
    for entity in design.entities:
        if not entity.table or not entity.legacy_table or _masked(f"tables:{entity.legacy_table}", found):
            continue
        rows = (raw.get("tables") or {}).get(entity.table, [])
        tables[entity.legacy_table] = _sorted([
            {f.legacy: canonical(f.type, row.get(column_of(f.name, f.column))) for f in entity.fields if f.legacy}
            for row in rows
        ])  # fmt: skip
    calls = []
    for call in raw.get("calls", []):
        port = next((p for p in design.ports if p.name == call.get("port")), None)
        method = next((m for m in port.methods if m.name == call.get("method")), None) if port else None
        if port is None or method is None or not port.legacy_program:
            continue
        arguments = {f.legacy: canonical(f.type, v) for f, v in zip(method.inputs, call.get("arguments", []),
                                                                     strict=False) if f.legacy}  # fmt: skip
        calls.append(Call(program=port.legacy_program, arguments=arguments))
    return Observation(returns=returns, outputs=outputs, tables=tables, calls=calls)


def _sorted(rows: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    return sorted(rows, key=lambda r: json.dumps(r, sort_keys=True))
