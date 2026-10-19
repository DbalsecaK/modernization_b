# ruff: noqa: S608 - the SQL is built from the design and runs only in the SQL Server inside the sandbox
"""The golden master on the generated .NET service (spec 11.3 check 3): the target cases of
`nexti_core.spec.equivalence` run by the platform's C# harness against SQL Server in the sandbox. SQL Server starts
from the seed the image prepared (system databases), in its own tmpfs, while the harness builds. With `same_database`
(ADR-0055) the cases run against the legacy's own engine instead, on the run's network: every port has its adapter
(the called programs are the engine's substitutes), each case is prepared by the engine's batches and the calls the
comparison judges come from the engine's log."""

import json
from collections.abc import Callable
from dataclasses import replace
from importlib.resources import files as package_files
from typing import Any

from nexti_core.spec.characterization import Case, GoldenMaster, Observation, Scalar
from nexti_core.spec.design import Design, UseCase
from nexti_core.spec.equivalence import (
    CaseRun,
    EngineTarget,
    EquivalenceRun,
    Mask,
    actual_view,
    column_of,
    expected_view,
    masks,
)
from nexti_core.spec.equivalence import target_case as neutral_target_case
from nexti_pack_dotnet.build import LIMITS, compile_and_test
from nexti_pack_dotnet.generate import SCHEMA, adapter_name, namespace, sql_type
from nexti_pack_dotnet.same_database import owns_transaction, unit_of_work_port
from nexti_pack_spring_boot.equivalence import CONCURRENCY, concurrency_case
from nexti_sandbox import Limits, Sandbox

__all__ = ["CaseRun", "EquivalenceRun", "Mask", "expected_view", "masks", "plan", "run_equivalence", "target_case"]

# The SA password only exists inside the sandbox, which has no network (infra/sandbox/dotnet/Dockerfile).
CONNECTION = ("Server=127.0.0.1,1433;Database=nexti;User Id=sa;Password=Nexti-Sandbox-Only-1;"
              "TrustServerCertificate=True;Encrypt=False")  # fmt: skip
# The ADO.NET connection class the harness opens (the plan names it, so one harness serves every database).
PROVIDER = "Microsoft.Data.SqlClient.SqlConnection, Microsoft.Data.SqlClient"
ASE_PROVIDER = "AdoNetCore.AseClient.AseConnection, AdoNetCore.AseClient"


def harness_sources() -> dict[str, str]:
    folder = package_files("nexti_pack_dotnet") / "harness"
    return {name: (folder / name).read_text("utf-8") for name in ("Harness.csproj", "Program.cs")}


def engine_connection(engine: EngineTarget) -> str:
    """The AseClient connection string of the engine the verification started (its JDBC URL, read)."""
    address, rest = engine.jdbc_url.split("//", 1)[1].split("/", 1)
    host, port = address.split(":")
    database = rest.split(";", 1)[0]
    return f"Data Source={host};Port={port};Database={database};Uid={engine.user};Pwd={engine.password};Charset=iso_1"


def plan(design: Design, use_case: UseCase, engine: EngineTarget | None = None) -> dict[str, Any]:
    """What the harness needs: the types, the ports (adapter or fake), how to reset and how to read the tables.
    Against the legacy's engine every port has its adapter, each case resets the engine itself and the calls come
    from the engine's log (ADR-0055)."""
    ns = namespace(design)
    ports = []
    for name in use_case.ports:
        port = next(p for p in design.ports if p.name == name)
        real = engine is not None or not port.legacy_program
        adapter = f"{ns}.Adapters.Out.Sql.{adapter_name(name)}, App" if real else None
        ports.append({"interface": f"{ns}.Domain.Port.{name}, App", "adapter": adapter})
    tables = [e for e in design.entities if e.table]
    dump = {}
    for entity in tables:
        columns = ", ".join(column_of(f.name, f.column) for f in entity.fields)
        order = ", ".join(column_of(k, next(f.column for f in entity.fields if f.name == k)) for k in entity.key)
        dump[entity.table] = f"SELECT {columns} FROM {entity.table}" + (f" ORDER BY {order}" if order else "")
    # Phase F: with a UnitOfWork port that begins, commits and rolls back, the service owns the transaction and the
    # harness does not wrap the use case.
    unit = unit_of_work_port(design)
    owned = owns_transaction(unit) and unit is not None and unit.name in use_case.ports
    common = {
        "db": f"{ns}.Infrastructure.Db, App",
        "service": f"{ns}.Application.{use_case.name}Service, App",
        "request": f"{ns}.Adapters.In.Rest.{use_case.name}Request, App",
        "ports": ports,
        "dump": dump,
        **({"service_transaction": True} if owned else {}),
    }
    if engine is not None:
        return {"provider": ASE_PROVIDER, "connection": engine_connection(engine), "reset": [],
                "calls": engine.calls_query, **common}  # fmt: skip
    return {"provider": PROVIDER, "connection": CONNECTION, "reset": [f"TRUNCATE TABLE {e.table}" for e in tables],
            **common}  # fmt: skip


