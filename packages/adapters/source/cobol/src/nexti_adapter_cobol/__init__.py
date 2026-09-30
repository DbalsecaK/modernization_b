"""The COBOL/CICS source adapter (spec 8.2, 8.3; ADR-0015): recognises COBOL programs, copybooks and CICS resource
definitions, parses them deterministically and builds the code layer of the knowledge graph as the family
Transaction -> Program -> Map (with the BMS adapter for the maps), with copybooks, VSAM files and paragraphs. It
also gives the neutral types, the classification of the statements, the slices the extractor reads and the data a
range of lines reads and writes. It never uses a model and never executes anything."""

import json
import re
from pathlib import PurePosixPath

from nexti_adapter_bms import BmsAdapter
from nexti_adapter_cobol.parser import (
    SYSTEM_COPYBOOKS,
    CicsCommand,
    CobolError,
    Copybook,
    DataItem,
    Paragraph,
    Program,
    Statement,
    TransactionDef,
    detect_programs,
    parse_copybook,
    parse_csd,
    parse_program,
)
from nexti_adapter_cobol.traces import TraceRunner, TraceSet, is_trace, load_traces
from nexti_adapter_cobol.types import TypeMapping, to_neutral
from nexti_core.adapters import Edge, EdgeType, Inventory, Node, SliceView, SourceFile
from nexti_core.spec.screens import ScreenSpec

PROGRAM_EXTENSIONS = (".cbl", ".cob", ".cobol")
COPYBOOK_EXTENSIONS = (".cpy", ".copy", ".cbc")
CSD_EXTENSIONS = (".csd",)
_CICS = re.compile(r"\bEXEC\s+CICS\b", re.IGNORECASE)
_DEFINE_TRANSACTION = re.compile(r"\bDEFINE\s+TRANSACTION\s*\(", re.IGNORECASE)
_INFRASTRUCTURE = {"SEND MAP", "SEND TEXT", "SEND CONTROL", "RECEIVE MAP", "RETURN", "XCTL", "SYNCPOINT", "ASKTIME",
                   "FORMATTIME", "HANDLE CONDITION", "HANDLE AID", "HANDLE ABEND", "ENDBR", "UNLOCK"}  # fmt: skip
_CONTROL = {"PERFORM", "IF", "ELSE", "END-IF", "EVALUATE", "WHEN", "END-EVALUATE", "GO", "CONTINUE", "END-PERFORM",
            "EXIT", "GOBACK", "STOP"}  # fmt: skip
_FILE_READS = {"READ", "READNEXT", "READPREV", "STARTBR"}
_FILE_WRITES = {"WRITE", "REWRITE", "DELETE"}


def _stem(path: str) -> str:
    return PurePosixPath(path).stem.upper()


