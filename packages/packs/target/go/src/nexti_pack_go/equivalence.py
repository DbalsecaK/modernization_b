# ruff: noqa: S608, E501 - the SQL is built from the design and runs only in the PostgreSQL inside the sandbox
"""The golden master on the generated Go service (spec 11.3 check 3): the target cases of
`nexti_core.spec.equivalence` run by the platform's Go harness against PostgreSQL in the sandbox. Go has no runtime
proxies or constructors by name, so the harness has two files: `runtime.go`, the same for every design (cases, fakes'
recorder, transaction, table dump, JSON lines), and `glue.go`, generated here from the design without judgement: it
builds the use case service with the real adapters and one fake per external program, and converts the request and
the response. Both print the lines the Java harness prints, so the comparison is the same code for every pack."""

import json
from importlib.resources import files as package_files
from typing import Any

from nexti_core.spec import neutral_types as nt
from nexti_core.spec.characterization import GoldenMaster, Observation, Scalar
from nexti_core.spec.design import Design, FieldSpec, Port, UseCase
from nexti_core.spec.equivalence import (
    CaseRun,
    EquivalenceRun,
    Mask,
    actual_view,
    column_of,
    expected_view,
    masks,
)
from nexti_pack_go.build import compile_and_test
from nexti_pack_go.generate import (
    APP,
    DECIMAL,
    DOMAIN,
    PG,
    SCHEMA,
    adapter_name,
    constructor,
    go_type,
    ident,
    module_path,
    pascal,
    zoned,
)
from nexti_pack_spring_boot.equivalence import target_case as postgresql_target_case
from nexti_sandbox import Sandbox

__all__ = ["CaseRun", "EquivalenceRun", "Mask", "expected_view", "glue", "masks", "plan", "run_equivalence",
           "target_case"]  # fmt: skip

URL = "postgres://nexti@localhost:5432/nexti?sslmode=disable"
HARNESS_DIR = "cmd/nexti-equivalence"
target_case = postgresql_target_case  # the rows go in with PostgreSQL types, as for the Spring Boot pack


def runtime_source() -> str:
    return (package_files("nexti_pack_go") / "harness" / "runtime.go").read_text("utf-8")


def _column_text(neutral: str, column: str) -> str:
    """The column in the canonical text of its type, computed by PostgreSQL so the harness reads only text."""
    value = nt.parse(neutral)
    if isinstance(value, nt.Binary):
        return f"encode({column}, 'hex') AS {column}"
    if isinstance(value, nt.Timestamp) and value.tz:
        return (f"to_char({column} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS') || '+00:00' AS {column}")  # fmt: skip
    return f"{column}::text AS {column}"


def plan(design: Design, use_case: UseCase) -> dict[str, Any]:
    """What the runtime needs: where the database is, how to reset it and how to read every table as text."""
    tables = [e for e in design.entities if e.table]
    dump = []
    for entity in tables:
        columns = ", ".join(_column_text(f.type, column_of(f.name, f.column)) for f in entity.fields)
        order = ", ".join(column_of(k, next(f.column for f in entity.fields if f.name == k)) for k in entity.key)
        dump.append({"table": entity.table,
                     "sql": f"SELECT {columns} FROM {entity.table}" + (f" ORDER BY {order}" if order else "")})  # fmt: skip
    return {
        "url": URL,
        "reset": [f"TRUNCATE {', '.join(e.table for e in tables if e.table)}"] if tables else [],
        "dump": dump,
    }


_PARSE = {"*string": "asString", "*int32": "asInt32", "*int64": "asInt64", "*decimal.Decimal": "asDecimal",
          "*bool": "asBool", "*time.Time": "asTime", "[]byte": "asBytes"}  # fmt: skip


def _text(field: FieldSpec, value: str) -> str:
    return f"{'zoned' if zoned(field.type) else 'text'}({value})"


