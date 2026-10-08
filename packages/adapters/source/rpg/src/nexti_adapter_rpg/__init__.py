"""The RPG / IBM i source adapter (spec 8.2, ADR-0051): RPG III/400, RPG IV fixed, mixed and fully free programs and
service-program modules, the DDS of their files (PF, LF, DSPF, PRTF) and the CL that starts them. It builds the code
and data layers of the knowledge graph (programs, subroutines, procedures, files as tables, display and printer
files, calls, embedded SQL), gives the neutral types, the classification of the statements, the slices the
extractor reads and the data a range of lines reads and writes. It never uses a model and never executes anything."""

import json
import re
from pathlib import PurePosixPath
from typing import Any

from nexti_adapter_cobol.traces import load_traces
from nexti_adapter_rpg import cl, dds, quirks
from nexti_adapter_rpg.parser import (
    CONTROL,
    INFRASTRUCTURE,
    READS,
    WRITES,
    FieldDecl,
    FileDecl,
    Routine,
    RpgError,
    RpgProgram,
    Statement,
    detect,
    parse,
    sql_tables,
)
from nexti_adapter_rpg.types import TypeMapping, to_neutral
from nexti_core.adapters import Edge, EdgeType, Inventory, Node, SliceView, SourceFile
from nexti_core.spec.characterization import CoveredBranch, EngineQuirk, EnvironmentItem

_ASSIGN = re.compile(r"^\s*([A-Za-z_#$@*][\w#$@]*(?:\([^)]*\))?(?:\.[\w#$@]+)?)\s*(?:[-+*/]?=)\s*(.*)$", re.S)
_ARITHMETIC = {"ADD", "SUB", "MULT", "DIV", "Z-ADD", "Z-SUB", "MOVE", "MOVEL", "MOVEA", "XFOOT", "SQRT", "MVR",
               "CAT", "SUBST", "SCAN", "CHECK", "CHECKR", "XLATE", "TIME", "COMP", "LOOKUP"}  # fmt: skip
_JUMPS = {"EXSR", "BEGSR", "ENDSR", "LEAVESR", "GOTO", "TAG"}


def _stem(path: str) -> str:
    return PurePosixPath(path).stem.upper()


def kind_of(statement: Statement) -> str:
    """business, control_flow or infrastructure."""
    base = statement.base
    if base in CONTROL or base in ("AND", "OR", "CAB", "CAS"):
        return "control_flow"
    if base in INFRASTRUCTURE:
        return "infrastructure"
    if base == "EVAL" and re.match(r"^\s*\*IN(LR|RT|H\d|\d\d)\s*=", statement.factor2, re.I):
        return "infrastructure"  # the cycle's indicators
    return "business"