def target_case(
    design: Design, use_case: UseCase, case: Case, defaults: dict[str, Scalar] | None = None,
    engine: EngineTarget | None = None,
) -> dict[str, Any]:  # fmt: skip
    """A legacy case in target terms, with SQL Server types for the rows to insert; against the legacy's engine the
    setup is the engine's own (rows and substitutes) and no port is faked."""
    found = neutral_target_case(design, use_case, case, defaults, sql_type)
    if engine is not None:
        found = {**found, "setup": engine.setup_for(case), "stubs": {}}
    return found


SCRIPT = rf"""
mkdir -p /work/harness && cp -r /input/harness/. /work/harness/
cp -r /opt/mssql-seed/. /var/opt/mssql/
/opt/mssql/bin/sqlservr > /work/sql.log 2>&1 &
HARNESS=/work/harness/Harness.csproj
if ! dotnet restore $HARNESS --source /opt/nuget -v q > /work/harness.txt 2>&1 \
    || ! dotnet build $HARNESS --no-restore $OPTS -o /work/harness-out > /work/harness.txt 2>&1; then
  echo "===HARNESS-FAILED==="; errors /work/harness.txt; exit 4
fi
for i in $(seq 1 150); do grep -q "now ready for client connections" /work/sql.log && break; sleep 1; done
SQL="sqlcmd -S 127.0.0.1,1433 -U sa -P $MSSQL_SA_PASSWORD -C -l 30 -b"
if ! $SQL -Q "CREATE DATABASE nexti" > /work/schema.log 2>&1 \
    || ! $SQL -d nexti -i /work/p/{SCHEMA} >> /work/schema.log 2>&1; then
  echo "===HARNESS-FAILED==="; cat /work/schema.log; tail -20 /work/sql.log; exit 6
fi
echo "===EQUIVALENCE==="
# M29 (ADR-0049): the harness runs under dotnet-coverage when the image has it (Cobertura report).
if [ -x /opt/tools/dotnet-coverage ]; then
  mkdir -p /work/tmp
  TMPDIR=/work/tmp DOTNET_CLI_HOME=/work /opt/tools/dotnet-coverage collect -f cobertura -o /work/coverage.xml \
    "dotnet /work/harness-out/Harness.dll /input/harness/plan.json /input/harness/cases.json" 2>&1 || true
else
  dotnet /work/harness-out/Harness.dll /input/harness/plan.json /input/harness/cases.json 2>&1 || true
fi
echo "===EQUIVALENCE-END==="
if [ -s /work/coverage.xml ]; then
  echo "===COVERAGE cobertura==="; gzip -c /work/coverage.xml | base64 | tr -d "\n"; echo; echo "===COVERAGE-END==="
fi
$SQL -Q "SHUTDOWN WITH NOWAIT" > /dev/null 2>&1 || true
"""

# ADR-0055: the golden master against the legacy's engine on the run's network; no SQL Server of the sandbox's own.
ENGINE_SCRIPT = r"""
mkdir -p /work/harness && cp -r /input/harness/. /work/harness/
HARNESS=/work/harness/Harness.csproj
if ! dotnet restore $HARNESS --source /opt/nuget -v q > /work/harness.txt 2>&1 \
    || ! dotnet build $HARNESS --no-restore $OPTS -o /work/harness-out > /work/harness.txt 2>&1; then
  echo "===HARNESS-FAILED==="; errors /work/harness.txt; exit 4
fi
echo "===EQUIVALENCE==="
if [ -x /opt/tools/dotnet-coverage ]; then
  mkdir -p /work/tmp
  TMPDIR=/work/tmp DOTNET_CLI_HOME=/work /opt/tools/dotnet-coverage collect -f cobertura -o /work/coverage.xml \
    "dotnet /work/harness-out/Harness.dll /input/harness/plan.json /input/harness/cases.json" 2>&1 || true
else
  dotnet /work/harness-out/Harness.dll /input/harness/plan.json /input/harness/cases.json 2>&1 || true
fi
echo "===EQUIVALENCE-END==="
if [ -s /work/coverage.xml ]; then
  echo "===COVERAGE cobertura==="; gzip -c /work/coverage.xml | base64 | tr -d "\n"; echo; echo "===COVERAGE-END==="
fi
"""


