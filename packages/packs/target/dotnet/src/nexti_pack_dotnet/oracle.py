"""Oracle as the persistence of the .NET pack (spec 8.4, ADR-0031), as M8b did for Spring Boot (ADR-0021): the
ADO.NET adapters over Oracle.ManagedDataAccess.Core, the neutral types in Oracle 23ai with the reserved columns quoted
(the Spring Boot pack's `oracle_type`, `quoted` and `schema`, reused as they are), and the golden master run by the
pack's C# harness against Oracle Database Free inside the sandbox (`nexti-sandbox-dotnet-oracle`). The sandbox gives
that image the two exceptions of Oracle: a network of its own with no route out, and its writable layer with the
unprivileged `oracle` user."""

from typing import Any

from nexti_core.spec.characterization import GoldenMaster, Scalar
from nexti_core.spec.design import Design, UseCase
from nexti_core.spec.equivalence import EquivalenceRun
from nexti_pack_dotnet import equivalence
from nexti_pack_dotnet.build import LIMITS as BUILD_LIMITS
from nexti_pack_dotnet.generate import APP, PACKAGES, SCHEMA
from nexti_pack_dotnet.generate import skeleton as base_skeleton
from nexti_pack_spring_boot import oracle as java_oracle
from nexti_pack_spring_boot.oracle import PASSWORD, RESERVED, SERVICE, SESSION, USER, oracle_type, quoted, schema
from nexti_sandbox import Limits, Sandbox

IMAGE = "nexti-sandbox-dotnet-oracle:1"
# The exact versions restored in the image (infra/sandbox/dotnet-oracle/seed/Seed.csproj): keep both lists equal.
ORACLE_CLIENT = "Oracle.ManagedDataAccess.Core"
ORACLE_PACKAGES = {ORACLE_CLIENT: "23.26.301"} | {k: v for k, v in PACKAGES.items() if k != "Microsoft.Data.SqlClient"}
# Oracle and the .NET build together need more memory and time; the exceptions of ADR-0021 apply only to this engine.
# xUnit v3 runs each test project as its own executable, so /work allows running what it builds (ADR-0017).
ORACLE_LIMITS = Limits(cpus=2.0, memory_mb=4608, pids=1024, timeout_seconds=1800, work_mb=BUILD_LIMITS.work_mb,
                       max_output_bytes=4 * 1024 * 1024, work_exec=True, internal_network=True, writable_root=True,
                       user="54321:54321")  # fmt: skip
PROVIDER = "Oracle.ManagedDataAccess.Client.OracleConnection, Oracle.ManagedDataAccess"
# A throwaway database without network (infra/sandbox/dotnet-oracle/Dockerfile): not secrets.
CONNECTION = f"User Id={USER};Password={PASSWORD};Data Source=localhost:1521/{SERVICE}"
DB = f"{APP}/Infrastructure/Db.cs"
PROJECT = f"{APP}/App.csproj"


def skeleton(design: Design) -> dict[str, str]:
    """The .NET skeleton with Oracle: its schema, its client package and the session over OracleConnection, whose
    commands bind parameters by name (ODP.NET binds by position unless told otherwise)."""
    files = base_skeleton(design)
    files[SCHEMA] = schema(design)
    files[PROJECT] = files[PROJECT].replace(
        f'Include="Microsoft.Data.SqlClient" Version="{PACKAGES["Microsoft.Data.SqlClient"]}"',
        f'Include="{ORACLE_CLIENT}" Version="{ORACLE_PACKAGES[ORACLE_CLIENT]}"',
    )
    db = files[DB].replace("using Microsoft.Data.SqlClient;", "using Oracle.ManagedDataAccess.Client;")
    for name in ("Connection", "Transaction", "Command"):
        db = db.replace(f"Sql{name}", f"Oracle{name}")
    bound = "command.Transaction = Transaction;\n"
    files[DB] = db.replace(bound, f"{bound}        command.BindByName = true;\n")
    return files


def oracle_plan(design: Design, use_case: UseCase) -> dict[str, Any]:
    """The plan of the C# harness with Oracle's provider, connection and session, and the Java pack's Oracle reset and
    reads (dates and timestamps as ISO text with TO_CHAR, every column under its lower-case name)."""
    java = java_oracle.oracle_plan(design, use_case)
    return {**equivalence.plan(design, use_case), "provider": PROVIDER, "connection": CONNECTION,
            "session": SESSION, "reset": java["reset"], "dump": java["dump"]}  # fmt: skip


target_case = java_oracle.target_case

SCRIPT = rf"""
mkdir -p /work/harness && cp -r /input/harness/. /work/harness/
/opt/oracle/container-entrypoint.sh > /work/oracle.log 2>&1 &
HARNESS=/work/harness/Harness.csproj
if ! dotnet restore $HARNESS --source /opt/nuget -v q > /work/harness.txt 2>&1 \
    || ! dotnet build $HARNESS --no-restore $OPTS -o /work/harness-out > /work/harness.txt 2>&1; then
  echo "===HARNESS-FAILED==="; errors /work/harness.txt; exit 4
fi
for i in $(seq 1 300); do
  grep -q "DATABASE IS READY" /work/oracle.log && break
  grep -q "ORA-00600" /work/oracle.log && break
  sleep 1
done
if ! grep -q "DATABASE IS READY" /work/oracle.log; then
  echo "===HARNESS-FAILED==="; echo "Oracle did not start"; tail -40 /work/oracle.log; exit 5
fi
( echo "WHENEVER SQLERROR EXIT FAILURE"; cat /work/p/{SCHEMA}; echo "EXIT" ) > /work/schema-run.sql
if ! sqlplus -s {USER}/{PASSWORD}@localhost/{SERVICE} @/work/schema-run.sql > /work/schema.log 2>&1; then
  echo "===HARNESS-FAILED==="; cat /work/schema.log; exit 6
fi
echo "===EQUIVALENCE==="
dotnet /work/harness-out/Harness.dll /input/harness/plan.json /input/harness/cases.json 2>&1 || true
echo "===EQUIVALENCE-END==="
"""


async def run_equivalence(
    sandbox: Sandbox, files: dict[str, str], design: Design, use_case: UseCase, master: GoldenMaster,
    defaults: dict[str, Scalar] | None = None,
) -> EquivalenceRun:  # fmt: skip
    """Compiles the project (tests included) and runs every golden case on it against Oracle."""
    return await equivalence.run_equivalence(
        sandbox, files, design, use_case, master, defaults, harness_plan=oracle_plan(design, use_case),
        case_of=target_case, script=SCRIPT, limits=ORACLE_LIMITS,
    )  # fmt: skip


__all__ = ["IMAGE", "ORACLE_LIMITS", "ORACLE_PACKAGES", "RESERVED", "oracle_plan", "oracle_type", "quoted",
           "run_equivalence", "schema", "skeleton", "target_case"]  # fmt: skip
