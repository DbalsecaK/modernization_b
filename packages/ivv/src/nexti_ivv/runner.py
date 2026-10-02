"""The black-box run of the golden master on the third party's target (ADR-0025). In the Java sandbox, without network:
PostgreSQL with the target's own schema, the target's service (its runnable jar, or its sources compiled against the
sandbox's libraries), stubs for the external services the legacy called, and the harness, which plays every case.
What the target did is translated back to the legacy's terms and compared with what the legacy did, with the masks the
approved mapping declares."""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from importlib.resources import files as package_files
from typing import Any

from nexti_core.spec.characterization import Call, Case, GoldenMaster, Observation
from nexti_ivv.mapping import Mapping, ProgramMap
from nexti_ivv.target import TargetInventory
from nexti_sandbox import Limits, Sandbox
from nexti_verification.compare import Difference, differences

IMAGE = "nexti-sandbox-java:2"
LIMITS = Limits(cpus=2.0, memory_mb=2048, pids=512, timeout_seconds=900, work_mb=768,
                max_output_bytes=4 * 1024 * 1024)  # fmt: skip
STUB_PORT = 18099
APP_PORT = 8080


@dataclass(frozen=True)
class IvvCase:
    name: str
    rules: tuple[str, ...]
    expected: Observation
    actual: Observation | None
    differences: tuple[Difference, ...] = ()
    error: str | None = None

    @property
    def matched(self) -> bool:
        return self.actual is not None and not self.differences and self.error is None


@dataclass(frozen=True)
class IvvRun:
    ready: bool
    diagnostic: str
    cases: tuple[IvvCase, ...] = field(default=())

    @property
    def matched(self) -> int:
        return sum(1 for c in self.cases if c.matched)