def raw_items(output: str) -> dict[str, Any]:
    """The harness's NXE lines by case name; the concurrency result keeps only its verdict (the two dumps are
    diagnostic)."""
    raw: dict[str, Any] = {}
    for line in output.split("===EQUIVALENCE===", 1)[-1].splitlines():
        if line.startswith("NXE "):
            item = json.loads(line[4:])
            raw[item["name"]] = item
    if CONCURRENCY in raw:
        for key in ("sequential", "concurrent"):
            raw[CONCURRENCY].pop(key, None)
    return raw


async def run_equivalence(
    sandbox: Sandbox,
    files: dict[str, str],
    design: Design,
    use_case: UseCase,
    master: GoldenMaster,
    defaults: dict[str, Scalar] | None = None,
    *,
    harness_plan: dict[str, Any] | None = None,
    case_of: Callable[[Design, UseCase, Case, dict[str, Scalar] | None], dict[str, Any]] = target_case,
    script: str = SCRIPT,
    limits: Limits = LIMITS,
    engine: EngineTarget | None = None,
) -> EquivalenceRun:
    """Compiles the project (tests included, counted from JUnit XML) and runs every golden case on it. Another
    database (Oracle) brings its own plan, case translation, script and limits; SQL Server is the default. With
    `engine` the cases run against the legacy's engine on the run's network (ADR-0055)."""
    recorded = [r for r in master.results if r.observation.error is None]
    if engine is not None:
        cases = [target_case(design, use_case, r.case, defaults, engine) for r in recorded]
        chosen_plan = plan(design, use_case, engine)
        script = ENGINE_SCRIPT
        limits = replace(LIMITS, network=engine.network, timeout_seconds=1800, max_output_bytes=16 * 1024 * 1024)
    else:
        cases = [case_of(design, use_case, r.case, defaults) for r in recorded]
        chosen_plan = harness_plan or plan(design, use_case)
    chosen = concurrency_case(design, use_case, master)
    if chosen is not None and harness_plan is None:  # Oracle brings its own plan and harness flavour
        chosen_plan = {**chosen_plan, "concurrency": chosen}
    extra = {f"harness/{name}": content for name, content in harness_sources().items()}
    extra.update({"harness/plan.json": json.dumps(chosen_plan), "harness/cases.json": json.dumps(cases)})
    build = await compile_and_test(sandbox, files, extra_inputs=extra, after=script, limits=limits)
    found = masks(design, use_case, master)
    if not build.compiled:
        return EquivalenceRun(build, [], found, f"the project does not compile: {build.compile_errors[:300]}")
    if "===HARNESS-FAILED===" in build.after_output:
        return EquivalenceRun(build, [], found, build.after_output.split("===HARNESS-FAILED===", 1)[1][:3000])
    raw = raw_items(build.after_output)
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
GOLDEN_MASTER_DIR = "tools/golden-master"
_README = """# Golden master of this project

Generated by the platform (ADR-0056). The cases the verification proved this project against, runnable here: every
case of `cases.json` runs through the services of this project and what it did is compared with `expected.json`, what
the platform observed when the verdict was signed.

ONLY AGAINST A TEST ENGINE: each case empties and reloads the tables of the suite and, on the legacy's engine, replaces
the programs the legacy calls by substitutes that answer as the case says.

    export NEXTI_LEGACY_CONNECTION="Data Source=HOST;Port=5000;Database=DATABASE;Uid=USER;Pwd=PASSWORD;Charset=iso_1"
    cd tools/golden-master && dotnet run -- plan.json cases.json expected.json

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
    harness as a tool of the solution, the cases and the plan without the platform's credentials, and what the
    platform observed (`expected.json`). Nothing when the harness did not run."""
    if run.problem or not run.raw:
        return {}
    recorded = [r for r in master.results if r.observation.error is None]
    cases = [target_case(design, use_case, r.case, defaults, engine) for r in recorded]
    stripped = {**plan(design, use_case, engine), "connection": ""}
    chosen = concurrency_case(design, use_case, master)
    if chosen is not None:
        stripped["concurrency"] = chosen
    expected = {name: {k: v for k, v in item.items() if k != "name"} for name, item in run.raw.items()}
    sources = harness_sources()
    project = sources["Harness.csproj"].replace("/work/p/src/App/App.csproj", "../../src/App/App.csproj")
    return {
        f"{GOLDEN_MASTER_DIR}/Harness.csproj": project,
        f"{GOLDEN_MASTER_DIR}/Program.cs": sources["Program.cs"],
        f"{GOLDEN_MASTER_DIR}/plan.json": json.dumps(stripped, indent=1),
        f"{GOLDEN_MASTER_DIR}/cases.json": json.dumps(cases, indent=1),
        f"{GOLDEN_MASTER_DIR}/expected.json": json.dumps(expected, indent=1, sort_keys=True),
        f"{GOLDEN_MASTER_DIR}/README.md": _README,
    }
