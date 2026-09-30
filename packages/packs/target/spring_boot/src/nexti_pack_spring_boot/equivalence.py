# ruff: noqa: S608 - the SQL is built from the design and runs only in the PostgreSQL inside the sandbox
"""The golden master on the generated service (spec 11.3 check 3): each legacy case translated through the design's
mappings (parameters, columns, external programs), run by the platform's harness against PostgreSQL in the
sandbox, and both sides put in one comparable view.

Both views use the legacy names and the canonical text of the target type, so `'S'` in a legacy `char(1)` and `true`
in a target boolean compare equal, and so do `0.63` and `0.6300`. What cannot be compared is declared as a mask
with its reason: infrastructure programs (6.2), legacy columns or tables the target does not keep. A legacy program
the target never calls is not masked: it is a difference."""

import json
from dataclasses import dataclass
from importlib.resources import files as package_files
from typing import Any

from nexti_core.spec.characterization import Call, Case, GoldenMaster, Observation, Scalar, canonical
from nexti_pack_spring_boot.build import BuildResult, compile_and_test
from nexti_pack_spring_boot.design import Design, Entity, UseCase
from nexti_pack_spring_boot.generate import _snake, adapter_path, sql_type
from nexti_sandbox import Sandbox

HARNESS_CLASS = "nexti.equivalence.EquivalenceHarness"
JDBC_URL = "jdbc:postgresql://localhost:5432/nexti"


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
    build: BuildResult
    cases: list[CaseRun]
    masks: list[Mask]
    problem: str | None = None  # the harness could not run at all


def harness_source() -> str:
    return (package_files("nexti_pack_spring_boot") / "harness" / "EquivalenceHarness.java").read_text("utf-8")


def _column(field_name: str, column: str | None) -> str:
    return column or _snake(field_name)


def _entities_by_legacy(design: Design) -> dict[str, Entity]:
    return {e.legacy_table.lower(): e for e in design.entities if e.legacy_table and e.table}


def _sql_literal(value: str | None, sql_type: str) -> str:
    if value is None:
        return "NULL"
    return "CAST('" + value.replace("'", "''") + f"' AS {sql_type})"


def plan(design: Design, use_case: UseCase) -> dict[str, Any]:
    """What the harness needs: the classes, the ports (adapter or fake), how to reset and how to read the tables."""
    ports = []
    for name in use_case.ports:
        port = next(p for p in design.ports if p.name == name)
        adapter = None if port.legacy_program else adapter_path(design, port).split("src/main/java/", 1)[1]
        ports.append({"interface": f"{design.base_package}.domain.port.{name}",
                      "adapter": adapter.removesuffix(".java").replace("/", ".") if adapter else None})  # fmt: skip
    tables = [e for e in design.entities if e.table]
    dump = {}
    for entity in tables:
        columns = ", ".join(_column(f.name, f.column) for f in entity.fields)
        order = ", ".join(_column(k, next(f.column for f in entity.fields if f.name == k)) for k in entity.key)
        dump[entity.table] = f"SELECT {columns} FROM {entity.table}" + (f" ORDER BY {order}" if order else "")
    return {
        "jdbc_url": JDBC_URL,
        "user": "nexti",
        "service": f"{design.base_package}.application.{use_case.name}Service",
        "request": f"{design.base_package}.adapters.in.rest.{use_case.name}Request",
        "ports": ports,
        "reset": [f"TRUNCATE {', '.join(e.table for e in tables if e.table)}"] if tables else [],
        "dump": dump,
    }


def target_case(
    design: Design, use_case: UseCase, case: Case, defaults: dict[str, Scalar] | None = None
) -> dict[str, Any]:
    """A legacy case in target terms: the request, the rows to insert and the answers of each external port."""
    inputs = {k.lower(): v for k, v in {**(defaults or {}), **case.inputs}.items()}
    request = {f.name: canonical(f.type, inputs.get((f.legacy or "").lower())) for f in use_case.inputs}
    entities = _entities_by_legacy(design)
    setup = []
    for table, rows in case.setup.items():
        entity = entities.get(table.lower())
        if entity is None:
            continue
        by_legacy = {(f.legacy or "").lower(): f for f in entity.fields if f.legacy}
        for row in rows:
            fields = [(by_legacy[c.lower()], v) for c, v in row.items() if c.lower() in by_legacy]
            columns = ", ".join(_column(f.name, f.column) for f, _ in fields)
            values = ", ".join(_sql_literal(canonical(f.type, v), sql_type(f.type)) for f, v in fields)
            setup.append(f"INSERT INTO {entity.table} ({columns}) VALUES ({values})")
    stubs: dict[str, list[dict[str, Any]]] = {}
    for port in design.ports:
        if not port.legacy_program:
            continue
        answers = next((a for p, a in case.stubs.items() if p.lower() == port.legacy_program.lower()), [])
        output_name = next((m.legacy_output for m in port.methods if m.legacy_output), None)
        stubs[port.name] = [
            {"returns": a.returns, "output": a.outputs.get(output_name) if output_name else None} for a in answers
        ]
    return {"name": case.name, "request": request, "setup": setup, "stubs": stubs}


