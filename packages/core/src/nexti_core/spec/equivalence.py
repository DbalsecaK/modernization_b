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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from nexti_core.spec.characterization import (
    OMITTED,
    Call,
    Case,
    GoldenMaster,
    Observation,
    Scalar,
    canonical,
    substitute_message,
)
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
class EngineTarget:
    """The legacy's engine a target runs its golden master against (ADR-0055, `same_database`): started by the
    verification with the suite's tables, the transactional substitutes of the called programs and the call log,
    reachable from the sandbox on `network`. `setup_for` gives the batches that reset and prepare one case (its
    rows, the substitutes with the case's answers); `calls_query` reads the calls that survived the use case's
    transaction; `parse_args` and `programs` turn each logged call into legacy arguments by name."""

    name: str  # the engine's host name on the network
    network: str
    jdbc_url: str
    user: str
    password: str
    setup_for: Callable[[Any], list[str]]  # Case -> batches (no `go`)
    calls_query: str
    programs: dict[str, list[str]]  # program -> names of its input parameters, in order
    parse_args: Callable[[str], list[str | None]]
    # program -> neutral type of each input parameter, in the order of `programs` (phase F: a `char(4)` the
    # substitute logs as `C1  ` is the `C1` the characterization canonicalised; without the type every case differed)
    types: dict[str, list[str | None]] = dc_field(default_factory=dict)

    def calls(self, rows: Sequence[dict[str, Any]]) -> list[Call]:
        found = []
        for row in rows:
            program = str(row.get("program") or "")
            values = self.parse_args(str(row.get("args") or "")) if row.get("args") is not None else []
            key = program.lower() if program.lower() in self.programs else program
            names = self.programs.get(key) or []
            kinds = self.types.get(key) or []
            found.append(Call(program=program, arguments={
                n: canonical(kinds[i] if i < len(kinds) else None, v)
                for i, (n, v) in enumerate(zip(names, values, strict=False)) if v != OMITTED
            }))  # fmt: skip
        return found


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


STATUS = "return"  # the reserved legacy name of a called program's return status (ADR-0055, phase F)


def status_field(use_case: UseCase) -> Any | None:
    """The output of the use case that carries the program's own return status (legacy name `return`, phase F):
    a program whose error exit returns 0 with the code in an output parameter signals errors as data, and the
    target returns the status and the outputs instead of throwing."""
    return next((f for f in use_case.outputs if (f.legacy or "").lower() == STATUS), None)


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
        # One call, every output (ADR-0043): the entity the method returns carries the program's outputs. The
        # reserved name `return` is the call's return status (ADR-0055, phase F): data the legacy reads and acts
        # on, delivered by the fake instead of thrown.
        mapped = {field: legacy for m in port.methods for field, legacy in m.legacy_outputs.items()}
        carries = output_name == STATUS or STATUS in mapped.values()
        stubs[port.name] = [
            {
                "returns": a.returns,
                "output": (a.returns if output_name == STATUS else a.outputs.get(output_name)) if output_name else None,
                **(
                    {
                        "outputs": {
                            field: (a.returns if legacy == STATUS else a.outputs.get(legacy))
                            for field, legacy in mapped.items()
                        }
                    }
                    if mapped
                    else {}
                ),
                **({"carries_status": True} if carries else {}),
                **({"effects": effects} if (effects := target_effects(design, a.effects, sql_type)) else {}),
            }
            for a in answers
        ]
    return {"name": case.name, "request": request, "setup": setup, "stubs": stubs}


