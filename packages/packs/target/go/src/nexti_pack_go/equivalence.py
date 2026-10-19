# ruff: noqa: S608, E501 - the SQL is built from the design and runs only in the PostgreSQL inside the sandbox
"""The golden master on the generated Go service (spec 11.3 check 3): the target cases of
`nexti_core.spec.equivalence` run by the platform's Go harness against PostgreSQL in the sandbox. Go has no runtime
proxies or constructors by name, so the harness has two files: `runtime.go`, the same for every design (cases, fakes'
recorder, transaction, table dump, JSON lines), and `glue.go`, generated here from the design without judgement: it
builds the use case service with the real adapters and one fake per external program, and converts the request and
the response. Both print the lines the Java harness prints, so the comparison is the same code for every pack.

With `same_database` (ADR-0055) the cases run against the legacy's own engine on the run's network: every port has
its adapter (the called programs are the engine's substitutes), each case is prepared by the engine's batches, and the
calls the comparison judges come from the engine's log."""

import json
from dataclasses import replace
from importlib.resources import files as package_files
from typing import Any

from nexti_core.spec import neutral_types as nt
from nexti_core.spec.characterization import GoldenMaster, Observation, Scalar
from nexti_core.spec.design import Design, FieldSpec, Port, UseCase
from nexti_core.spec.equivalence import (
    CaseRun,
    EngineTarget,
    EquivalenceRun,
    Mask,
    actual_view,
    column_of,
    engine_seconds,
    expected_view,
    masks,
)
from nexti_pack_go.build import LIMITS, compile_and_test
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
    service_owns_transaction,
    zoned,
)
from nexti_pack_go.same_database import same_database
from nexti_pack_spring_boot.equivalence import CONCURRENCY, concurrency_case
from nexti_pack_spring_boot.equivalence import target_case as postgresql_target_case
from nexti_sandbox import Sandbox

__all__ = ["CaseRun", "EquivalenceRun", "Mask", "expected_view", "glue", "masks", "plan", "run_equivalence",
           "target_case"]  # fmt: skip

URL = "postgres://nexti@localhost:5432/nexti?sslmode=disable"
HARNESS_DIR = "cmd/nexti-equivalence"


def target_case(
    design: Design, use_case: UseCase, case: Any, defaults: dict[str, Scalar] | None = None,
    engine: EngineTarget | None = None,
) -> dict[str, Any]:  # fmt: skip
    """The rows go in with PostgreSQL types, as for the Spring Boot pack; against the legacy's engine the setup is the
    engine's own (rows and substitutes) and no port is faked."""
    return postgresql_target_case(design, use_case, case, defaults, engine)


def runtime_source() -> str:
    return (package_files("nexti_pack_go") / "harness" / "runtime.go").read_text("utf-8")


def engine_url(engine: EngineTarget) -> str:
    """The tds URL of the engine the verification started (its JDBC URL, read)."""
    address, rest = engine.jdbc_url.split("//", 1)[1].split("/", 1)
    database = rest.split(";", 1)[0]
    return f"tds://{engine.user}:{engine.password}@{address}/{database}?charset=iso_1"


def _column_text(neutral: str, column: str) -> str:
    """The column in the canonical text of its type, computed by PostgreSQL so the harness reads only text."""
    value = nt.parse(neutral)
    if isinstance(value, nt.Binary):
        return f"encode({column}, 'hex') AS {column}"
    if isinstance(value, nt.Timestamp) and value.tz:
        return (f"to_char({column} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS') || '+00:00' AS {column}")  # fmt: skip
    return f"{column}::text AS {column}"


def plan(design: Design, use_case: UseCase, engine: EngineTarget | None = None) -> dict[str, Any]:
    """What the runtime needs: where the database is, how to reset it and how to read every table as text. Against
    the legacy's engine the tables are read in their own types (the runtime writes their canonical text), nothing
    is reset (each case prepares the engine) and the calls come from the engine's log."""
    tables = [e for e in design.entities if e.table]
    dump = []
    for entity in tables:
        if engine is not None:
            columns = ", ".join(column_of(f.name, f.column) for f in entity.fields)
        else:
            columns = ", ".join(_column_text(f.type, column_of(f.name, f.column)) for f in entity.fields)
        order = ", ".join(column_of(k, next(f.column for f in entity.fields if f.name == k)) for k in entity.key)
        dump.append({"table": entity.table,
                     "sql": f"SELECT {columns} FROM {entity.table}" + (f" ORDER BY {order}" if order else "")})  # fmt: skip
    if engine is not None:
        return {"url": engine_url(engine), "reset": [], "dump": dump, "calls": engine.calls_query}
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
        call = f'f.rec.call(ctx, "{port.name}", "{method.name}"{arguments})'
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
            f"func (f *fake{port.name}) {pascal(method.name)}(ctx context.Context{params}) {result} {{\n{body}}}\n"
        )
    return (
        f"// fake{port.name} is the external program {port.legacy_program}, answering what each case says it answered.\n"
        f"type fake{port.name} struct {{\n\trec *recorder\n}}\n\n" + "\n".join(methods)
    )