def _fake(design: Design, port: Port) -> str:
    entities = {e.name for e in design.entities}
    methods = []
    for method in port.methods:
        params = "".join(f", {ident(p.name)} {go_type(p.type)}" for p in method.inputs)
        arguments = "".join(f", {_text(p, ident(p.name))}" for p in method.inputs)
        call = f'f.rec.call("{port.name}", "{method.name}"{arguments})'
        if method.returns is None:
            body = f"\t_, err := {call}\n\treturn err\n"
            result = "error"
        elif method.returns in entities:
            body = f"\t_, err := {call}\n\treturn nil, err\n"
            result = f"(*domain.{method.returns}, error)"
        else:
            kind = {"boolean": ("bool", "answerBool", "false"), "int": ("int", "answerInt", "0"),
                    "long": ("int64", "answerInt64", "0")}[method.returns]  # fmt: skip
            body = f"\tout, err := {call}\n\tif err != nil {{\n\t\treturn {kind[2]}, err\n\t}}\n\treturn {kind[1]}(out), nil\n"
            result = f"({kind[0]}, error)"
        methods.append(
            f"func (f *fake{port.name}) {pascal(method.name)}(_ context.Context{params}) {result} {{\n{body}}}\n"
        )
    return (
        f"// fake{port.name} is the external program {port.legacy_program}, answering what each case says it answered.\n"
        f"type fake{port.name} struct {{\n\trec *recorder\n}}\n\n" + "\n".join(methods)
    )


def glue(design: Design, use_case: UseCase) -> str:
    """The design-specific half of the harness: the service with its real adapters and fakes, and the conversion of
    the request and the response."""
    mod = module_path(design)
    ports = [next(p for p in design.ports if p.name == name) for name in use_case.ports]
    fakes = [p for p in ports if p.legacy_program]
    arguments = ", ".join(
        f"&fake{p.name}{{rec: rec}}" if p.legacy_program else f"pg.{constructor(adapter_name(p.name))}(db)"
        for p in ports
    )
    # The keys aligned as gofmt aligns them in a composite literal.
    width = max((len(pascal(f.name)) for f in use_case.inputs), default=0) + 1
    request = "".join(f"\t\t\t{(pascal(f.name) + ':').ljust(width)} {_PARSE[go_type(f.type)]}(in[\"{f.name}\"]),\n"
                      for f in use_case.inputs)  # fmt: skip
    width = max((len(f.name) for f in use_case.outputs), default=0) + 3
    response = "".join(f"\t\t\t{(json.dumps(f.name) + ':').ljust(width)} {_text(f, 'response.' + pascal(f.name))},\n"
                       for f in use_case.outputs)  # fmt: skip
    fake_types = [go_type(p.type) for port in fakes for m in port.methods for p in m.inputs]
    std = ["context", "errors", *(["time"] if any("time.Time" in t for t in fake_types) else [])]
    external = [DECIMAL] if any("decimal.Decimal" in t for t in fake_types) else []
    local = [f"{mod}/{APP}", f"{mod}/{DOMAIN}", f"{mod}/{PG}"]
    groups = [sorted(std), sorted(external), sorted(local)]
    imports = "\n\n".join("\n".join(f'\t"{i}"' for i in g) for g in groups if g)
    uses_db = any(not p.legacy_program for p in ports)
    return (
        "// Generated by the platform from the design: the use case of this golden master run, its adapters and the\n"
        "// fakes of the external programs. Never written by a model.\n"
        f"package main\n\nimport (\n{imports}\n)\n\n"
        "func open(url string) (store, error) {\n"
        "\tdb, err := pg.Open(url)\n\tif err != nil {\n\t\treturn nil, err\n\t}\n\treturn db, nil\n}\n\n"
        "func rejection(err error) (map[string]any, bool) {\n"
        "\tvar found *domain.BusinessError\n\tif !errors.As(err, &found) {\n\t\treturn nil, false\n\t}\n"
        '\treturn map[string]any{"code": found.Code, "legacy_code": found.LegacyCode, "message": found.Message}, true\n}\n\n'
        f"func build(s store, rec *recorder) execute {{\n"
        + ("\tdb := s.(*pg.DB)\n" if uses_db else "\t_ = s\n")
        + ("" if fakes else "\t_ = rec\n")
        + f"\tservice := app.New{use_case.name}Service({arguments})\n"
        "\treturn func(ctx context.Context, in map[string]*string) (map[string]*string, error) {\n"
        f"\t\t{'response' if use_case.outputs else '_'}, err := service.Execute(ctx, app.{use_case.name}Request{{\n{request}\t\t}})\n"
        "\t\tif err != nil {\n\t\t\treturn nil, err\n\t\t}\n"
        f"\t\treturn map[string]*string{{\n{response}\t\t}}, nil\n\t}}\n}}\n"
        + "".join(f"\n{_fake(design, p)}" for p in fakes)
    )