def _slug(program: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", program.lower()).strip("-")


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


def _ident(name: str) -> str:
    """A table or column name of the approved mapping; anything else is refused before it reaches SQL."""
    if not _IDENTIFIER.match(name):
        raise ValueError(f"not a SQL identifier: {name!r}")
    return name


def _sql(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float | Decimal):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _plan_case(case: Case, program: ProgramMap) -> dict[str, Any]:
    setup = []
    for legacy_table, rows in case.setup.items():
        table = program.tables.get(legacy_table)
        if table is None:
            continue
        for row in rows:
            columns = [(_ident(table.columns[c]), v) for c, v in row.items() if c in table.columns]
            if columns:
                names, values = ", ".join(c for c, _ in columns), ", ".join(_sql(v) for _, v in columns)
                setup.append(f"INSERT INTO {_ident(table.table)} ({names}) VALUES ({values})")  # noqa: S608 - checked identifiers, quoted literals
    body = {name: case.inputs[parameter] for name, parameter in program.request.items() if parameter in case.inputs}
    answers: dict[str, list[dict[str, Any]]] = {}
    for legacy_program, call in program.calls.items():
        replies = []
        for stub in case.stubs.get(legacy_program, []):
            reply: dict[str, Any] = {}
            if call.answer.returns:
                reply[call.answer.returns] = stub.returns
            for output, name in call.answer.outputs.items():
                if output in stub.outputs:
                    reply[name] = stub.outputs[output]
            replies.append(reply)
        answers[f"/{_slug(legacy_program)}"] = replies
    return {"name": case.name, "setup": setup, "body": body, "answers": answers}


def plan(master: GoldenMaster, program: ProgramMap, cases: list[Case]) -> dict[str, Any]:
    tables = list(program.tables.values())
    return {
        "jdbc": "jdbc:postgresql://localhost:5432/nexti",
        "user": "nexti",
        "base": f"http://127.0.0.1:{APP_PORT}",
        "endpoint": {"method": program.endpoint.method.upper(), "path": program.endpoint.path},
        "stubPort": STUB_PORT,
        "startSeconds": 240,
        "reset": [f"DELETE FROM {_ident(t.table)}" for t in reversed(tables)],  # noqa: S608 - checked identifier
        "dump": {t.table: f"SELECT * FROM {_ident(t.table)}" for t in tables},  # noqa: S608 - checked identifier
        "cases": [_plan_case(c, program) for c in cases],
    }


def _script(inventory: TargetInventory, program: ProgramMap) -> str:
    properties = [
        f"--server.port={APP_PORT}",
        "--spring.datasource.url=jdbc:postgresql://localhost:5432/nexti",
        "--spring.datasource.username=nexti",
        "--spring.datasource.password=",
        "--spring.sql.init.mode=never",
        "--logging.level.root=WARN",
        "--spring.main.banner-mode=off",
    ]
    properties += [f"--{call.property}=http://127.0.0.1:{STUB_PORT}/{_slug(name)}"
                   for name, call in program.calls.items()]  # fmt: skip
    args = " ".join(f"'{p}'" for p in properties)
    if inventory.artifact:
        prepare = ""
        start = f"java -Xmx768m -jar '/input/target/{inventory.artifact}' {args}"
    else:
        # The target's sources, compiled against the sandbox's libraries (a target without a runnable jar).
        prepare = (
            "mkdir -p /work/target-out\n"
            "find /input/target -path '*/src/main/java/*' -name '*.java' > /work/target.txt\n"
            "javac -nowarn -encoding UTF-8 -d /work/target-out -cp '/opt/lib/*' @/work/target.txt "
            "> /work/target-javac.txt 2>&1 "
            "|| { echo '===TARGET-BUILD-FAILED==='; cat /work/target-javac.txt; exit 3; }\n"
            "for r in $(find /input/target -type d -path '*/src/main/resources'); do "
            'cp -r "$r"/. /work/target-out/; done\n'
        )
        start = f"java -Xmx768m -cp '/work/target-out:/opt/lib/*' {inventory.main_class} {args}"
    return (
        "initdb -D /work/pg -U nexti --auth=trust -E UTF8 --no-locale > /work/pg-init.log 2>&1 "
        "|| { echo '===DB-FAILED==='; cat /work/pg-init.log; exit 5; }\n"
        'pg_ctl -D /work/pg -l /work/pg.log -o "-k /work -c listen_addresses=localhost -c port=5432 -F" -w start '
        "> /dev/null || { echo '===DB-FAILED==='; cat /work/pg.log; exit 5; }\n"
        'psql -h localhost -U nexti -d postgres -q -c "CREATE DATABASE nexti" > /dev/null\n'
        "psql -h localhost -U nexti -d nexti -q -v ON_ERROR_STOP=1 -f /input/target-schema.sql > /work/schema.log 2>&1 "
        "|| { echo '===TARGET-SCHEMA-FAILED==='; cat /work/schema.log; exit 4; }\n"
        f"{prepare}"
        f"({start} > /work/app.log 2>&1 &)\n"
        'echo "===IVV==="\n'
        "java -cp '/opt/lib/*' /input/harness/IvvHarness.java /input/harness/plan.json 2> /work/harness.log || true\n"
        'echo "===IVV-END==="\n'
        'echo "===APP-LOG==="; tail -c 3000 /work/app.log; tail -c 1000 /work/harness.log\n'
        "pkill -f 'spring.datasource.url' > /dev/null 2>&1 || true\n"
        "pg_ctl -D /work/pg -m fast stop > /dev/null 2>&1 || true\n"
    )


def _like(expected: str | None, actual: Any) -> str | None:
    """The target's value written as the legacy's canonical value of the same field (scale, dates, blanks)."""
    if actual is None:
        return None
    text = actual if isinstance(actual, str) else json.dumps(actual) if isinstance(actual, dict | list) else str(actual)
    if isinstance(actual, bool):
        text = "true" if actual else "false"
    if expected is None:
        return text.rstrip(" ")
    try:
        if re.fullmatch(r"-?\d+\.\d+", expected):
            scale = len(expected.split(".")[1])
            return str(Decimal(text).quantize(Decimal(1).scaleb(-scale)))
        if re.fullmatch(r"-?\d+", expected) and re.fullmatch(r"-?\d+(\.0+)?", text):
            return str(int(Decimal(text)))
        if re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?", expected):
            moment = datetime.fromisoformat(text.strip().replace(" ", "T"))
            return moment.isoformat(timespec="milliseconds" if "." in expected else "seconds")
        if expected in ("true", "false"):
            return "true" if text.strip().lower() in ("true", "t", "1", "s", "y") else "false"
    except (InvalidOperation, ValueError):
        return text
    return text.rstrip(" ")


def _masked(program: ProgramMap, path: str, rejected: bool) -> bool:
    return any((m.path == path or path.startswith(m.path + ":")) and (m.when == "always" or rejected)
               for m in program.masks)  # fmt: skip


def _views(program: ProgramMap, expected: Observation, raw: dict[str, Any]) -> tuple[Observation, Observation]:
    rejected = (expected.returns or 0) != 0
    found_body = raw.get("body")
    body: dict[str, Any] = found_body if isinstance(found_body, dict) else {}
    keep_returns = program.response.returns is not None and not _masked(program, "returns", rejected)
    exp_outputs = {k: v for k, v in expected.outputs.items()
                   if k in program.response.outputs and not _masked(program, f"outputs:{k}", rejected)}  # fmt: skip
    act_outputs = {k: _like(exp_outputs.get(k), body.get(program.response.outputs[k])) for k in exp_outputs}
    exp_tables: dict[str, list[dict[str, str | None]]] = {}
    act_tables: dict[str, list[dict[str, str | None]]] = {}
    for legacy_table, table in program.tables.items():
        if _masked(program, f"tables:{legacy_table}", rejected):
            continue
        rows = expected.tables.get(legacy_table, [])
        columns = [c for c in table.columns if not _masked(program, f"tables:{legacy_table}.{c}", rejected)]
        samples = {c: next((r.get(c) for r in rows if r.get(c) is not None), None) for c in columns}
        exp_tables[legacy_table] = sorted(({c: r.get(c) for c in columns} for r in rows), key=json.dumps)
        got = raw.get("tables", {}).get(table.table, [])
        act_tables[legacy_table] = sorted(
            ({c: _like(samples[c], g.get(table.columns[c].lower(), g.get(table.columns[c]))) for c in columns}
             for g in got), key=json.dumps)  # fmt: skip
    by_path = {f"/{_slug(name)}": (name, call) for name, call in program.calls.items()}
    exp_calls = [c for c in expected.calls if not _masked(program, f"calls:{c.program}", rejected)]
    samples_by_program: dict[str, dict[str, str | None]] = {}
    for c in exp_calls:
        for argument, value in c.arguments.items():
            samples_by_program.setdefault(c.program, {}).setdefault(argument, value)
    act_calls = []
    for made in raw.get("calls", []):
        found = by_path.get(made.get("path", ""))
        if found is None:
            continue
        name, call = found
        if _masked(program, f"calls:{name}", rejected):
            continue
        sent = made.get("body") if isinstance(made.get("body"), dict) else {}
        arguments = {a: _like(samples_by_program.get(name, {}).get(a), sent.get(f)) for a, f in call.arguments.items()}
        act_calls.append(Call(program=name, arguments=arguments))
    exp_calls = [Call(program=c.program, arguments={a: v for a, v in c.arguments.items()
                                                     if a in program.calls.get(c.program, _NO_CALL).arguments})
                 for c in exp_calls if c.program in program.calls]  # fmt: skip
    returns = None
    if keep_returns and program.response.returns in body:
        try:
            returns = int(body[program.response.returns])
        except (TypeError, ValueError):
            returns = None
    exp = Observation(returns=expected.returns if keep_returns else None, outputs=exp_outputs, tables=exp_tables,
                      calls=exp_calls)  # fmt: skip
    act = Observation(returns=returns if keep_returns else None, outputs=act_outputs, tables=act_tables,
                      calls=act_calls)  # fmt: skip
    return exp, act


class _NoCall:
    arguments: dict[str, str] = {}  # noqa: RUF012 - a sentinel


_NO_CALL = _NoCall()


async def run(sandbox: Sandbox, archive: dict[str, bytes], inventory: TargetInventory, mapping: Mapping,
              master: GoldenMaster, cases: list[Case] | None = None,
              expected: dict[str, Observation] | None = None) -> IvvRun:  # fmt: skip
    """Plays `cases` (the golden master's by default) on the target and compares with `expected` (the legacy's)."""
    program = mapping.program(master.program)
    if program is None:
        return IvvRun(False, f"The mapping has no entry for {master.program}")
    cases = cases if cases is not None else [r.case for r in master.results]
    expected = expected if expected is not None else {r.case.name: r.observation for r in master.results}
    if inventory.schema is None:
        return IvvRun(False, "The target has no schema.sql: its tables cannot be created")
    if not inventory.artifact and not inventory.main_class:
        return IvvRun(False, "The target has neither a runnable jar nor a main class")
    harness = (package_files("nexti_ivv") / "harness" / "IvvHarness.java").read_bytes()
    inputs = {f"target/{path}": data for path, data in archive.items()}
    inputs["target-schema.sql"] = inventory.schema.encode("utf-8")
    inputs["harness/IvvHarness.java"] = harness
    inputs["harness/plan.json"] = json.dumps(plan(master, program, cases)).encode("utf-8")
    result = await sandbox.run(["sh", "-c", _script(inventory, program)], inputs, LIMITS)
    out = result.stdout
    for marker in ("===TARGET-BUILD-FAILED===", "===TARGET-SCHEMA-FAILED===", "===DB-FAILED==="):
        if marker in out:
            return IvvRun(False, f"{marker.strip('=').lower().replace('-', ' ')}: {out.split(marker, 1)[1][:1500]}")
    if "NXI-NOT-READY" in out or "NXI-READY" not in out:
        log = out.split("===APP-LOG===", 1)[-1] if "===APP-LOG===" in out else (result.stderr or out)
        return IvvRun(False, f"The target did not start: {log[-1500:]}")
    raws = {}
    for line in out.splitlines():
        if line.startswith("NXI {"):
            data = json.loads(line[4:])
            raws[data["case"]] = data
    found = []
    for case in cases:
        raw = raws.get(case.name)
        legacy = expected[case.name]
        if raw is None or raw.get("error"):
            found.append(IvvCase(case.name, tuple(case.rules), legacy, None,
                                 error=(raw or {}).get("error", "the case did not run")))  # fmt: skip
            continue
        exp, act = _views(program, legacy, raw)
        found.append(IvvCase(case.name, tuple(case.rules), exp, act, tuple(differences(exp, act))))
    return IvvRun(True, f"{sum(1 for c in found if c.matched)} of {len(found)} case(s) reproduced", tuple(found))
