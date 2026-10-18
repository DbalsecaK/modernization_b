# ruff: noqa: E501 - the shell script of the run keeps its long lines
"""The local engine of a COBOL/CICS program, run (ADR-0056, point 7): the translated programs compiled by GnuCOBOL
inside the sandbox image, each case loaded into the indexed files, the task driven as CICS would drive it (EIB,
COMMAREA, the map it receives), and what it left read back as the observation. The engine is not the customer's:
the verdict says `gnucobol-3` and the certainty index counts it as another engine. What the engine cannot do yet
(an EXEC CICS command without substitute, EXEC SQL, a missing copybook) makes the phase wait with the list, never
a guess."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.resources import files as package_files

from nexti_adapter_bms import BmsAdapter
from nexti_adapter_bms.parser import BmsMap
from nexti_adapter_cobol import CobolAdapter
from nexti_adapter_cobol.local import (
    ENGINE,
    IMAGE,
    Field,
    Translation,
    byte_length,
    case_plan,
    driver_source,
    dumper_source,
    group_layout,
    loader_source,
    observe,
    symbolic_copybook,
    translate,
)
from nexti_adapter_cobol.parser import SYSTEM_COPYBOOKS, Copybook, DataItem, Program
from nexti_core.adapters import LegacyUnavailableError, SourceFile
from nexti_core.spec.characterization import (
    EnvironmentItem,
    GoldenMaster,
    Recorded,
    Suite,
    program_key,
    source_digest,
)
from nexti_sandbox import Limits, Sandbox

PROVIDED_COPYBOOKS = {"DFHAID", "DFHEIBLK", "DFHBMSCA", "DFHEIBLC"}
_EXEC_SQL = re.compile(r"\bEXEC\s+SQL\b", re.IGNORECASE)

RUN_SCRIPT = r"""
set -u
mkdir -p /work/bin /work/src /work/case /work/tmp
export TMPDIR=/work/tmp
cp -r /input/src/. /work/src/
cd /work/src
for P in SQLPROGRAMS; do
  if ! ocesql $P.cbl $P.pre.cbl > /work/ocesql.txt 2>&1; then echo "NXCOMPILE-FAILED"; cat /work/ocesql.txt; exit 3; fi
  mv $P.pre.cbl $P.cbl
done
if ! cobc -x -o /work/bin/NXMAIN -I /input/cpy -I /input/nx -I /opt/ocesql/copy LINKSQL NXMAIN.cbl PROGRAMS NXCICS.cbl > /work/cobc.txt 2>&1; then
  echo "NXCOMPILE-FAILED"; cat /work/cobc.txt; exit 3
fi
if [ -n "SQLPROGRAMS" ]; then
  if ! initdb -D /work/pg -U nexti --auth=trust -E UTF8 --no-locale > /work/pg-init.log 2>&1; then echo "NXCOMPILE-FAILED"; cat /work/pg-init.log; exit 5; fi
  if ! pg_ctl -D /work/pg -l /work/pg.log -o "-k /work -c listen_addresses=localhost -c port=5432 -F" -w start > /dev/null; then echo "NXCOMPILE-FAILED"; cat /work/pg.log; exit 5; fi
  psql -h localhost -U nexti -d postgres -q -c "CREATE DATABASE nexti" > /dev/null
  if ! psql -h localhost -U nexti -d nexti -q -v ON_ERROR_STOP=1 -f /input/sql/schema.sql > /work/schema.log 2>&1; then echo "NXCOMPILE-FAILED"; cat /work/schema.log; exit 6; fi
fi
for F in FILES; do
  cobc -x -o /work/bin/NXLD_$F NXLD_$F.cbl >> /work/cobc.txt 2>&1 || { echo "NXCOMPILE-FAILED"; cat /work/cobc.txt; exit 3; }
  cobc -x -o /work/bin/NXDP_$F NXDP_$F.cbl >> /work/cobc.txt 2>&1 || { echo "NXCOMPILE-FAILED"; cat /work/cobc.txt; exit 3; }