class CobolAdapter:
    name = "cobol-cics"

    # -- the workspace ------------------------------------------------------------------------------------------
    def _programs(self, files: list[SourceFile]) -> tuple[list[Program], list[str]]:
        programs, problems = [], []
        for f in files:
            if f.path.lower().endswith(PROGRAM_EXTENSIONS) or (
                not f.path.lower().endswith(COPYBOOK_EXTENSIONS) and detect_programs(f.text)
            ):
                try:
                    programs.append(parse_program(f.path, f.text))
                except CobolError as exc:
                    problems.append(f"{f.path}:{exc.line}: {exc}")
        return programs, problems

    def _copybooks(self, files: list[SourceFile]) -> dict[str, Copybook]:
        return {_stem(f.path): parse_copybook(_stem(f.path), f.path, f.text) for f in files
                if f.path.lower().endswith(COPYBOOK_EXTENSIONS)}  # fmt: skip

    def _transactions(self, files: list[SourceFile]) -> list[TransactionDef]:
        return [t for f in files if f.path.lower().endswith(CSD_EXTENSIONS) or _DEFINE_TRANSACTION.search(f.text)
                for t in parse_csd(f.path, f.text)]  # fmt: skip

    def _data(self, programs: list[Program], copybooks: dict[str, Copybook]) -> list[DataItem]:
        return [i for p in programs for i in p.data] + [i for c in copybooks.values() for i in c.data]

    def detect(self, files: list[SourceFile]) -> float:
        programs = [f for f in files if f.path.lower().endswith(PROGRAM_EXTENSIONS) or detect_programs(f.text)]
        if not programs:
            return 0.0
        markers = sum(min(len(_CICS.findall(f.text)), 20) for f in programs)
        return round(min(1.0, 0.6 + markers / (40 * len(programs))), 2)

    def screens(self, files: list[SourceFile]) -> list[ScreenSpec]:
        return BmsAdapter().screens(files)

    # -- inventory (8.2 inventory) ------------------------------------------------------------------------------
    def inventory(self, files: list[SourceFile]) -> Inventory:
        programs, problems = self._programs(files)
        copybooks = self._copybooks(files)
        transactions = self._transactions(files)
        maps = BmsAdapter().inventory(files)
        inv = Inventory(self.name, list(maps.nodes), list(maps.edges), problems=problems + maps.problems)
        map_keys = {n.name: n.key for n in maps.nodes if n.label == "BmsMap"}
        known = {p.name for p in programs}
        external: set[str] = set()
        files_used: dict[str, set[str]] = {}
        for tx in transactions:
            inv.nodes.append(Node(f"tx:{tx.transid}", "Transaction", tx.transid, tx.file, tx.line, tx.line,
                                  {"description": tx.description}))  # fmt: skip
            inv.edges.append(Edge(f"tx:{tx.transid}", "STARTS", f"program:{tx.program}"))
            if tx.program not in known:
                external.add(tx.program)
        for name, book in sorted(copybooks.items()):
            last = max([i.line for i in book.data] or [1])
            inv.nodes.append(Node(f"copybook:{name}", "Copybook", name, book.file, 1, last, {"items": len(book.data)}))
            self._fields(inv, f"copybook:{name}", name, book.data)
            for other, line in book.copies:
                inv.edges.append(Edge(f"copybook:{name}", "COPIES", f"copybook:{other}", {"line": line}))
        statements = decisions = commands = 0
        for program in programs:
            key = f"program:{program.name}"
            stmts = program.statements()
            statements += len(stmts)
            branch = sum(1 for s in stmts if s.verb in ("IF", "WHEN"))
            decisions += branch
            cics = [s.cics for s in stmts if s.cics is not None]
            commands += len(cics)
            inv.nodes.append(Node(key, "Program", program.name, program.file, program.line_start, program.line_end, {
                "language": "COBOL", "statements": len(stmts), "complexity": 1 + branch,
                "paragraphs": len(program.paragraphs), "cics_commands": len(cics),
                "lines": program.line_end - program.line_start + 1,
            }))  # fmt: skip
            inv.problems.extend(program.problems)
            self._fields(inv, key, program.name, program.data)
            for copied, line in program.copies:
                if copied in SYSTEM_COPYBOOKS:
                    continue
                if copied not in copybooks:
                    inv.problems.append(f"{program.file}:{line}: copybook {copied} is not in the inputs")
                    inv.nodes.append(Node(f"copybook:{copied}", "Copybook", copied, properties={"missing": True}))
                    copybooks[copied] = Copybook(copied, "", [])
                inv.edges.append(Edge(key, "COPIES", f"copybook:{copied}", {"line": line}))
            for paragraph in program.paragraphs:
                pkey = f"para:{program.name}.{paragraph.name}"
                inv.nodes.append(Node(pkey, "Paragraph", paragraph.name, program.file, paragraph.line_start,
                                      paragraph.line_end, {"statements": len(paragraph.statements),
                                                           "program": program.name}))  # fmt: skip
                inv.edges.append(Edge(key, "CONTAINS", pkey))
                for target, line in paragraph.performs():
                    if program.paragraph(target) is None:
                        inv.problems.append(f"{program.file}:{line}: PERFORM of unknown paragraph {target}")
                        continue
                    inv.edges.append(Edge(pkey, "PERFORMS", f"para:{program.name}.{target}", {"line": line}))
                for callee, line in paragraph.calls():
                    inv.edges.append(Edge(key, "CALLS", f"program:{callee}", {"kind": "CALL", "line": line}))
                    if callee not in known:
                        external.add(callee)
                for command in paragraph.cics():
                    self._cics_edges(inv, program, command, map_keys, known, external, files_used)
        for callee in sorted(external):
            inv.nodes.append(Node(f"program:{callee}", "Program", callee, properties={"external": True}))
        defined = {n.name for n in inv.nodes if n.label == "File"}
        for name in sorted(set(files_used) - defined):
            inv.nodes.append(
                Node(f"file:{name}", "File", name, properties={"access": ",".join(sorted(files_used[name]))})
            )
        inv.edges = _unique(inv.edges)
        inv.metrics = {
            "programs": len(programs), "paragraphs": sum(len(p.paragraphs) for p in programs),
            "statements": statements, "decisions": decisions, "copybooks": len(copybooks),
            "transactions": len(transactions), "maps": len(map_keys), "files": len(files_used),
            "cics_commands": commands, "external_calls": len(external),
            "lines": sum(p.line_end - p.line_start + 1 for p in programs),
        }  # fmt: skip
        return inv

    def _fields(self, inv: Inventory, owner: str, prefix: str, items: list[DataItem]) -> None:
        for item in items:
            if item.name == "FILLER" or item.level == 88:
                continue
            mapping = to_neutral(item.picture, item.usage)
            key = f"field:{prefix}.{item.name}"
            inv.nodes.append(Node(key, "Field", item.name, item.file, item.line, item.line, {
                "level": item.level, "source_type": mapping.source,
                "neutral_type": str(mapping.neutral) if mapping.neutral else "",
                "conditions": ",".join(n for n, _ in item.conditions), "note": mapping.note,
            }))  # fmt: skip
            inv.edges.append(Edge(owner, "DECLARES", key))
            if item.redefines:
                inv.edges.append(Edge(key, "REDEFINES", f"field:{prefix}.{item.redefines}"))

    def _cics_edges(
        self, inv: Inventory, program: Program, command: CicsCommand, map_keys: dict[str, str], known: set[str],
        external: set[str], files_used: dict[str, set[str]],
    ) -> None:  # fmt: skip
        key = f"program:{program.name}"
        line: dict[str, str | int | float | bool | None] = {"line": command.line_start, "command": command.command}
        if command.command in ("LINK", "XCTL") and command.option("PROGRAM"):
            callee = str(command.option("PROGRAM")).upper()
            inv.edges.append(Edge(key, "CALLS", f"program:{callee}", {**line, "kind": command.command}))
            if callee not in known:
                external.add(callee)
        elif command.command in ("SEND MAP", "RECEIVE MAP") and command.option("MAP"):
            name = str(command.option("MAP")).upper()
            mapset = (command.option("MAPSET") or "").upper()
            target = f"map:{mapset}.{name}" if mapset else map_keys.get(name, f"map:{name}")
            inv.edges.append(Edge(key, "USES_MAP", target, line))
        elif command.command in _FILE_READS | _FILE_WRITES and (command.option("FILE") or command.option("DATASET")):
            name = str(command.option("FILE") or command.option("DATASET")).upper()
            files_used.setdefault(name, set()).add(command.command)
            kind: EdgeType = "READS" if command.command in _FILE_READS else "WRITES"
            inv.edges.append(Edge(key, kind, f"file:{name}", line))
        elif command.command in ("RETURN", "START") and command.option("TRANSID"):
            inv.edges.append(Edge(key, "EXEC_CICS", f"tx:{str(command.option('TRANSID')).upper()}", line))

    # -- types, classification, slices, data (8.2) --------------------------------------------------------------
    def types(self, files: list[SourceFile]) -> dict[str, str]:
        programs, _ = self._programs(files)
        found: dict[str, str] = {}
        for item in self._data(programs, self._copybooks(files)):
            if item.name == "FILLER" or item.level == 88:
                continue
            mapping = to_neutral(item.picture, item.usage)
            if mapping.neutral is not None:
                found.setdefault(item.name, str(mapping.neutral))
        return found

    def classification(self, files: list[SourceFile]) -> dict[str, int]:
        counts = {"infrastructure": 0, "control_flow": 0, "business": 0}
        programs, _ = self._programs(files)
        for statement in (s for p in programs for s in p.statements()):
            counts[_kind(statement)] += 1
        return counts

    def slices(self, files: list[SourceFile]) -> list[SliceView]:
        """One slice per program: the paragraphs with business or control statements (pure screen handling is left
        out), the map fields and COMMAREA items it reads as parameters and the files it uses as tables."""
        programs, _ = self._programs(files)
        copybooks = self._copybooks(files)
        known = {i.name for i in self._data(programs, copybooks)}
        views = []
        for program in programs:
            ranges = [(p.line_start, p.line_end) for p in program.paragraphs
                      if any(_kind(s) == "business" for s in p.statements)]  # fmt: skip
            if not ranges:
                continue
            reads, _ = self._flow(program, ranges, known)
            # Parameters: what the program receives, i.e. its LINKAGE items (COMMAREA) and the input fields of its maps.
            linkage = {i.name for i in program.data if i.section == "LINKAGE"} | {
                i.name for book in program.linkage_copies if book in copybooks for i in copybooks[book].data
            }
            inputs = {n for n in known if n.endswith("I") and n[:-1] + "O" in known}
            parameters = sorted(n for n in reads if n in linkage | inputs)
            tables = sorted({str(c.option("FILE")).upper() for s in program.statements() if (c := s.cics)
                             and c.command in _FILE_READS | _FILE_WRITES and c.option("FILE")})  # fmt: skip
            views.append(SliceView(program.name, program.file, tuple(ranges), tuple(parameters), tuple(tables)))
        return views

    def data_of(
        self, files: list[SourceFile], file: str, ranges: list[tuple[int, int]]
    ) -> tuple[frozenset[str], frozenset[str]]:
        programs, _ = self._programs(files)
        program = next((p for p in programs if p.file == file or _stem(p.file) == _stem(file)), None)
        if program is None:
            return frozenset(), frozenset()
        known = {i.name for i in self._data(programs, self._copybooks(files))}
        reads, writes = self._flow(program, ranges, known)
        return frozenset(reads), frozenset(writes)

    def _flow(self, program: Program, ranges: list[tuple[int, int]], known: set[str]) -> tuple[set[str], set[str]]:
        reads: set[str] = set()
        writes: set[str] = set()
        for statement in program.statements():
            if not any(a <= statement.line_start <= b for a, b in ranges):
                continue
            if statement.cics is not None:
                c = statement.cics
                for option in ("RIDFLD", "FROM", "COMMAREA", "LENGTH"):
                    argument = (c.option(option) or "").upper().replace("LENGTH OF ", "")
                    if argument in known:
                        reads.add(argument)
                target = c.option("FILE")
                if target and c.command in _FILE_READS:
                    reads.add(target.upper())
                    if c.option("INTO"):
                        writes.add(str(c.option("INTO")).upper())
                elif target and c.command in _FILE_WRITES:
                    writes.add(target.upper())
                elif c.command == "RECEIVE MAP" and c.option("INTO"):
                    writes.add(str(c.option("INTO")).upper())
                continue
            written = {n for n in statement.writes() if n in known}
            writes |= written
            reads |= {n for n in statement.names() if n in known and n not in written}
        return reads, writes

    def transactions(self, files: list[SourceFile]) -> list[TransactionDef]:
        return self._transactions(files)

    def digest(self, files: list[SourceFile]) -> str:
        """Transactions, programs with what they use, file records and, when the legacy cannot run, the traces the
        golden master comes from."""
        inventory = self.inventory(files)
        copybooks = self._copybooks(files)
        lines = [f"Metrics: {json.dumps(inventory.metrics)}"]
        for node in inventory.nodes:
            if node.label == "Transaction":
                lines.append(f"Transaction {node.name} ({node.properties.get('description', '')})")
            elif node.label == "Program":
                where = f"{node.file}:{node.line_start}-{node.line_end}" if node.file else "not in the inputs: stub it"
                lines.append(f"Program {node.name} ({where})")
        uses = {"STARTS", "CALLS", "USES_MAP", "READS", "WRITES", "COPIES", "EXEC_CICS"}
        for edge in inventory.edges:
            if edge.type in uses:
                kind = f" ({edge.properties['kind']})" if "kind" in edge.properties else ""
                lines.append(f"{edge.source} {edge.type} {edge.target}{kind}")
        for name in sorted({e.target.split(":", 1)[1] for e in inventory.edges if e.type == "COPIES"}):
            book = copybooks.get(name)
            if book is None:
                continue
            fields = [f"{i.name} {to_neutral(i.picture, i.usage).source}" for i in book.data
                      if i.picture and i.name != "FILLER" and not i.name.endswith(("L", "F"))]  # fmt: skip
            lines.append(f"Copybook {name}: " + ", ".join(fields[:40]))
        sets, problems = load_traces(files)
        for trace in sets:
            lines.append(f"The legacy does not run here: the golden master of {trace.program} comes from its recorded "
                         f"traces ({trace.file}). Use \"program\": \"{trace.program}\", the tables of the traces "
                         "(below) and the trace names as case names; say which rules each one exercises. Inputs are "
                         "the map fields without their I/O suffix, as the traces name them.")  # fmt: skip
            for table in trace.schema.tables:
                columns = ", ".join(f"{c.name} {c.type}" for c in table.columns)
                lines.append(f"  table {table.name} (key {', '.join(table.key)}): {columns}")
            for recorded in trace.results:
                case, seen = recorded.case, recorded.observation
                lines.append(f"  trace {case.name}: {case.description}; inputs {json.dumps(case.inputs)}; "
                             f"sends {json.dumps(seen.outputs)}")  # fmt: skip
        lines.extend(f"Trace problem: {p}" for p in problems)
        return "\n".join(lines)


def _kind(statement: Statement) -> str:
    if statement.cics is not None:
        return "infrastructure" if statement.cics.command in _INFRASTRUCTURE else "business"
    if statement.verb in _CONTROL:
        return "control_flow"
    words = [t.upper for t in statement.tokens]
    if statement.verb == "MOVE" and len(words) > 1 and words[1] in ("LOW-VALUES", "LOW-VALUE", "SPACES"):
        return "infrastructure"
    return "business"


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
    "CicsCommand", "CobolAdapter", "CobolError", "Copybook", "DataItem", "Paragraph", "Program", "Statement",
    "TraceRunner", "TraceSet", "TransactionDef", "TypeMapping", "is_trace", "load_traces", "parse_copybook",
    "parse_csd", "parse_program", "to_neutral",
]  # fmt: skip