class RpgAdapter:
    name = "rpg-ibmi"

    # -- the workspace ------------------------------------------------------------------------------------------
    def _programs(self, files: list[SourceFile]) -> tuple[list[RpgProgram], list[str]]:
        programs, problems = [], []
        for f in files:
            if detect(f.path, f.text) and not dds.is_dds(f.path, f.text) and not cl.is_cl(f.path, f.text):
                try:
                    programs.append(parse(f.path, f.text))
                except RpgError as exc:
                    problems.append(f"{f.path}:{exc.line}: {exc}")
        return programs, problems

    def _dds(self, files: list[SourceFile]) -> list[dds.DdsFile]:
        return [dds.parse(f.path, f.text) for f in files if dds.is_dds(f.path, f.text) and not detect(f.path, "")]

    def _cl(self, files: list[SourceFile]) -> list[cl.ClProgram]:
        return [cl.parse(f.path, f.text) for f in files if cl.is_cl(f.path, f.text)]

    def detect(self, files: list[SourceFile]) -> float:
        programs = [f for f in files if detect(f.path, f.text)]
        if not programs:
            return 0.0
        dds_files = sum(1 for f in files if dds.is_dds(f.path, f.text))
        return round(min(1.0, 0.7 + 0.05 * dds_files), 2)

    # -- inventory ----------------------------------------------------------------------------------------------
    def inventory(self, files: list[SourceFile]) -> Inventory:
        programs, problems = self._programs(files)
        described = self._dds(files)
        cls = self._cl(files)
        inv = Inventory(self.name, problems=problems)
        formats = {r.name: d.name for d in described for r in d.records}
        by_name = {d.name: d for d in described}
        known = {p.name for p in programs} | {c.name for c in cls}
        external: set[str] = set()
        tables_used: set[str] = set()
        devices = _devices(described)
        for d in described:
            self._dds_nodes(inv, d, by_name)
        statements = decisions = 0
        for program in programs:
            key = f"program:{program.name}"
            stmts = program.statements()
            statements += len(stmts)
            branch = sum(1 for s in stmts if s.base in ("IF", "ELSEIF", "WHEN", "DOW", "DOU", "FOR", "CAB", "CAS"))
            decisions += branch
            inv.nodes.append(Node(key, "Program", program.name, program.file, program.line_start, program.line_end, {
                "language": "RPG", "variant": program.variant, "statements": len(stmts), "complexity": 1 + branch,
                "kind": "service-program-module" if program.nomain else "program",
                "parameters": ",".join(program.parameters), "lines": program.line_end - program.line_start + 1,
            }))  # fmt: skip
            inv.problems.extend(program.problems)
            for item in program.fields:
                self._field(inv, key, program.name, item)
            for member, line in program.copies:
                inv.edges.append(Edge(key, "COPIES", f"copybook:{member}", {"line": line}))
                if not any(_stem(f.path) == member for f in files):
                    inv.problems.append(f"{program.file}:{line}: /COPY member {member} is not in the inputs")
            for decl in program.files:
                self._file_edges(inv, key, decl, by_name, tables_used)
            local = {r.name for r in program.routines if r.kind == "procedure"}
            for routine in program.routines:
                if routine.kind == "mainline":
                    continue
                label = "Paragraph" if routine.kind == "subroutine" else "Method"
                rkey = f"{'para' if routine.kind == 'subroutine' else 'proc'}:{program.name}.{routine.name}"
                inv.nodes.append(Node(rkey, label, routine.name, program.file, routine.line_start, routine.line_end, {  # type: ignore[arg-type]
                    "program": program.name, "kind": routine.kind, "statements": len(routine.statements),
                    "exported": routine.exported,
                }))  # fmt: skip
                inv.edges.append(Edge(key, "CONTAINS", rkey))
            for routine in program.routines:
                source = key if routine.kind == "mainline" else \
                    f"{'para' if routine.kind == 'subroutine' else 'proc'}:{program.name}.{routine.name}"  # fmt: skip
                for s in routine.statements:
                    self._statement_edges(inv, program, key, source, s, local, formats, devices, known, external,
                                          tables_used)  # fmt: skip
        for job in cls:
            key = f"program:{job.name}"
            inv.nodes.append(
                Node(
                    key,
                    "Program",
                    job.name,
                    job.file,
                    1,
                    job.line_end,
                    {"language": "CL", "commands": len(job.commands), "parameters": ",".join(job.parameters)},
                )
            )
            inv.problems.extend(job.problems)
            for callee, line, how in job.calls():
                inv.edges.append(Edge(key, "CALLS", f"program:{callee}", {"kind": how, "line": line}))
                if callee not in known:
                    external.add(callee)
            for file_name, target, line in job.overrides():
                inv.edges.append(Edge(key, "DEPENDS_ON", f"table:{target or file_name}", {"override": file_name,
                                                                                         "line": line}))  # fmt: skip
        for callee in sorted(external):
            inv.nodes.append(Node(f"program:{callee}", "Program", callee, properties={"external": True}))
        defined = {n.key for n in inv.nodes}
        for table in sorted(tables_used):
            if f"table:{table}" not in defined:
                inv.nodes.append(Node(f"table:{table}", "Table", table, properties={"described": False}))
                inv.problems.append(f"file {table} has no DDS in the inputs: its fields are unknown")
        inv.edges = _unique(inv.edges)
        inv.metrics = {
            "programs": len(programs), "cl_programs": len(cls), "statements": statements, "decisions": decisions,
            "subroutines": sum(1 for p in programs for r in p.routines if r.kind == "subroutine"),
            "procedures": sum(1 for p in programs for r in p.routines if r.kind == "procedure"),
            "physical_files": sum(1 for d in described if d.kind == "PF"),
            "logical_files": sum(1 for d in described if d.kind == "LF"),
            "display_files": sum(1 for d in described if d.kind == "DSPF"),
            "printer_files": sum(1 for d in described if d.kind == "PRTF"),
            "external_calls": len(external), "lines": sum(p.line_end for p in programs),
        }  # fmt: skip
        return inv

    def _dds_nodes(self, inv: Inventory, d: dds.DdsFile, by_name: dict[str, dds.DdsFile]) -> None:
        inv.problems.extend(d.problems)
        if d.kind in ("PF", "LF"):
            key = f"table:{d.name}"
            inv.nodes.append(Node(key, "Table", d.name, d.file, 1, d.line_end, {
                "kind": d.kind, "keys": ",".join(k for r in d.records for k in r.keys),
                "unique": "UNIQUE" in d.keywords.upper()}))  # fmt: skip
            for based in d.based_on:
                inv.edges.append(Edge(key, "DERIVED_FROM", f"table:{based}"))
            for item in d.fields:
                mapping = column_type(d, item, by_name)
                ckey = f"column:{d.name}.{item.name}"
                inv.nodes.append(Node(ckey, "Column", item.name, d.file, item.line, item.line, {
                    "source_type": mapping.source, "neutral_type": str(mapping.neutral) if mapping.neutral else "",
                    "note": mapping.note}))  # fmt: skip
                inv.edges.append(Edge(key, "DECLARES", ckey))
            return
        key = f"file:{d.name}"
        inv.nodes.append(Node(key, "File", d.name, d.file, 1, d.line_end, {
            "kind": d.kind, "records": ",".join(r.name for r in d.records)}))  # fmt: skip
        for record in d.records:
            rkey = f"map:{d.name}.{record.name}"
            props: dict[str, str | int | float | bool | None] = {
                "fields": len(record.fields), "keys": ",".join(dds.function_keys(record)),
                "device": "display" if d.kind == "DSPF" else "printer"}  # fmt: skip
            inv.nodes.append(Node(rkey, "BmsMap" if d.kind == "DSPF" else "File", record.name, d.file, record.line,
                                  record.line, props))  # fmt: skip
            inv.edges.append(Edge(key, "CONTAINS", rkey))

    def _field(self, inv: Inventory, owner: str, prefix: str, item: FieldDecl) -> None:
        if item.kind in ("DS", "LIKE"):
            return
        mapping = to_neutral(item.kind, item.length, item.decimals)
        key = f"field:{prefix}.{item.name}"
        inv.nodes.append(Node(key, "Field", item.name, None, item.line, item.line, {
            "role": item.role, "source_type": mapping.source,
            "neutral_type": str(mapping.neutral) if mapping.neutral else "", "note": mapping.note}))  # fmt: skip
        inv.edges.append(Edge(owner, "DECLARES", key))

    def _file_edges(self, inv: Inventory, key: str, decl: FileDecl, by_name: dict[str, dds.DdsFile],
                    tables: set[str]) -> None:  # fmt: skip
        props: dict[str, str | int | float | bool | None] = {"line": decl.line, "usage": decl.usage}
        described = by_name.get(decl.name)
        if decl.device == "WORKSTN" or (described is not None and described.kind == "DSPF"):
            inv.edges.append(Edge(key, "USES_MAP", f"file:{decl.name}", props))
        elif decl.device == "PRINTER" or (described is not None and described.kind == "PRTF"):
            inv.edges.append(Edge(key, "WRITES", f"file:{decl.name}", props))
        else:
            tables.add(decl.name)
            if decl.usage in ("I", "U"):
                inv.edges.append(Edge(key, "READS", f"table:{decl.name}", props))
            if decl.usage in ("O", "U"):
                inv.edges.append(Edge(key, "WRITES", f"table:{decl.name}", props))

    def _statement_edges(
        self, inv: Inventory, program: RpgProgram, key: str, source: str, s: Statement, local: set[str],
        formats: dict[str, str], devices: dict[str, str], known: set[str], external: set[str], tables: set[str],
    ) -> None:  # fmt: skip
        line: dict[str, str | int | float | bool | None] = {"line": s.line_start, "opcode": s.opcode}
        if s.base == "EXSR":
            target = (s.factor2 or s.factor2).split()[0].upper() if s.factor2.split() else ""
            if target:
                inv.edges.append(Edge(source, "PERFORMS", f"para:{program.name}.{target}", line))
        elif s.base in ("CALL", "CALLB", "CALLP"):
            callee = _callee(s)
            if not callee:
                return
            if callee in local:
                inv.edges.append(Edge(source, "PERFORMS", f"proc:{program.name}.{callee}", line))
            else:
                inv.edges.append(Edge(key, "CALLS", f"program:{callee}", {**line, "kind": s.base}))
                if callee not in known:
                    external.add(callee)
        elif s.base == "EXEC SQL":
            reads, writes = sql_tables(s)
            for table in sorted(reads | writes):
                tables.add(table)
                inv.edges.append(Edge(key, "EXEC_SQL", f"table:{table}", line))
            for table in sorted(reads):
                inv.edges.append(Edge(key, "READS", f"table:{table}", line))
            for table in sorted(writes):
                inv.edges.append(Edge(key, "WRITES", f"table:{table}", line))
        elif s.base in READS | WRITES:
            target = _file_operand(s)
            if target:
                name = formats.get(target, target)
                if devices.get(name) == "PRTF":
                    inv.edges.append(Edge(key, "WRITES", f"file:{name}", line))  # a report line, not a table row
                elif devices.get(name) == "DSPF":
                    inv.edges.append(Edge(key, "USES_MAP", f"file:{name}", line))
                else:
                    kind: EdgeType = "READS" if s.base in READS else "WRITES"
                    inv.edges.append(Edge(key, kind, f"table:{name}", line))

    # -- types, classification, slices, data --------------------------------------------------------------------
    def types(self, files: list[SourceFile]) -> dict[str, str]:
        found: dict[str, str] = {}
        programs, _ = self._programs(files)
        for item in (i for p in programs for i in p.fields):
            if item.kind in ("DS", "LIKE"):
                continue
            mapping = to_neutral(item.kind, item.length, item.decimals)
            if mapping.neutral is not None:
                found.setdefault(item.name, str(mapping.neutral))
        described = self._dds(files)
        by_name = {d.name: d for d in described}
        for d in described:
            for f in d.fields:
                mapping = column_type(d, f, by_name)
                if mapping.neutral is not None:
                    found.setdefault(f.name, str(mapping.neutral))
        return found

    def classification(self, files: list[SourceFile]) -> dict[str, int]:
        counts = {"infrastructure": 0, "control_flow": 0, "business": 0}
        programs, _ = self._programs(files)
        for statement in (s for p in programs for s in p.statements()):
            counts[kind_of(statement)] += 1
        return counts

    def classified(self, files: list[SourceFile]) -> list[dict[str, Any]]:
        programs, _ = self._programs(files)
        return [{"unit": p.name, "file": p.file, "line_start": s.line_start, "line_end": s.line_end,
                 "statement": s.opcode, "label": kind_of(s), "reason": f"{s.opcode} operation"}
                for p in programs for s in p.statements()]  # fmt: skip

    def slices(self, files: list[SourceFile]) -> list[SliceView]:
        """One slice per program: the routines with business operations, its entry parameters and the database
        files it reads or writes."""
        programs, _ = self._programs(files)
        described = self._dds(files)
        formats = {r.name: d.name for d in described for r in d.records}
        devices = _devices(described)
        views = []
        for program in programs:
            ranges = [(r.line_start, r.line_end) for r in program.routines
                      if any(kind_of(s) == "business" for s in r.statements)]  # fmt: skip
            if not ranges:
                continue
            tables = sorted({f.name for f in program.files if f.device not in ("WORKSTN", "PRINTER")} | {
                formats.get(t, t) for s in program.statements() if s.base in READS | WRITES
                and (t := _file_operand(s))} | {t for s in program.statements() if s.base == "EXEC SQL"
                for group in sql_tables(s) for t in group})  # fmt: skip
            tables = [t for t in tables if t not in devices]
            views.append(SliceView(program.name, program.file, tuple(ranges), tuple(program.parameters), tuple(tables)))
        return views

    def data_of(
        self, files: list[SourceFile], file: str, ranges: list[tuple[int, int]]
    ) -> tuple[frozenset[str], frozenset[str]]:
        programs, _ = self._programs(files)
        program = next((p for p in programs if p.file == file or _stem(p.file) == _stem(file)), None)
        if program is None:
            return frozenset(), frozenset()
        formats = {r.name: d.name for d in self._dds(files) for r in d.records}
        reads, writes = flow(program, ranges, formats)
        return frozenset(reads), frozenset(writes)

    def engine_quirks(self, files: list[SourceFile]) -> list[EngineQuirk]:
        """The RPG behaviours every program relies on (R4: cycle, truncation and (H), MOVE, EBCDIC order...)."""
        programs, _ = self._programs(files)
        formats = device_formats(self._dds(files))
        return [q for p in programs for q in quirks.detect(p, formats)]

    def program_quirks(self, files: list[SourceFile], program: str) -> tuple[list[EngineQuirk], list[EnvironmentItem]]:
        """The quirks and the program-set environment of one program (empty when it is not in the inputs)."""
        programs, _ = self._programs(files)
        found = next((p for p in programs if p.name == program.rsplit(".", 1)[-1].upper()), None)
        if found is None:
            return [], []
        return quirks.detect(found, device_formats(self._dds(files))), quirks.program_environment(found)

    def coverage_branches(self, files: list[SourceFile], program: str) -> list[CoveredBranch]:
        """The subroutines and procedures of a program: the units an IBM i trace or coverage tool reports as run."""
        programs, _ = self._programs(files)
        found = next((p for p in programs if p.name == program.upper()), None)
        if found is None:
            return []
        return [CoveredBranch(id=r.name, kind=r.kind, line_start=r.line_start, line_end=r.line_end, file=found.file)
                for r in found.routines if r.kind != "mainline"]  # fmt: skip

    def digest(self, files: list[SourceFile]) -> str:
        inventory = self.inventory(files)
        programs, _ = self._programs(files)
        lines = [f"Metrics: {json.dumps(inventory.metrics)}"]
        for program in programs:
            kind = "service program module (no main)" if program.nomain else "program"
            lines.append(f"Program {program.name} ({program.variant} {kind}, {program.file}:{program.line_start}-"
                         f"{program.line_end}); parameters: {', '.join(program.parameters) or 'none'}")  # fmt: skip
            for item in program.fields:
                if item.role == "parameter":
                    mapping = to_neutral(item.kind, item.length, item.decimals)
                    lines.append(f"  parameter {item.name}: {mapping.neutral or mapping.source}")
            exported = [r.name for r in program.routines if r.exported]
            if exported:
                lines.append(f"  exported procedures: {', '.join(exported)}")
        described = self._dds(files)
        by_name = {d.name: d for d in described}
        for d in described:
            if d.kind in ("PF", "LF"):
                keys = ", ".join(k for r in d.records for k in r.keys)
                columns = ", ".join(f"{f.name} {column_type(d, f, by_name).source}" for f in d.fields[:40])
                lines.append(f"Table {d.name} ({d.kind}{', keys ' + keys if keys else ''}): {columns}")
            else:
                lines.append(f"{'Display' if d.kind == 'DSPF' else 'Printer'} file {d.name}: records "
                             f"{', '.join(r.name for r in d.records)}")  # fmt: skip
        uses = {"CALLS", "READS", "WRITES", "USES_MAP", "COPIES", "EXEC_SQL"}
        lines += [f"{e.source} {e.type} {e.target}" + (f" ({e.properties['kind']})" if "kind" in e.properties else "")
                  for e in inventory.edges if e.type in uses]  # fmt: skip
        sets, problems = load_traces(files)
        for trace in sets:
            lines.append(f"The legacy does not run here: the golden master of {trace.program} comes from its recorded "
                         f"traces ({trace.file}). Use \"program\": \"{trace.program}\" and the trace names as case "
                         "names; say which rules each one exercises.")  # fmt: skip
        lines.extend(f"Trace problem: {p}" for p in problems)
        return "\n".join(lines)