done
for DIR in /input/cases/*/; do
  N=$(basename "$DIR")
  rm -rf /work/case; mkdir -p /work/case; cp "$DIR"/* /work/case/; : > /work/case/out.txt
  for F in FILES; do /work/bin/NXLD_$F > /dev/null 2>> /work/case/out.txt || echo "NXERR|load $F failed" >> /work/case/out.txt; done
  if [ -f /work/case/case.sql ]; then psql -h localhost -U nexti -d nexti -q -v ON_ERROR_STOP=1 -f /work/case/case.sql > /dev/null 2>> /work/case/out.txt || echo "NXERR|the rows of the case could not be loaded" >> /work/case/out.txt; fi
  /work/bin/NXMAIN > /work/case/stdout.txt 2>&1 || echo "NXERR|the program ended with status $?: $(tail -c 300 /work/case/stdout.txt)" >> /work/case/out.txt
  for F in FILES; do /work/bin/NXDP_$F > /dev/null 2>> /work/case/out.txt || echo "NXERR|dump $F failed" >> /work/case/out.txt; done
  if [ -f /input/sql/dump.sql ]; then psql -h localhost -U nexti -d nexti -At -f /input/sql/dump.sql >> /work/case/out.txt 2>&1 || echo "NXERR|the tables could not be read" >> /work/case/out.txt; fi
  echo "NXCASE|$N"
  cat /work/case/out.txt
  for F in FILES; do echo "NXF|$F|$(base64 -w0 /work/case/$F.dump 2>/dev/null)"; done
done
if [ -n "SQLPROGRAMS" ]; then pg_ctl -D /work/pg -m fast stop > /dev/null 2>&1 || true; fi
echo "NXDONE"
"""


def expanded_data(program: Program, copybooks: dict[str, Copybook]) -> list[DataItem]:
    """The data items of a program with every COPY of its DATA DIVISION expanded where it stands, so a group
    (a COMMAREA) that copies its fields lays out as the compiler sees it."""
    items = sorted(program.data, key=lambda it: it.line)
    copies = sorted(((line, name) for name, line in program.copies), key=lambda c: c[0])
    out: list[DataItem] = []
    pending = list(copies)
    for item in items:
        while pending and pending[0][0] < item.line:
            _, name = pending.pop(0)
            found = copybooks.get(name.upper())
            if found is not None:
                out += expanded_copybook(found, copybooks)
        out.append(item)
    for _, name in pending:
        found = copybooks.get(name.upper())
        if found is not None:
            out += expanded_copybook(found, copybooks)
    return out


def expanded_copybook(copybook: Copybook, copybooks: dict[str, Copybook], depth: int = 0) -> list[DataItem]:
    if depth > 5:
        return list(copybook.data)
    items = sorted(copybook.data, key=lambda it: it.line)
    pending = sorted(((line, name) for name, line in copybook.copies), key=lambda c: c[0])
    out: list[DataItem] = []
    for item in items:
        while pending and pending[0][0] < item.line:
            _, name = pending.pop(0)
            inner = copybooks.get(name.upper())
            if inner is not None:
                out += expanded_copybook(inner, copybooks, depth + 1)
        out.append(item)
    for _, name in pending:
        inner = copybooks.get(name.upper())
        if inner is not None:
            out += expanded_copybook(inner, copybooks, depth + 1)
    return out


class GnuCobolRunner:
    """A legacy runner (8.2) for COBOL/CICS on GnuCOBOL inside the sandbox."""

    engine = ENGINE

    def __init__(self, sandboxes: Callable[[str], Sandbox], image: str = IMAGE) -> None:
        self._sandboxes = sandboxes
        self.image = image

    async def run(self, files: list[SourceFile], suite: Suite) -> GoldenMaster:
        prepared = self.prepare(files, suite)
        sandbox = self._sandboxes(self.image)
        result = await sandbox.run(["sh", "/input/run.sh"], prepared.inputs,
                                   Limits(timeout_seconds=600, memory_mb=512, work_exec=True, work_mb=256,
                                          max_output_bytes=16 * 1024 * 1024))  # fmt: skip
        if "NXCOMPILE-FAILED" in result.stdout:
            detail = result.stdout.split("NXCOMPILE-FAILED", 1)[1].strip()[:1500]
            raise LegacyUnavailableError(f"GnuCOBOL could not compile the translated programs: {detail}")
        if "NXDONE" not in result.stdout:
            tail = (result.stderr or result.stdout)[-800:]
            failure = LegacyUnavailableError(f"the local COBOL engine did not finish: {tail}")
            failure.transient = result.timed_out
            raise failure
        sections = _sections(result.stdout)
        results = []
        for case in suite.cases:
            output = sections.get(case.name)
            if output is None:
                raise LegacyUnavailableError(f"the local COBOL engine printed nothing for the case {case.name}")
            results.append(Recorded(case=case, observation=observe(output, suite.schema_, case, prepared.layouts,
                                                                   prepared.files)))  # fmt: skip
        return GoldenMaster(
            program=prepared.program, source_sha256=source_digest(files), engine=ENGINE, schema_=suite.schema_,
            results=results, unreachable=dict(suite.unreachable),
            environment=[EnvironmentItem(key="engine", value="GnuCOBOL 3 (ASCII, big-endian binary, local "
                                         "substitutes of CICS)", source="engine")],
        )  # fmt: skip

    def prepare(self, files: list[SourceFile], suite: Suite) -> "Prepared":
        """Everything the sandbox receives for the suite (sources translated, copybooks, runtime, the cases as
        bytes, the script), and the layouts the observations are decoded with. Raises LegacyUnavailableError with
        the list of what the engine cannot do yet."""
        adapter = CobolAdapter()
        programs, problems = adapter._programs(files)
        copybooks = adapter._copybooks(files)
        main = next((p for p in programs if program_key(p.name) == program_key(suite.program)), None)
        if main is None:
            known = ", ".join(p.name for p in programs) or "none"
            raise ValueError(f"the program {suite.program} is not in the source files (programs: {known})")
        mapsets = BmsAdapter().mapsets(files)
        maps: dict[str, BmsMap] = {m.name.upper(): m for _, ms in mapsets for m in ms.maps}
        generated_copybooks = {ms.name.upper(): symbolic_copybook(ms) for _, ms in mapsets}
        waiting: list[str] = []
        for program in programs:
            needed = {name.upper() for name, _ in program.copies}
            missing = sorted(needed - set(copybooks) - PROVIDED_COPYBOOKS - set(generated_copybooks)
                             - {c.upper() for c in SYSTEM_COPYBOOKS})  # fmt: skip
            if missing:
                waiting.append(f"{program.name}: copybook(s) not in the inputs: {', '.join(missing)}")
        local = {p.name.upper() for p in programs}
        translations: dict[str, Translation] = {}
        for program in programs:
            try:
                found = translate(program, _text_of(files, program), suite.schema_, local, main=program is main)
            except ValueError as exc:
                waiting.append(str(exc))
                continue
            if found.unsupported:
                waiting.append(f"{program.name}: {', '.join(sorted(set(found.unsupported)))}")
            translations[program.name.upper()] = found
        if waiting or problems:
            raise LegacyUnavailableError(
                "the local COBOL engine (GnuCOBOL) cannot run this legacy yet: " + "; ".join([*problems, *waiting])
            )
        # The COMMAREA each substituted program receives, laid out from the caller's item, for the case's answers.
        layouts: dict[str, list[Field]] = {}
        for program in programs:
            items = expanded_data(program, copybooks)
            text = _text_of(files, program)
            for match in re.finditer(r"EXEC\s+CICS\s+(LINK|XCTL)\s+(.*?)END-EXEC", text, re.IGNORECASE | re.DOTALL):
                body = " ".join(match.group(2).split())
                target = re.search(r"PROGRAM\s*\(\s*'?([A-Z0-9-]+)'?\s*\)", body, re.IGNORECASE)
                area = re.search(r"COMMAREA\s*\(\s*([A-Z0-9-]+)\s*\)", body, re.IGNORECASE)
                if target and area and target.group(1).upper() not in local:
                    layouts.setdefault(target.group(1).upper(), group_layout(items, area.group(1)))
        file_sizes = {name: size for t in translations.values() for name, size in t.files.items()}
        sql_programs = [name for name, t in translations.items() if t.sql]
        transid = _transid(files, main.name)
        inputs: dict[str, bytes] = {}
        for name, found in translations.items():
            inputs[f"src/{name}.cbl"] = found.text.encode("latin-1", "replace")
        inputs["src/NXMAIN.cbl"] = driver_source(main.name).encode("latin-1")
        for name, (length, key) in file_sizes.items():
            inputs[f"src/NXLD_{name}.cbl"] = loader_source(name, length, key).encode("latin-1")
            inputs[f"src/NXDP_{name}.cbl"] = dumper_source(name, length, key).encode("latin-1")
        for name, copybook in copybooks.items():
            inputs[f"cpy/{name.upper()}.cpy"] = _text_of(files, copybook).encode("latin-1", "replace")
        for name, text in generated_copybooks.items():
            inputs.setdefault(f"cpy/{name}.cpy", text.encode("latin-1"))
        runtime = package_files("nexti_adapter_cobol") / "runtime"
        inputs["src/NXCICS.cbl"] = (runtime / "NXCICS.cbl").read_bytes()
        inputs["nx/DFHEIBLK.cpy"] = (runtime / "DFHEIBLK.cpy").read_bytes()
        inputs["nx/DFHAID.cpy"] = (runtime / "DFHAID.cpy").read_bytes()
        inputs["nx/nxhelper.py"] = (runtime / "nxhelper.py").read_bytes()
        received = {m for t in translations.values() for m in t.maps if m in maps}
        commarea_length = _commarea_length(main, copybooks)
        for case in suite.cases:
            plan = case_plan(case, suite.schema_, {m: maps[m] for m in received}, transid, layouts,
                             commarea_length=commarea_length)  # fmt: skip
            folder = f"cases/{case.name}"
            for file_name, data in plan.files.items():
                inputs[f"{folder}/{file_name}"] = data
            inputs[f"{folder}/eib.bin"] = plan.eib
            inputs[f"{folder}/commarea.bin"] = plan.commarea
            inputs[f"{folder}/case.json"] = plan.case_json.encode("utf-8")
        if sql_programs:
            from nexti_adapter_cobol.sql import case_sql, dump_sql, schema_sql

            inputs["sql/schema.sql"] = schema_sql(suite.schema_, list(file_sizes)).encode("utf-8")
            inputs["sql/dump.sql"] = dump_sql(suite.schema_, list(file_sizes)).encode("utf-8")
            for case in suite.cases:
                inputs[f"cases/{case.name}/case.sql"] = case_sql(suite.schema_, case.setup, list(file_sizes)).encode(
                    "utf-8"
                )
        script = (RUN_SCRIPT.replace("SQLPROGRAMS", " ".join(sql_programs))
                  .replace("LINKSQL", "-L/opt/ocesql/lib -locesql" if sql_programs else "")
                  .replace("PROGRAMS", " ".join(f"{name}.cbl" for name in translations))
                  .replace("FILES", " ".join(file_sizes) or "''"))  # fmt: skip
        inputs["run.sh"] = script.encode("utf-8")
        return Prepared(main.name, inputs, layouts, list(file_sizes))


@dataclass(frozen=True)
class Prepared:
    program: str
    inputs: dict[str, bytes]
    layouts: dict[str, list[Field]]
    files: list[str] = field(default_factory=list)  # the tables reached as files; the rest are SQL tables


def _commarea_length(program: Program, copybooks: dict[str, Copybook]) -> int:
    """The bytes of the program's DFHCOMMAREA (LINKAGE), the length a continuation of its task comes with."""
    items = expanded_data(program, copybooks)
    layout = group_layout(items, "DFHCOMMAREA")
    if layout:
        return max(f.offset + f.length for f in layout)
    own = next((it for it in items if it.name.upper() == "DFHCOMMAREA" and it.picture), None)
    return byte_length(own.picture, own.usage) if own else 0


def _text_of(files: list[SourceFile], owner: Program | Copybook) -> str:
    return next((f.text for f in files if f.path == owner.file), "")


def _transid(files: list[SourceFile], program: str) -> str:
    for definition in CobolAdapter()._transactions(files):
        if definition.program.upper() == program.upper():
            return definition.transid
    return "NXTX"


def _sections(stdout: str) -> dict[str, str]:
    found: dict[str, list[str]] = {}
    current: str | None = None
    for line in stdout.splitlines():
        if line.startswith("NXCASE|"):
            current = line[7:].strip()
            found[current] = []
        elif current is not None and line.strip() != "NXDONE":
            found[current].append(line)
    return {name: "\n".join(lines) for name, lines in found.items()}
