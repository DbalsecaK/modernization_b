# ruff: noqa: S608 - the SQL is built from the design and runs only in the PostgreSQL inside the sandbox
"""The golden master on the generated Java service (spec 11.3 check 3): the target cases of
`nexti_core.spec.equivalence` run by the platform's Java harness against PostgreSQL in the sandbox."""

import json
from dataclasses import replace
from importlib.resources import files as package_files
from typing import Any

from nexti_core.spec.characterization import GoldenMaster, Observation, Scalar
from nexti_core.spec.design import writes
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
from nexti_pack_spring_boot.build import LIMITS, compile_and_test
from nexti_pack_spring_boot.design import Design, UseCase
from nexti_pack_spring_boot.generate import adapter_path, owns_transaction, sql_type, unit_of_work_port
from nexti_sandbox import Sandbox

__all__ = ["CaseRun", "EquivalenceRun", "Mask", "expected_view", "masks", "plan", "run_equivalence", "target_case"]

HARNESS_CLASS = "nexti.equivalence.EquivalenceHarness"
JDBC_URL = "jdbc:postgresql://localhost:5432/nexti"


def harness_source(flavour: str = "") -> str:
    """The harness of the Spring Boot pack (Spring JDBC), or of one of its frameworks (`quarkus`: plain JDBC over a
    DataSource). Every flavour is the class `nexti.equivalence.EquivalenceHarness` and prints the same lines."""
    folder = package_files("nexti_pack_spring_boot") / "harness"
    return (folder / flavour / "EquivalenceHarness.java" if flavour else folder / "EquivalenceHarness.java").read_text(
        "utf-8"
    )


def plan(design: Design, use_case: UseCase, engine: EngineTarget | None = None) -> dict[str, Any]:
    """What the harness needs: the classes, the ports (adapter or fake), how to reset and how to read the tables.
    Against the legacy's engine (ADR-0055) every port has its adapter (the called programs are the engine's
    substitutes), each case resets the engine itself, and the calls come from the engine's log."""
    ports = []
    for name in use_case.ports:
        port = next(p for p in design.ports if p.name == name)
        real = engine is not None or not port.legacy_program
        adapter = adapter_path(design, port).split("src/main/java/", 1)[1] if real else None
        ports.append({"interface": f"{design.base_package}.domain.port.{name}",
                      "adapter": adapter.removesuffix(".java").replace("/", ".") if adapter else None})  # fmt: skip
    # Phase F: with a UnitOfWork port that begins, commits and rolls back, the service owns the transaction and
    # the harness does not wrap the use case (the legacy begins after some work and returns after committing).
    unit = unit_of_work_port(design)
    owned = unit is not None and owns_transaction(unit) and unit.name in use_case.ports
    tables = [e for e in design.entities if e.table]
    dump = {}
    for entity in tables:
        columns = ", ".join(column_of(f.name, f.column) for f in entity.fields)
        order = ", ".join(column_of(k, next(f.column for f in entity.fields if f.name == k)) for k in entity.key)
        dump[entity.table] = f"SELECT {columns} FROM {entity.table}" + (f" ORDER BY {order}" if order else "")
    if engine is not None:
        return {
            "jdbc_url": engine.jdbc_url, "user": engine.user, "password": engine.password,
            "service": f"{design.base_package}.application.{use_case.name}Service",
            "request": f"{design.base_package}.adapters.in.rest.{use_case.name}Request",
            "ports": ports, "reset": [], "dump": dump, "calls": engine.calls_query,
            **({"service_transaction": True} if owned else {}),
        }  # fmt: skip
    return {
        "jdbc_url": JDBC_URL,
        "user": "nexti",
        "service": f"{design.base_package}.application.{use_case.name}Service",
        "request": f"{design.base_package}.adapters.in.rest.{use_case.name}Request",
        "ports": ports,
        "reset": [f"TRUNCATE {', '.join(e.table for e in tables if e.table)}"] if tables else [],
        "dump": dump,
        **({"service_transaction": True} if owned else {}),
    }


CONCURRENCY = "__concurrency__"  # the name of the harness's concurrency result among the cases (ADR-0056)