def column_type(d: dds.DdsFile, item: dds.DdsField, by_name: dict[str, dds.DdsFile]) -> TypeMapping:
    """A DDS field's type; a field of a logical file without its own length takes the one of its physical file."""
    if item.length is None:
        for based in d.based_on:
            found = next((f for f in by_name[based].fields if f.name == item.name), None) if based in by_name else None
            if found is not None:
                return column_type(by_name[based], found, by_name)
    return to_neutral(item.kind or ("P" if item.decimals is not None else "A"), item.length, item.decimals)


def device_formats(described: list[dds.DdsFile]) -> set[str]:
    """The record formats of the display and printer files: what a WRITE to them sends to a device."""
    return {r.name for d in described if d.kind in ("DSPF", "PRTF") for r in d.records}


def _devices(described: list[dds.DdsFile]) -> dict[str, str]:
    """Display and printer files by name: DSPF or PRTF."""
    return {d.name: d.kind for d in described if d.kind in ("DSPF", "PRTF")}


def _callee(s: Statement) -> str:
    if s.base in ("CALL", "CALLB"):
        text = (s.factor2 or "").strip().strip("'").split("(")[0]
        return text.split("/")[-1].upper().strip("'")
    match = re.match(r"\s*([A-Za-z_#$@][\w#$@]*)", s.factor2)
    return match.group(1).upper() if match else ""