def target_effects(
    design: Design, effects: dict[str, list[dict[str, Scalar]]], sql_type: Callable[[str], str]
) -> list[dict[str, str | None]]:
    """The rows a substitute leaves (ADR-0055), in target terms: for each row an UPDATE by the entity's key and the
    INSERT the harness runs when the update changed nothing, inside the use case's transaction. A row of a table no
    entity keeps is not an effect on the target; a row without its key is only inserted."""
    entities = entities_by_legacy(design)
    out: list[dict[str, str | None]] = []
    for table, rows in effects.items():
        entity = entities.get(table.lower())
        if entity is None:
            continue
        by_legacy = {(f.legacy or "").lower(): f for f in entity.fields if f.legacy}
        key_columns = [column_of(f.name, f.column) for f in entity.fields if f.name in entity.key]
        for row in rows:
            fields = [(by_legacy[c.lower()], v) for c, v in row.items() if c.lower() in by_legacy]
            if not fields:
                continue
            values = {column_of(f.name, f.column): sql_literal(canonical(f.type, v), sql_type(f.type))
                      for f, v in fields}  # fmt: skip
            where = [f"{c} = {values[c]}" for c in key_columns if c in values]
            # A row of key columns only still has to say whether it exists: an update that changes nothing.
            sets = [f"{c} = {v}" for c, v in values.items() if c not in key_columns] or [
                f"{c} = {c}" for c in list(values)[:1]
            ]
            insert = f"INSERT INTO {entity.table} ({', '.join(values)}) VALUES ({', '.join(values.values())})"
            update = (f"UPDATE {entity.table} SET {', '.join(sets)} WHERE {' AND '.join(where)}"
                      if where and len(where) == len(key_columns) else None)  # fmt: skip
            out.append({"update": update, "insert": insert})
    return out


def message_field(use_case: UseCase) -> str | None:
    """The legacy parameter that carries the message of a rejection, when it is text: a numeric output (an error
    code) cannot hold a message, so it is compared as an ordinary output (P36)."""
    if not use_case.legacy_message:
        return None
    field = next((f for f in use_case.outputs if (f.legacy or "").lower() == use_case.legacy_message.lower()), None)
    if field is not None and not field.type.startswith("text"):
        return None
    return use_case.legacy_message


REJECTED_REASON = (
    "a rejection of the target is an exception with the code and the message: the legacy's output parameters on "
    "that path are not part of it"
)


