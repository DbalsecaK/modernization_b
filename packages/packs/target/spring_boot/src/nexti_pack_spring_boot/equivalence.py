# ruff: noqa: S608 - the SQL is built from the design and runs only in the PostgreSQL inside the sandbox
"""The golden master on the generated Java service (spec 11.3 check 3): the target cases of
`nexti_core.spec.equivalence` run by the platform's Java harness against PostgreSQL in the sandbox."""

import json
from importlib.resources import files as package_files
from typing import Any

from nexti_core.spec.characterization import GoldenMaster, Observation, Scalar
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
from nexti_pack_spring_boot.build import compile_and_test
from nexti_pack_spring_boot.design import Design, UseCase
from nexti_pack_spring_boot.generate import adapter_path, sql_type
from nexti_sandbox import Sandbox

__all__ = ["CaseRun", "EquivalenceRun", "Mask", "expected_view", "masks", "plan", "run_equivalence", "target_case"]

HARNESS_CLASS = "nexti.equivalence.EquivalenceHarness"
JDBC_URL = "jdbc:postgresql://localhost:5432/nexti"


def harness_source() -> str:
    return (package_files("nexti_pack_spring_boot") / "harness" / "EquivalenceHarness.java").read_text("utf-8")


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
        columns = ", ".join(column_of(f.name, f.column) for f in entity.fields)
        order = ", ".join(column_of(k, next(f.column for f in entity.fields if f.name == k)) for k in entity.key)
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
    design: Design, use_case: UseCase, case: Any, defaults: dict[str, Scalar] | None = None
) -> dict[str, Any]:
    """A legacy case in target terms, with PostgreSQL types for the rows to insert."""
    return neutral_target_case(design, use_case, case, defaults, sql_type)


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
            # A trace has no legacy return code (a CICS program just shows its message): it can only say that the
            # program rejected (-1, ADR-0015). The target's rejection is compared as that, its message as usual.
            actual = actual.model_copy(update={"returns": -1})
        runs.append(CaseRun(recorded_case.case.name, expected, actual))
    return EquivalenceRun(build, runs, found)