def concurrency_case(design: Design, use_case: UseCase, master: GoldenMaster) -> str | None:
    """The case the harness runs twice at the same time (ADR-0056, point 12): the first one the legacy accepted and
    that changed a row, for a use case with a unit of work. None when there is nothing to contend for."""
    if use_case.unit_of_work is None and not writes(design, use_case):
        return None
    for recorded in master.results:
        observation = recorded.observation
        if observation.error is not None or observation.returns not in (0, None):
            continue
        before = {t.lower(): rows for t, rows in recorded.case.setup.items()}
        after = {t.lower(): rows for t, rows in observation.tables.items()}
        for table, rows in after.items():
            initial = before.get(table, [])
            seen = {str(x) for row in initial for x in row.values()}
            if len(rows) != len(initial) or any(str(v) not in seen for row in rows for v in row.values()):
                return recorded.case.name
    return None


def target_case(
    design: Design, use_case: UseCase, case: Any, defaults: dict[str, Scalar] | None = None,
    engine: EngineTarget | None = None,
) -> dict[str, Any]:  # fmt: skip
    """A legacy case in target terms, with PostgreSQL types for the rows to insert. Against the legacy's engine the
    setup is the engine's own (rows and substitutes, ADR-0055) and no port is faked."""
    found = neutral_target_case(design, use_case, case, defaults, sql_type)
    if engine is not None:
        found = {**found, "setup": engine.setup_for(case), "stubs": {}}
    return found


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
# M29 (ADR-0049): the harness runs under JaCoCo when the image has it; only the target's classes are reported.
AGENT=""
[ -f /opt/coverage/jacocoagent.jar ] && AGENT="-javaagent:/opt/coverage/jacocoagent.jar=destfile=/work/jacoco.exec"
echo "===EQUIVALENCE==="
java $AGENT -cp "/work/out:/work/harness-out:/opt/lib/*" nexti.equivalence.EquivalenceHarness \
  /input/harness/plan.json /input/harness/cases.json 2>&1 || true
echo "===EQUIVALENCE-END==="
if [ -n "$AGENT" ] && [ -f /work/jacoco.exec ] && java -jar /opt/coverage/jacococli.jar report /work/jacoco.exec \
    --classfiles /work/out --xml /work/jacoco.xml > /dev/null 2>&1; then
  echo "===COVERAGE jacoco==="; gzip -c /work/jacoco.xml | base64 | tr -d "\n"; echo; echo "===COVERAGE-END==="
fi
pg_ctl -D /work/pg -m fast stop > /dev/null 2>&1 || true
"""

# ADR-0055: the golden master against the legacy's engine on the run's network; no database of the sandbox's own.
ENGINE_SCRIPT = r"""
mkdir -p /work/harness-out
if ! javac -nowarn -encoding UTF-8 -d /work/harness-out -cp "/work/out:/opt/lib/*" \
    /input/harness/EquivalenceHarness.java 2> /work/javac.txt; then
  echo "===HARNESS-FAILED==="; cat /work/javac.txt; exit 4
fi
for i in $(seq 1 90); do (exec 3<>/dev/tcp/ENGINE_HOST/ENGINE_PORT) > /dev/null 2>&1 && break; sleep 2; done
AGENT=""
[ -f /opt/coverage/jacocoagent.jar ] && AGENT="-javaagent:/opt/coverage/jacocoagent.jar=destfile=/work/jacoco.exec"
echo "===EQUIVALENCE==="
java $AGENT -cp "/work/out:/work/harness-out:/opt/lib/*" nexti.equivalence.EquivalenceHarness \
  /input/harness/plan.json /input/harness/cases.json 2>&1 || true
echo "===EQUIVALENCE-END==="
if [ -n "$AGENT" ] && [ -f /work/jacoco.exec ] && java -jar /opt/coverage/jacococli.jar report /work/jacoco.exec \
    --classfiles /work/out --xml /work/jacoco.xml > /dev/null 2>&1; then
  echo "===COVERAGE jacoco==="; gzip -c /work/jacoco.xml | base64 | tr -d "\n"; echo; echo "===COVERAGE-END==="