def masks(design: Design, use_case: UseCase, master: GoldenMaster) -> list[Mask]:
    found = [Mask(m.path, m.reason, m.when) for m in design.masks]
    found += [Mask(f"calls:{p}", "infrastructure of the legacy: the target framework replaces it (6.2)")
              for p in design.infrastructure]  # fmt: skip
    entities = _entities_by_legacy(design)
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
    return found


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
    entities = _entities_by_legacy(design)
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
            {f.legacy: canonical(f.type, row.get(_column(f.name, f.column))) for f in entity.fields if f.legacy}
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


SCRIPT = r"""
mkdir -p /work/harness-out
if ! javac -nowarn -encoding UTF-8 -d /work/harness-out -cp "/work/out:/opt/lib/*" \
    /input/harness/EquivalenceHarness.java 2> /work/javac.txt; then
  echo "===HARNESS-FAILED==="; cat /work/javac.txt; exit 4
fi
if ! initdb -D /work/pg -U nexti --auth=trust -E UTF8 --no-locale > /work/pg-init.log 2>&1; then
  echo "===HARNESS-FAILED==="; cat /work/pg-init.log; exit 5
fi
if ! pg_ctl -D /work/pg -l /work/pg.log -o "-k /work -c listen_addresses=localhost -c port=5432 -F" -w start \
    > /dev/null; then
  echo "===HARNESS-FAILED==="; cat /work/pg.log; exit 5
fi
psql -h localhost -U nexti -d postgres -q -c "CREATE DATABASE nexti" > /dev/null
if ! psql -h localhost -U nexti -d nexti -q -v ON_ERROR_STOP=1 -f /work/p/src/main/resources/db/schema.sql \
    > /work/schema.log 2>&1; then
  echo "===HARNESS-FAILED==="; cat /work/schema.log; exit 6
fi
echo "===EQUIVALENCE==="
java -cp "/work/out:/work/harness-out:/opt/lib/*" nexti.equivalence.EquivalenceHarness \
  /input/harness/plan.json /input/harness/cases.json 2>&1 || true
echo "===EQUIVALENCE-END==="
pg_ctl -D /work/pg -m fast stop > /dev/null 2>&1 || true
"""


async def run_equivalence(
    sandbox: Sandbox,
    files: dict[str, str],
    design: Design,
    use_case: UseCase,
    master: GoldenMaster,
    defaults: dict[str, Scalar] | None = None,
) -> EquivalenceRun:
    """Compiles the project (tests included, counted from JUnit XML) and runs every golden case on it."""
    recorded = [r for r in master.results if r.observation.error is None]
    cases = [target_case(design, use_case, r.case, defaults) for r in recorded]
    extra = {
        "harness/EquivalenceHarness.java": harness_source(),
        "harness/plan.json": json.dumps(plan(design, use_case)),
        "harness/cases.json": json.dumps(cases),
    }
    build = await compile_and_test(sandbox, files, extra_inputs=extra, after=SCRIPT)
    found = masks(design, use_case, master)
    if not build.compiled:
        return EquivalenceRun(build, [], found, "the project does not compile")
    if "===HARNESS-FAILED===" in build.after_output:
        return EquivalenceRun(build, [], found, build.after_output.split("===HARNESS-FAILED===", 1)[1][:3000])
    raw = {}
    for line in build.after_output.split("===EQUIVALENCE===", 1)[-1].splitlines():
        if line.startswith("NXE "):
            item = json.loads(line[4:])
            raw[item["name"]] = item
    runs = []
    for recorded_case in recorded:
        item = raw.get(recorded_case.case.name)
        expected = expected_view(design, use_case, recorded_case.observation, found)
        if item is None or item.get("failure"):
            failure = (item or {}).get("failure") or "the harness printed nothing for this case"
            runs.append(CaseRun(recorded_case.case.name, expected, Observation(), failure))
            continue
        rejected = recorded_case.observation.returns not in (0, None)
        actual = actual_view(design, use_case, item, found, rejected)
        if master.from_traces and actual.returns not in (0, None):
            # A trace has no legacy return code (a CICS program just shows its message): it can only say that the
            # program rejected (-1, ADR-0015). The target's rejection is compared as that, its message as usual.
            actual = actual.model_copy(update={"returns": -1})
        runs.append(CaseRun(recorded_case.case.name, expected, actual))
    return EquivalenceRun(build, runs, found)