def masks(design: Design, use_case: UseCase, master: GoldenMaster) -> list[Mask]:
    found = [Mask(m.path, m.reason, m.when) for m in design.masks]
    # A program the design declared as infrastructure (logging, auditing): a decision of the architect, checked by the
    # guided design against the rules (ADR-0055 keeps the error contract and the unit of work out of this list).
    found += [Mask(f"calls:{p}", "declared infrastructure by the design: the target framework replaces it (6.2)")
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
    mapped.discard(STATUS)  # the status is `returns`, never an output parameter
    outputs = {o for r in master.results for o in r.observation.outputs}
    found += [Mask(f"outputs:{o}", "no output of the use case returns this legacy parameter")
              for o in sorted(outputs) if o.lower() not in mapped]  # fmt: skip
    # On a path the legacy rejects, the target raises its business error (code and message): the other output
    # parameters of the legacy are not produced there, and comparing them would demand the impossible (P36).
    message = (message_field(use_case) or "").lower()
    masked_paths = {m.path.lower() for m in found}
    rejected_outputs = [
        f.legacy
        for f in use_case.outputs
        if f.legacy and f.legacy.lower() not in (message, STATUS) and f"outputs:{f.legacy}".lower() not in masked_paths
    ]
    found += [Mask(f"outputs:{legacy}", REJECTED_REASON, "rejected") for legacy in rejected_outputs]
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
    return Observation(returns=observed.returns, outputs=outputs, tables=tables,
                       calls=_legacy_calls(design, observed.calls, found),
                       undone=_legacy_calls(design, observed.undone, found),
                       messages=_substitute_messages(observed.messages))  # fmt: skip


def _substitute_messages(raw: Sequence[Any]) -> list[str]:
    """The messages the called programs raised, in canonical form (ADR-0056): what the legacy's caller saw from
    them is what the target's caller must see."""
    return [m for m in (substitute_message(str(text)) for text in raw) if m]


def _legacy_calls(design: Design, observed: list[Call], found: list[Mask]) -> list[Call]:
    """The legacy's calls without the masked programs, each argument in the canonical text of its port's type. Every
    argument the legacy passed counts (ADR-0056): one the port does not map is a difference the design must close,
    not one the view hides."""
    calls = []
    ports = {(p.legacy_program or "").lower(): p for p in design.ports if p.legacy_program}
    for call in observed:
        if _masked(f"calls:{call.program}", found):
            continue
        port = ports.get(call.program.lower())
        types = {(f.legacy or "").lower(): f.type for m in port.methods for f in m.inputs} if port else {}
        calls.append(Call(program=call.program, arguments={
            n: canonical(types.get(n.lower()), v) for n, v in call.arguments.items()
        }))  # fmt: skip
    return calls


def actual_view(
    design: Design, use_case: UseCase, raw: dict[str, Any], found: list[Mask], rejected: bool = False,
    legacy_calls: Sequence[Call] | None = None,
) -> Observation:  # fmt: skip
    """What the target did, in the same view as `expected_view`; `rejected` says whether the legacy rejected. With
    `legacy_calls` (the target ran against the legacy's engine, ADR-0055) the calls are the ones the engine logged,
    already in legacy terms, filtered by the masks."""
    outputs: dict[str, str | None] = {}
    error = raw.get("error")
    status = status_field(use_case)
    for field in use_case.outputs:
        if field is status:
            continue
        if field.legacy and not _masked(f"outputs:{field.legacy}", found, rejected):
            value = (raw.get("response") or {}).get(field.name) if error is None else None
            outputs[field.legacy] = canonical(field.type, value)
    text_message = message_field(use_case)
    if error is not None and text_message and not _masked(f"outputs:{text_message}", found, rejected):
        message = next((f for f in use_case.outputs if f.legacy == text_message), None)
        outputs[text_message] = canonical(message.type if message else None, error.get("message"))
    returns = 0
    if error is not None:
        code = str(error.get("legacy_code") or "")
        returns = int(code) if code.lstrip("-").isdigit() else -1
    elif status is not None:
        # The program's own status as data (phase F): what the response says it returned, 0 when it says nothing.
        text = canonical(status.type, (raw.get("response") or {}).get(status.name))
        returns = int(text) if text is not None and text.lstrip("-").isdigit() else 0
    tables = {}
    for entity in design.entities:
        if not entity.table or not entity.legacy_table or _masked(f"tables:{entity.legacy_table}", found):
            continue
        rows = (raw.get("tables") or {}).get(entity.table, [])
        tables[entity.legacy_table] = _sorted([
            {f.legacy: canonical(f.type, row.get(column_of(f.name, f.column))) for f in entity.fields if f.legacy}
            for row in rows
        ])  # fmt: skip
    # The harness reports the calls of the fakes that are in the final state and, apart, the ones its rollback
    # undid (ADR-0055); the undone ones are diagnostic, the comparison is on what survived.
    messages = _substitute_messages(raw.get("messages") or [])
    if legacy_calls is not None:
        calls = _legacy_calls(design, list(legacy_calls), found)
        return Observation(returns=returns, outputs=outputs, tables=tables, calls=calls, messages=messages)
    return Observation(returns=returns, outputs=outputs, tables=tables,
                       calls=_target_calls(design, raw.get("calls", [])),
                       undone=_target_calls(design, raw.get("undone", [])), messages=messages)  # fmt: skip


def _target_calls(design: Design, raw: list[dict[str, Any]]) -> list[Call]:
    """The calls of the harness's fakes in legacy terms: the program of the port, the arguments by the method's
    input mapping."""
    calls = []
    for call in raw:
        port = next((p for p in design.ports if p.name == call.get("port")), None)
        method = next((m for m in port.methods if m.name == call.get("method")), None) if port else None
        if port is None or method is None or not port.legacy_program:
            continue
        arguments = {f.legacy: canonical(f.type, v) for f, v in zip(method.inputs, call.get("arguments", []),
                                                                     strict=False) if f.legacy}  # fmt: skip
        calls.append(Call(program=port.legacy_program, arguments=arguments))
    return calls


def _sorted(rows: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    return sorted(rows, key=lambda r: json.dumps(r, sort_keys=True))