def glue(design: Design, use_case: UseCase, engine: bool = False) -> str:
    """The design-specific half of the harness: the service with its real adapters and fakes, and the conversion of
    the request and the response. `engine`: the cases run on the legacy's engine, where no port is faked."""
    mod = module_path(design)
    ports = [next(p for p in design.ports if p.name == name) for name in use_case.ports]
    fakes = [] if engine else [p for p in ports if p.legacy_program]
    arguments = ", ".join(
        f"&fake{p.name}{{rec: rec}}" if p in fakes else f"pg.{constructor(adapter_name(p.name))}(db)" for p in ports
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
    uses_db = any(p not in fakes for p in ports)
    collected = same_database(design)
    owned = service_owns_transaction(design, use_case)
    return (
        "// Generated by the platform from the design: the use case of this golden master run, its adapters and the\n"
        "// fakes of the external programs. Never written by a model.\n"
        f"package main\n\nimport (\n{imports}\n)\n\n"
        "func open(url string) (store, error) {\n"
        "\tdb, err := pg.Open(url)\n\tif err != nil {\n\t\treturn nil, err\n\t}\n\treturn db, nil\n}\n\n"
        "func rejection(err error) (map[string]any, bool) {\n"
        "\tvar found *domain.BusinessError\n\tif !errors.As(err, &found) {\n\t\treturn nil, false\n\t}\n"
        '\treturn map[string]any{"code": found.Code, "legacy_code": found.LegacyCode, "message": found.Message}, true\n}\n\n'
        "// collect is ctx with a collector of the messages the called programs raise (ADR-0056), and how to read them.\n"
        "func collect(ctx context.Context) (context.Context, func() []string) {\n"
        + ("\treturn pg.WithMessages(ctx)\n" if collected else "\treturn ctx, func() []string { return nil }\n")
        + "}\n\n"
        "// transact is how the request runs the use case: in one transaction, or (phase F) on a bound connection when\n"
        "// the service owns its unit of work.\n"
        "func transact(s store) func(ctx context.Context, fn func(ctx context.Context) error) error {\n"
        + ("\treturn s.(*pg.DB).InConn\n" if owned else "\treturn s.InTx\n")
        + "}\n\n"
        "func build(s store, rec *recorder) execute {\n"
        + ("\tdb := s.(*pg.DB)\n" if uses_db else "\t_ = s\n")
        + ("" if fakes else "\t_ = rec\n")
        # ADR-0055: the effects of a substitute run on the transaction the context carries (db.Q), as the adapters do.
        + (
            "\trec.exec = func(ctx context.Context, query string) (int64, error) {\n"
            "\t\tresult, err := db.Q(ctx).ExecContext(ctx, query)\n"
            "\t\tif err != nil {\n\t\t\treturn 0, err\n\t\t}\n\t\treturn result.RowsAffected()\n\t}\n"
            if uses_db and fakes
            else ""
        )
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

# ADR-0055: the golden master against the legacy's engine on the run's network; no PostgreSQL of the sandbox's own.
ENGINE_SCRIPT = rf"""
mkdir -p /work/p/{HARNESS_DIR}
cp /input/harness/runtime.go /input/harness/glue.go /work/p/{HARNESS_DIR}/
if ! go build -cover -coverpkg=./... -o /work/harness ./{HARNESS_DIR} > /work/harness.txt 2>&1; then
  echo "===HARNESS-FAILED==="; cat /work/harness.txt; exit 4
fi
mkdir -p /work/cov
echo "===EQUIVALENCE==="
GOCOVERDIR=/work/cov /work/harness /input/harness/plan.json /input/harness/cases.json 2>&1 || true
echo "===EQUIVALENCE-END==="
if go tool covdata textfmt -i=/work/cov -o /work/cover.out > /dev/null 2>&1 && [ -s /work/cover.out ]; then
  echo "===COVERAGE go==="; gzip -c /work/cover.out | base64 | tr -d "\n"; echo; echo "===COVERAGE-END==="
fi
"""


async def run_equivalence(
    sandbox: Sandbox,
    files: dict[str, str],
    design: Design,
    use_case: UseCase,
    master: GoldenMaster,
    defaults: dict[str, Scalar] | None = None,
    engine: EngineTarget | None = None,
) -> EquivalenceRun:
    """Compiles the project (tests included, counted from `go test -json`) and runs every golden case on it. With
    `engine` the cases run against the legacy's engine on the run's network (ADR-0055)."""
    recorded = [r for r in master.results if r.observation.error is None]
    cases = [target_case(design, use_case, r.case, defaults, engine) for r in recorded]
    harness_plan = plan(design, use_case, engine)
    chosen = concurrency_case(design, use_case, master)
    if chosen is not None:
        harness_plan["concurrency"] = chosen
    extra = {
        "harness/runtime.go": runtime_source(),
        "harness/glue.go": glue(design, use_case, engine=engine is not None),
        "harness/plan.json": json.dumps(harness_plan),
        "harness/cases.json": json.dumps(cases),
    }
    if engine is not None:
        limits = replace(
            LIMITS,
            network=engine.network,
            timeout_seconds=engine_seconds(len(cases) + 2),
            max_output_bytes=16 * 1024 * 1024,
        )
        build = await compile_and_test(sandbox, files, extra_inputs=extra, after=ENGINE_SCRIPT, limits=limits)
    else:
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
    if CONCURRENCY in raw:
        for key in ("sequential", "concurrent"):  # the two dumps are diagnostic
            raw[CONCURRENCY].pop(key, None)
    runs = []
    for recorded_case in recorded:
        item = raw.get(recorded_case.case.name)
        expected = expected_view(design, use_case, recorded_case.observation, found, strict_calls=engine is not None)
        if item is None or item.get("failure"):
            failure = (item or {}).get("failure") or "the harness printed nothing for this case"
            runs.append(CaseRun(recorded_case.case.name, expected, Observation(), failure))
            continue
        rejected = recorded_case.observation.returns not in (0, None)
        logged = engine.calls(item.get("legacy_calls", [])) if engine is not None else None
        actual = actual_view(design, use_case, item, found, rejected, logged)
        if master.from_traces and actual.returns not in (0, None):
            # A trace has no legacy return code (ADR-0015): it can only say that the program rejected (-1).
            actual = actual.model_copy(update={"returns": -1})
        runs.append(CaseRun(recorded_case.case.name, expected, actual))
    return EquivalenceRun(build, runs, found, raw=raw)


# -- ADR-0056 (phase E): the golden master travels with the delivery, runnable by the customer ------------------------
GOLDEN_MASTER_DIR = "testdata/golden-master"
_README = """# Golden master of this project

Generated by the platform (ADR-0056). The cases the verification proved this project against, runnable here: every
case of `cases.json` runs through the services of this project and what it did is compared with `expected.json`, what
the platform observed when the verdict was signed.

ONLY AGAINST A TEST ENGINE: each case empties and reloads the tables of the suite and, on the legacy's engine, replaces
the programs the legacy calls by substitutes that answer as the case says.

    export NEXTI_LEGACY_URL="tds://USER:PASSWORD@HOST:5000/DATABASE?charset=iso_1"
    go run ./cmd/nexti-equivalence testdata/golden-master/plan.json testdata/golden-master/cases.json testdata/golden-master/expected.json

The run ends with `GOLDEN MASTER REPRODUCED`, or lists each case that no longer reproduces and exits with 1.
"""


def delivery_files(
    design: Design,
    use_case: UseCase,
    run: EquivalenceRun,
    master: GoldenMaster,
    defaults: dict[str, Scalar] | None = None,
    engine: EngineTarget | None = None,
) -> dict[str, str]:
    """What the delivery adds so the customer can run the golden master on a test engine (ADR-0056, phase E): the
    harness as a command of the module, the cases and the plan without the platform's credentials, and what the
    platform observed (`expected.json`). Nothing when the harness did not run."""
    if run.problem or not run.raw:
        return {}
    recorded = [r for r in master.results if r.observation.error is None]
    cases = [target_case(design, use_case, r.case, defaults, engine) for r in recorded]
    stripped = {**plan(design, use_case, engine), "url": ""}
    chosen = concurrency_case(design, use_case, master)
    if chosen is not None:
        stripped["concurrency"] = chosen
    expected = {name: {k: v for k, v in item.items() if k != "name"} for name, item in run.raw.items()}
    return {
        f"{HARNESS_DIR}/runtime.go": runtime_source(),
        f"{HARNESS_DIR}/glue.go": glue(design, use_case, engine=engine is not None),
        f"{GOLDEN_MASTER_DIR}/plan.json": json.dumps(stripped, indent=1),
        f"{GOLDEN_MASTER_DIR}/cases.json": json.dumps(cases, indent=1),
        f"{GOLDEN_MASTER_DIR}/expected.json": json.dumps(expected, indent=1, sort_keys=True),
        f"{GOLDEN_MASTER_DIR}/README.md": _README,
    }