fi
"""


def engine_script(engine: EngineTarget) -> str:
    host, port = engine.jdbc_url.split("//", 1)[1].split("/", 1)[0].split(":")
    return ENGINE_SCRIPT.replace("ENGINE_HOST", host).replace("ENGINE_PORT", port)


async def run_equivalence(
    sandbox: Sandbox,
    files: dict[str, str],
    design: Design,
    use_case: UseCase,
    master: GoldenMaster,
    defaults: dict[str, Scalar] | None = None,
    harness: str | None = None,
    engine: EngineTarget | None = None,
) -> EquivalenceRun:
    """Compiles the project (tests included, counted from JUnit XML) and runs every golden case on it. `harness` is the
    source of the harness when the project's framework is not Spring (Quarkus, ADR-0028). With `engine` the cases
    run against the legacy's engine on the run's network instead of the sandbox's PostgreSQL (ADR-0055)."""
    recorded = [r for r in master.results if r.observation.error is None]
    cases = [target_case(design, use_case, r.case, defaults, engine) for r in recorded]
    harness_plan = plan(design, use_case, engine)
    chosen = concurrency_case(design, use_case, master)
    if chosen is not None and harness is None:  # the Spring harness runs it; the Quarkus one does not yet
        harness_plan["concurrency"] = chosen
    extra = {
        "harness/EquivalenceHarness.java": harness if harness is not None else harness_source(),
        "harness/plan.json": json.dumps(harness_plan),
        "harness/cases.json": json.dumps(cases),
    }
    if engine is not None:
        # Against the legacy's engine every case resets the engine and the call log travels with the output: more
        # time and more output than a local run (phase F: the sandbox killed a 17-case run at 600 s).
        build = await compile_and_test(sandbox, files, extra_inputs=extra, after=engine_script(engine),
                                       limits=replace(LIMITS, network=engine.network, timeout_seconds=1800,
                                                      max_output_bytes=16 * 1024 * 1024))  # fmt: skip
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
        for key in ("sequential", "concurrent"):  # the two dumps are diagnostic: kept out of the delivery's expected
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
            # A trace has no legacy return code (a CICS program just shows its message): it can only say that the
            # program rejected (-1, ADR-0015). The target's rejection is compared as that, its message as usual.
            actual = actual.model_copy(update={"returns": -1})
        runs.append(CaseRun(recorded_case.case.name, expected, actual))
    return EquivalenceRun(build, runs, found, raw=raw)


# -- ADR-0056 (phase E): the golden master travels with the delivery, runnable by the customer ------------------------
GOLDEN_MASTER_DIR = "src/test/resources/golden-master"
GOLDEN_MASTER_IT = "src/test/java/nexti/equivalence/GoldenMasterIT.java"
DELIVERED_HARNESS = "src/test/java/nexti/equivalence/EquivalenceHarness.java"
LEGACY_PROPERTIES = "src/main/resources/application-legacy.properties"

_GOLDEN_MASTER_IT = """package nexti.equivalence;

import static org.junit.jupiter.api.Assertions.assertEquals;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Generated by the platform (ADR-0056). The golden master the verification proved this project against, runnable
 * here: every case of src/test/resources/golden-master/cases.json runs through the services of this project on
 * the engine named by NEXTI_LEGACY_JDBC_URL (NEXTI_LEGACY_USER, NEXTI_LEGACY_PASSWORD) and what it did is compared
 * with expected.json, what the platform observed when the verdict was signed.
 *
 * <p>ONLY AGAINST A TEST ENGINE: each case truncates the tables of the suite and replaces the programs the legacy
 * calls by substitutes that answer as the case says. Set NEXTI_LEGACY_TEST_ENGINE=yes to say so. Run with
 * {@code mvn -Dtest=GoldenMasterIT -DfailIfNoTests=false test}.
 */
class GoldenMasterIT {

    private static final ObjectMapper JSON = new ObjectMapper();

    @Test
    void theProjectStillReproducesTheGoldenMaster() throws Exception {
        String url = System.getenv("NEXTI_LEGACY_JDBC_URL");
        Assumptions.assumeTrue(url != null && !url.isBlank(),
                "NEXTI_LEGACY_JDBC_URL is not set: the golden master needs a test engine of the legacy");
        Assumptions.assumeTrue("yes".equals(System.getenv("NEXTI_LEGACY_TEST_ENGINE")),
                "set NEXTI_LEGACY_TEST_ENGINE=yes: every case resets the tables of the suite and replaces the "
                        + "called programs by substitutes on that engine");
        ObjectNode plan = (ObjectNode) read("plan.json");
        plan.put("jdbc_url", url);
        plan.put("user", System.getenv().getOrDefault("NEXTI_LEGACY_USER", plan.path("user").asText("")));
        plan.put("password", System.getenv().getOrDefault("NEXTI_LEGACY_PASSWORD", ""));
        JsonNode cases = read("cases.json");
        JsonNode expected = read("expected.json");
        SingleConnectionDataSource dataSource = new SingleConnectionDataSource(
                url, plan.get("user").asText(), plan.get("password").asText(), true);
        try {
            JdbcTemplate jdbc = new JdbcTemplate(dataSource);
            TransactionTemplate transaction = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
            List<String> differing = new ArrayList<>();
            int compared = 0;
            for (JsonNode testCase : cases) {
                String name = testCase.get("name").asText();
                JsonNode wanted = expected.get(name);
                if (wanted == null) {
                    continue;
                }
                compared++;
                JsonNode actual = comparable(EquivalenceHarness.run(plan, testCase, jdbc, transaction));
                if (!actual.equals(comparable(wanted))) {
                    differing.add(name + ": expected " + comparable(wanted) + " but was " + actual);
                }
            }
            assertEquals(List.of(), differing, "cases that no longer reproduce the proven behaviour");
            Assumptions.assumeTrue(compared > 0, "expected.json names no case of cases.json");
        } finally {
            dataSource.destroy();
        }
    }

    private static JsonNode comparable(JsonNode node) {
        ObjectNode copy = node.deepCopy();
        copy.remove("name");
        return copy;
    }

    private static JsonNode read(String file) throws java.io.IOException {
        try (InputStream in = GoldenMasterIT.class.getResourceAsStream("/golden-master/" + file)) {
            if (in == null) {
                throw new IllegalStateException("golden-master/" + file + " is not in the test resources");
            }
            return JSON.readTree(in);
        }
    }
}
"""

