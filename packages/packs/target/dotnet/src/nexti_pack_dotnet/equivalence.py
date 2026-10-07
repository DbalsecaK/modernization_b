# ruff: noqa: S608 - the SQL is built from the design and runs only in the SQL Server inside the sandbox
"""The golden master on the generated .NET service (spec 11.3 check 3): the target cases of
`nexti_core.spec.equivalence` run by the platform's C# harness against SQL Server in the sandbox. SQL Server starts
from the seed the image prepared (system databases), in its own tmpfs, while the harness builds."""

import json
from collections.abc import Callable
from importlib.resources import files as package_files
from typing import Any

from nexti_core.spec.characterization import Case, GoldenMaster, Observation, Scalar
from nexti_core.spec.design import Design, UseCase
from nexti_core.spec.equivalence import (
    CaseRun,
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
from nexti_sandbox import Limits, Sandbox

__all__ = ["CaseRun", "EquivalenceRun", "Mask", "expected_view", "masks", "plan", "run_equivalence", "target_case"]

# The SA password only exists inside the sandbox, which has no network (infra/sandbox/dotnet/Dockerfile).
CONNECTION = ("Server=127.0.0.1,1433;Database=nexti;User Id=sa;Password=Nexti-Sandbox-Only-1;"
              "TrustServerCertificate=True;Encrypt=False")  # fmt: skip
# The ADO.NET connection class the harness opens (the plan names it, so one harness serves every database).
PROVIDER = "Microsoft.Data.SqlClient.SqlConnection, Microsoft.Data.SqlClient"


def harness_sources() -> dict[str, str]:
    folder = package_files("nexti_pack_dotnet") / "harness"
    return {name: (folder / name).read_text("utf-8") for name in ("Harness.csproj", "Program.cs")}


def plan(design: Design, use_case: UseCase) -> dict[str, Any]:
    """What the harness needs: the types, the ports (adapter or fake), how to reset and how to read the tables."""
    ns = namespace(design)
    ports = []
    for name in use_case.ports:
        port = next(p for p in design.ports if p.name == name)
        adapter = None if port.legacy_program else f"{ns}.Adapters.Out.Sql.{adapter_name(name)}, App"
        ports.append({"interface": f"{ns}.Domain.Port.{name}, App", "adapter": adapter})
    tables = [e for e in design.entities if e.table]
    dump = {}
    for entity in tables:
        columns = ", ".join(column_of(f.name, f.column) for f in entity.fields)
        order = ", ".join(column_of(k, next(f.column for f in entity.fields if f.name == k)) for k in entity.key)
        dump[entity.table] = f"SELECT {columns} FROM {entity.table}" + (f" ORDER BY {order}" if order else "")
    return {
        "provider": PROVIDER,
        "connection": CONNECTION,
        "db": f"{ns}.Infrastructure.Db, App",
        "service": f"{ns}.Application.{use_case.name}Service, App",
        "request": f"{ns}.Adapters.In.Rest.{use_case.name}Request, App",
        "ports": ports,
        "reset": [f"TRUNCATE TABLE {e.table}" for e in tables],
        "dump": dump,
    }


def target_case(
    design: Design, use_case: UseCase, case: Case, defaults: dict[str, Scalar] | None = None
) -> dict[str, Any]:
    """A legacy case in target terms, with SQL Server types for the rows to insert."""
    return neutral_target_case(design, use_case, case, defaults, sql_type)


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
) -> EquivalenceRun:
    """Compiles the project (tests included, counted from JUnit XML) and runs every golden case on it. Another
    database (Oracle) brings its own plan, case translation, script and limits; SQL Server is the default."""
    recorded = [r for r in master.results if r.observation.error is None]
    cases = [case_of(design, use_case, r.case, defaults) for r in recorded]
    extra = {f"harness/{name}": content for name, content in harness_sources().items()}
    extra.update({
        "harness/plan.json": json.dumps(harness_plan or plan(design, use_case)),
        "harness/cases.json": json.dumps(cases),
    })  # fmt: skip
    build = await compile_and_test(sandbox, files, extra_inputs=extra, after=script, limits=limits)
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