SCRIPT = rf"""
mkdir -p /work/p/{HARNESS_DIR}
cp /input/harness/runtime.go /input/harness/glue.go /work/p/{HARNESS_DIR}/
# M29 (ADR-0049): the harness is built with Go's coverage; the cases write their counters to /work/cov.
if ! go build -cover -coverpkg=./... -o /work/harness ./{HARNESS_DIR} > /work/harness.txt 2>&1; then
  echo "===HARNESS-FAILED==="; cat /work/harness.txt; exit 4
fi
if ! initdb -D /work/pg -U nexti --auth=trust -E UTF8 --no-locale > /work/pg-init.log 2>&1; then
  echo "===HARNESS-FAILED==="; cat /work/pg-init.log; exit 5
fi
if ! pg_ctl -D /work/pg -l /work/pg.log -o "-k /work -c listen_addresses=localhost -c port=5432 -F" -w start \
    > /dev/null; then
  echo "===HARNESS-FAILED==="; cat /work/pg.log; exit 5
fi
psql -h localhost -U nexti -d postgres -q -c "CREATE DATABASE nexti" > /dev/null
if ! psql -h localhost -U nexti -d nexti -q -v ON_ERROR_STOP=1 -f /work/p/{SCHEMA} > /work/schema.log 2>&1; then
  echo "===HARNESS-FAILED==="; cat /work/schema.log; exit 6
fi
mkdir -p /work/cov
echo "===EQUIVALENCE==="
GOCOVERDIR=/work/cov /work/harness /input/harness/plan.json /input/harness/cases.json 2>&1 || true
echo "===EQUIVALENCE-END==="
if go tool covdata textfmt -i=/work/cov -o /work/cover.out > /dev/null 2>&1 && [ -s /work/cover.out ]; then
  echo "===COVERAGE go==="; gzip -c /work/cover.out | base64 | tr -d "\n"; echo; echo "===COVERAGE-END==="
fi
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
    """Compiles the project (tests included, counted from `go test -json`) and runs every golden case on it."""
    recorded = [r for r in master.results if r.observation.error is None]
    cases = [target_case(design, use_case, r.case, defaults) for r in recorded]
    extra = {
        "harness/runtime.go": runtime_source(),
        "harness/glue.go": glue(design, use_case),
        "harness/plan.json": json.dumps(plan(design, use_case)),
        "harness/cases.json": json.dumps(cases),
    }
    build = await compile_and_test(sandbox, files, extra_inputs=extra, after=SCRIPT)
    found = masks(design, use_case, master)
    if not build.compiled:
        return EquivalenceRun(build, [], found, f"the project does not compile: {build.compile_errors[:300]}")
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
            # A trace has no legacy return code (ADR-0015): it can only say that the program rejected (-1).
            actual = actual.model_copy(update={"returns": -1})
        runs.append(CaseRun(recorded_case.case.name, expected, actual))
    return EquivalenceRun(build, runs, found)