_LEGACY_PROPERTIES = """# Generated by the platform (ADR-0056): the datasource of the legacy's engine, for the
# `legacy` profile (`--spring.profiles.active=legacy`). The data and the programs this project calls stay where they are
# (same_database): point it at that engine. prepareSQL=0 sends every statement as the literal T-SQL the legacy ran
# (no prepared handles nor temporary procedures inside the unit of work); the charset is the engine's default
# (iso_1 on most Sybase ASE servers; set it to the server's if it differs).
spring.datasource.url=jdbc:jtds:sybase://HOST:5000/DATABASE;prepareSQL=0;charset=iso_1
spring.datasource.username=
spring.datasource.password=
spring.datasource.driver-class-name=net.sourceforge.jtds.jdbc.Driver
# The unit of work is the legacy's own T-SQL (begin/commit/rollback tran) on the request's connection, in the
# engine's unchained mode: the pool hands out connections with autocommit on.
spring.datasource.hikari.auto-commit=true
"""


def delivery_files(
    design: Design,
    use_case: UseCase,
    run: EquivalenceRun,
    master: GoldenMaster,
    defaults: dict[str, Scalar] | None = None,
    engine: EngineTarget | None = None,
    harness: str | None = None,
) -> dict[str, str]:
    """What the delivery adds so the customer can run the golden master on a test engine of the legacy (ADR-0056,
    phase E): the harness as a test, the cases and the plan without the platform's credentials, what the platform
    observed (`expected.json`) and, with `same_database`, the datasource of the legacy's engine. Nothing when the
    harness did not run."""
    if run.problem or not run.raw:
        return {}
    recorded = [r for r in master.results if r.observation.error is None]
    cases = [target_case(design, use_case, r.case, defaults, engine) for r in recorded]
    stripped = {**plan(design, use_case, engine), "jdbc_url": "", "user": "", "password": ""}
    expected = {name: {k: v for k, v in item.items() if k != "name"}
                for name, item in run.raw.items()}  # fmt: skip
    source = (harness if harness is not None else harness_source()).replace(
        "    private static ObjectNode run(", "    static ObjectNode run(", 1
    )
    files = {
        DELIVERED_HARNESS: source,
        GOLDEN_MASTER_IT: _GOLDEN_MASTER_IT,
        f"{GOLDEN_MASTER_DIR}/plan.json": json.dumps(stripped, indent=1),
        f"{GOLDEN_MASTER_DIR}/cases.json": json.dumps(cases, indent=1),
        f"{GOLDEN_MASTER_DIR}/expected.json": json.dumps(expected, indent=1, sort_keys=True),
    }
    if design.data_strategy == "same_database":
        files[LEGACY_PROPERTIES] = _LEGACY_PROPERTIES
    return files