def _file_operand(s: Statement) -> str:
    """The file or record format a file operation works on (fixed: factor 2; free: by opcode)."""
    if s.factor1 or s.result or not s.operands():
        target = s.factor2.split()[0] if s.factor2.split() else ""
        return target.upper()
    operands = s.operands()
    keyed = s.base in ("CHAIN", "SETLL", "SETGT", "READE", "READPE") or (s.base == "DELETE" and len(operands) > 1)
    index = 1 if keyed and len(operands) > 1 else 0
    return operands[index].split("(")[0].upper() if len(operands) > index else ""


def flow(program: RpgProgram, ranges: list[tuple[int, int]], formats: dict[str, str]) -> tuple[set[str], set[str]]:
    """What the statements inside the ranges read and write: variables and files (by file, not record format)."""
    reads: set[str] = set()
    writes: set[str] = set()
    for s in program.statements():
        if not any(a <= s.line_start <= b for a, b in ranges):
            continue
        if s.base in READS:
            target = _file_operand(s)
            if target:
                reads.add(formats.get(target, target))
            reads |= s.names() - {target}
            continue
        if s.base in WRITES:
            target = _file_operand(s)
            if target:
                writes.add(formats.get(target, target))
            continue
        if s.base == "EXEC SQL":
            r, w = sql_tables(s)
            reads |= r
            writes |= w
            continue
        if s.base in ("EVAL", "EVALR"):
            match = _ASSIGN.match(s.factor2)
            if match:
                target = re.split(r"[(.]", match.group(1))[0].upper()
                writes.add(target)
                reads |= Statement("EVAL", 0, 0, factor2=match.group(2)).names()
            continue
        if s.base in _JUMPS:
            continue  # the name is a subroutine or a label, not data
        if s.base in _ARITHMETIC and s.result:
            writes.add(s.result.split("(")[0].upper())
            reads |= {n for n in (s.factor1.upper(), s.factor2.split("(")[0].upper()) if n and not n.startswith("*")
                      and not n.replace(".", "").isdigit() and not n.startswith("'")}  # fmt: skip
            continue
        reads |= s.names()
    return reads, writes


def _unique(edges: list[Edge]) -> list[Edge]:
    seen: set[tuple[str, str, str]] = set()
    unique = []
    for edge in edges:
        pair = (edge.source, edge.type, edge.target)
        if pair not in seen:
            seen.add(pair)
            unique.append(edge)
    return unique


__all__ = [
    "FieldDecl",
    "FileDecl",
    "Routine",
    "RpgAdapter",
    "RpgProgram",
    "Statement",
    "TypeMapping",
    "cl",
    "column_type",
    "dds",
    "flow",
    "kind_of",
    "parse",
    "to_neutral",
]  # fmt: skip
