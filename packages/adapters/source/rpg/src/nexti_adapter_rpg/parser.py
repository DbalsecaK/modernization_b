"""A deterministic parser of a documented subset of RPG (spec 8.2, ADR-0051), in its four forms:

- RPG III / RPG/400 (OPM), fixed form: F, E, I, C, O specs with the RPG III columns (opcode in 28-32);
- RPG IV fixed form (ILE): H, F, D, C, P specs with the RPG IV columns (opcode in 26-35, extended factor 2);
- RPG IV mixed: fixed specs with free-form calculations (`/FREE ... /END-FREE`, or free lines from column 8);
- RPG IV fully free (`**FREE`): `ctl-opt`, `dcl-f`, `dcl-s`, `dcl-ds`, `dcl-pr`, `dcl-pi`, `dcl-proc`.

It reads files (F specs / dcl-f), fields (D specs / dcl-*, result fields with length in RPG III), the program's
parameters (*ENTRY PLIST or the procedure interface), subroutines and procedures with their statements, /COPY and
/INCLUDE members and embedded SQL. What it does not recognise is a problem with its line, never a guess. It never
uses a model and never executes anything."""

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

RPG3_EXTENSIONS = (".rpg", ".rpg38", ".rpg36", ".rpg400")
RPG4_EXTENSIONS = (".rpgle", ".sqlrpgle", ".rpgile", ".rpg4")
EXTENSIONS = RPG3_EXTENSIONS + RPG4_EXTENSIONS
_WORD = re.compile(r"[A-Za-z_#$@][A-Za-z0-9_#$@]*")
_STRING = re.compile(r"'(?:[^']|'')*'")
_BUILTIN = re.compile(r"%[A-Za-z]+")  # %FOUND, %EOF, %SUBST...: the built-in's name, not a variable
_OPERATORS = {"NOT", "AND", "OR"}
_SQL_TABLE = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+([A-Za-z_#$@][\w#$@]*(?:[./][A-Za-z_#$@][\w#$@]*)?)", re.I)
_COPY = re.compile(r"^\s*/(COPY|INCLUDE)\s+(\S+)", re.I)
_FREE_DIRECTIVE = re.compile(r"^\s*/(FREE|END-FREE)\b", re.I)
# Opcodes whose factor 2 is the whole rest of the line (RPG IV extended factor 2).
EXTENDED = {"EVAL", "EVALR", "EVAL-CORR", "IF", "ELSEIF", "DOW", "DOU", "WHEN", "FOR", "CALLP", "RETURN", "ON-ERROR",
            "SORTA", "DSPLY", "XML-INTO", "DATA-INTO", "SND-MSG"}  # fmt: skip
READS = {"CHAIN", "READ", "READE", "READP", "READPE", "READC", "SETLL", "SETGT"}
WRITES = {"WRITE", "UPDATE", "DELETE"}
CONTROL = {"IF", "ELSE", "ELSEIF", "ENDIF", "END", "DO", "DOW", "DOU", "ENDDO", "FOR", "ENDFOR", "SELECT", "WHEN",
           "OTHER", "ENDSL", "ITER", "LEAVE", "LEAVESR", "EXSR", "BEGSR", "ENDSR", "GOTO", "TAG", "RETURN", "MONITOR",
           "ON-ERROR", "ENDMON", "CASEQ", "CASNE", "CASGT", "CASLT", "CASGE", "CASLE", "CAS", "ENDCS",
           "CABEQ", "CABNE", "CABGT", "CABLT", "CABGE", "CABLE"}  # fmt: skip
INFRASTRUCTURE = {"OPEN", "CLOSE", "DSPLY", "SETON", "SETOFF", "COMMIT", "ROLBK", "EXFMT", "UNLOCK", "FEOD", "DUMP",
                  "PLIST", "PARM", "KLIST", "KFLD", "DEFINE", "ACQ", "REL", "POST", "SHTDN", "TIME"}  # fmt: skip
# RPG III comparison opcodes (IFEQ, DOWLT, ...) behave as their base opcode with a relational code.
_RELATIONAL = re.compile(r"^(IF|DOW|DOU|WH|AND|OR|CAB|CAS)(EQ|NE|GT|LT|GE|LE)$")


class RpgError(ValueError):
    def __init__(self, line: int, message: str) -> None:
        super().__init__(message)
        self.line = line


@dataclass
class Statement:
    opcode: str  # upper case, without the extender: CHAIN, EVAL, IF, EXEC SQL...
    line_start: int
    line_end: int
    factor1: str = ""
    factor2: str = ""  # in free form, the whole operand text
    result: str = ""
    extender: str = ""  # H, E, N... (RPG III half adjust in column 53 is H too)
    indicators: str = ""  # the resulting indicators of a fixed-form operation (hi, lo, eq)
    level: str = ""  # L1..L9 or LR: the control level of a fixed-form calculation (the RPG cycle)

    @property
    def base(self) -> str:
        """IFEQ -> IF, WHGT -> WHEN, CABLT -> CAB: the opcode without the RPG III relational code."""
        match = _RELATIONAL.match(self.opcode)
        if not match:
            return self.opcode
        return {"WH": "WHEN"}.get(match.group(1), match.group(1))

    def names(self) -> set[str]:
        """The identifiers the statement mentions (upper case), outside string literals."""
        text = _BUILTIN.sub(" ", _STRING.sub(" ", f"{self.factor1} {self.factor2} {self.result}"))
        return {w.upper() for w in _WORD.findall(text) if not w.startswith("*") and w.upper() not in _OPERATORS}

    def operands(self) -> list[str]:
        """The operands of a free-form statement, split at blanks outside parentheses and strings."""
        text = _STRING.sub("''", self.factor2)
        parts, depth, current = [], 0, ""
        for char in text:
            if char in "(":
                depth += 1
            elif char == ")":
                depth -= 1
            if char.isspace() and depth == 0:
                if current:
                    parts.append(current)
                current = ""
            else:
                current += char
        if current:
            parts.append(current)
        return parts


@dataclass
class FileDecl:
    name: str
    usage: str  # I input, O output, U update, C combined (display)
    device: str  # DISK, WORKSTN, PRINTER, SPECIAL, SEQ
    keyed: bool
    line: int
    external: bool = True
    primary: bool = False  # the primary file of the RPG cycle: the program reads it record by record implicitly


@dataclass
class FieldDecl:
    name: str
    kind: str  # the type letter or keyword
    length: int | None
    decimals: int | None
    line: int
    role: str = "standalone"  # standalone, subfield, constant, parameter, ds


@dataclass
class Routine:
    name: str
    kind: str  # mainline, subroutine, procedure
    line_start: int
    line_end: int
    statements: list[Statement] = field(default_factory=list)
    exported: bool = False


@dataclass
class RpgProgram:
    name: str
    file: str
    variant: str  # rpg3, rpg4-fixed, rpg4-mixed, rpg4-free
    line_start: int
    line_end: int
    files: list[FileDecl] = field(default_factory=list)
    fields: list[FieldDecl] = field(default_factory=list)
    parameters: list[str] = field(default_factory=list)
    routines: list[Routine] = field(default_factory=list)
    copies: list[tuple[str, int]] = field(default_factory=list)
    nomain: bool = False  # a module of a service program (*SRVPGM)
    control: str = ""  # the H spec / ctl-opt keywords (DATFMT, EXPROPTS...) and each file's keywords, upper case
    problems: list[str] = field(default_factory=list)

    def statements(self) -> list[Statement]:
        return [s for r in self.routines for s in r.statements]

    def routine(self, name: str) -> Routine | None:
        return next((r for r in self.routines if r.name == name.upper()), None)


def _int(text: str) -> int | None:
    text = text.strip()
    return int(text) if text.isdigit() else None


def _col(line: str, start: int, end: int) -> str:
    """Columns start..end (1-based, inclusive) of a fixed-form line."""
    return line[start - 1 : end].strip() if len(line) >= start else ""


def detect(path: str, text: str) -> bool:
    if path.lower().endswith(EXTENSIONS):
        return True
    head = text[:4000].upper()
    return head.lstrip().startswith("**FREE") or bool(re.search(r"(?m)^.{5}[HFDC][ ].{20,}", head) and (
        "DCL-" in head or "BEGSR" in head or "CHAIN" in head))  # fmt: skip


def parse(path: str, text: str) -> RpgProgram:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    name = PurePosixPath(path).stem.upper()
    fully_free = bool(lines) and lines[0].strip().upper().startswith("**FREE")
    rpg3 = path.lower().endswith(RPG3_EXTENSIONS)
    program = RpgProgram(name, path, "rpg4-free" if fully_free else "rpg3" if rpg3 else "rpg4-fixed", 1, len(lines))
    builder = _Builder(program)
    free_block = False
    pending: list[tuple[int, str]] = []  # a free-form statement split over lines, until its `;`
    for number, raw in enumerate(lines, start=1):
        if fully_free and number == 1:
            continue
        line = raw.rstrip()
        copy = _COPY.match(line[5:] if not fully_free and len(line) > 5 and line[:5].strip().isdigit() else line)
        if copy:
            program.copies.append((copy.group(2).split(",")[-1].upper(), number))
            continue
        directive = _FREE_DIRECTIVE.match(line[6:] if not fully_free and len(line) > 6 else line)
        if directive and not fully_free:
            free_block = directive.group(1).upper() == "FREE"
            program.variant = "rpg4-mixed"
            continue
        if fully_free or free_block or _free_line(line, rpg3):
            if not fully_free and not free_block and line.strip():
                program.variant = "rpg4-mixed"
            body = line if fully_free else line[7:] if len(line) > 7 else ""
            body = _strip_comment(body)
            if not body.strip():
                continue
            pending.append((number, body))
            if body.rstrip().endswith(";"):
                builder.free(pending)
                pending = []
            continue
        if len(line) < 6 or line[6:7] == "*" or not line[5:6].strip():
            continue
        builder.fixed(number, line, rpg3)
    if pending:
        builder.free(pending)
    builder.finish(len(lines))
    return program


def _free_line(line: str, rpg3: bool) -> bool:
    """RPG IV 7.1+: a line with columns 6-7 blank and code from column 8 is free form."""
    return not rpg3 and len(line) > 7 and not line[5:7].strip() and bool(line[7:].strip())


def _strip_comment(text: str) -> str:
    out, in_string, i = [], False, 0
    while i < len(text):
        char = text[i]
        if char == "'":
            in_string = not in_string
        if not in_string and text.startswith("//", i):
            break
        out.append(char)
        i += 1
    return "".join(out)


class _Builder:
    """Assembles routines from statements in source order: BEGSR/ENDSR and procedures open and close routines; the
    rest belongs to the mainline (cycle or linear main)."""

    def __init__(self, program: RpgProgram) -> None:
        self.p = program
        self.main = Routine("*MAIN", "mainline", 1, 1)
        self.current: Routine = self.main
        self.procedure: Routine | None = None
        self.entry_plist = False
        self.interface = False
        self.ds = False
        self.prototype = False
        self.sql: tuple[int, list[str]] | None = None

    # -- free form ----------------------------------------------------------------------------------------------
    def free(self, pending: list[tuple[int, str]]) -> None:
        start, end = pending[0][0], pending[-1][0]
        text = " ".join(t.strip() for _, t in pending).rstrip(";").strip()
        word, _, rest = text.partition(" ")
        opcode = word.upper()
        extender = ""
        if "(" in opcode and opcode.endswith(")") and not opcode.startswith(("DCL", "END")):
            opcode, _, extender = opcode[:-1].partition("(")
        if opcode in ("CTL-OPT", "H"):
            self.p.nomain = self.p.nomain or "NOMAIN" in rest.upper()
            self.p.control += f" {rest.upper()}"
            return
        if opcode == "DCL-F":
            self._dcl_f(start, rest)
            return
        if opcode in ("DCL-S", "DCL-C", "DCL-SUBF") or (self.ds and opcode not in ("END-DS",)) or (
            self.interface and opcode not in ("END-PI",)):  # fmt: skip
            self._dcl_field(start, rest if opcode in ("DCL-S", "DCL-C", "DCL-SUBF") else text, opcode)
            return
        if opcode == "DCL-DS":
            self.ds = not rest.upper().rstrip().endswith("END-DS") and "LIKEDS" not in rest.upper()
            ds_name = rest.split()[0] if rest.split() else ""
            if ds_name and not ds_name.startswith("*"):
                self.p.fields.append(FieldDecl(ds_name.upper(), "DS", None, None, start, "ds"))
            return
        if opcode == "END-DS":
            self.ds = False
            return
        if opcode == "DCL-PI":
            self.interface = not rest.upper().rstrip().endswith("END-PI")
            return
        if opcode == "END-PI":
            self.interface = False
            return
        if opcode == "DCL-PR":
            self.prototype = not rest.upper().rstrip().endswith("END-PR")  # `dcl-pr x ... end-pr;` is one line
            return
        if opcode == "END-PR" or self.prototype:
            self.prototype = opcode != "END-PR"
            return
        if opcode == "DCL-PROC":
            parts = rest.split()
            self._open_procedure(parts[0].upper() if parts else "?", start, "EXPORT" in rest.upper())
            return
        if opcode == "END-PROC":
            self._close_procedure(end)
            return
        if opcode == "EXEC" and rest.upper().startswith("SQL"):
            self._statement(Statement("EXEC SQL", start, end, factor2=rest[3:].strip()))
            return
        if opcode == "BEGSR":
            self._open_subroutine(rest.split()[0].upper() if rest.split() else "?", start)
            return
        if opcode == "ENDSR":
            self._close_subroutine(end)
            return
        known = {*READS, *WRITES, *CONTROL, *INFRASTRUCTURE, *EXTENDED, "CALLP", "CALL", "EVAL", "CLEAR", "RESET",
                 "SORTA", "EXFMT", "NEXT", "IN", "OUT", "TEST", "DEALLOC"}  # fmt: skip
        if opcode in known:
            self._statement(Statement(opcode, start, end, factor2=rest.strip(), extender=extender))
            return
        if "=" in text and not text.upper().startswith(("IF ", "DOW ", "DOU ", "WHEN ")):
            self._statement(Statement("EVAL", start, end, factor2=text))  # an assignment without EVAL
            return
        if re.match(r"^[A-Za-z_#$@][\w#$@]*\s*\(", text):
            self._statement(Statement("CALLP", start, end, factor2=text))  # a prototyped call without CALLP
            return
        self._statement(Statement(opcode, start, end, factor2=rest.strip(), extender=extender))

    def _dcl_f(self, line: int, rest: str) -> None:
        parts = rest.split()
        if not parts:
            return
        upper = rest.upper()
        device = next((d for d in ("WORKSTN", "PRINTER", "SPECIAL", "SEQ") if d in upper), "DISK")
        usage = "C" if device == "WORKSTN" else "O" if device == "PRINTER" else "I"
        if re.search(r"USAGE\([^)]*\*(UPDATE|DELETE)", upper):
            usage = "U"
        elif re.search(r"USAGE\([^)]*\*OUTPUT", upper) and "*INPUT" not in upper:
            usage = "O"
        self.p.files.append(FileDecl(parts[0].upper(), usage, device, "KEYED" in upper, line))
        self.p.control += f" FILE({parts[0].upper()}: {upper})"

    def _dcl_field(self, line: int, text: str, opcode: str) -> None:
        parts = text.split(None, 1)
        if not parts:
            return
        name = parts[0].upper()
        if name in ("END-DS", "END-PI", "DCL-SUBF", "DCL-PARM"):
            return
        rest = parts[1] if len(parts) > 1 else ""
        kind, length, decimals = _free_type(rest)
        role = "constant" if opcode == "DCL-C" else "parameter" if self.interface else "subfield" if self.ds \
            else "standalone"  # fmt: skip
        self.p.fields.append(FieldDecl(name, kind, length, decimals, line, role))
        if self.interface and self.procedure is None:  # the program's own interface, not a procedure's
            self.p.parameters.append(name)

    # -- fixed form ---------------------------------------------------------------------------------------------
    def fixed(self, number: int, line: str, rpg3: bool) -> None:
        spec = line[5].upper()
        if spec == "H":
            self.p.nomain = self.p.nomain or "NOMAIN" in line.upper()
            self.p.control += f" {line[6:].upper()}"
        elif spec == "F":
            self._f_spec(number, line, rpg3)
        elif spec == "D" and not rpg3:
            self._d_spec(number, line)
        elif spec == "P" and not rpg3:
            name = _col(line, 7, 21).upper()
            if _col(line, 24, 24).upper() == "B":
                self._open_procedure(name, number, "EXPORT" in _col(line, 44, 80).upper())
            elif _col(line, 24, 24).upper() == "E":
                self._close_procedure(number)
        elif spec == "C":
            self._c_spec(number, line, rpg3)
        elif spec in ("I", "E", "O", "L"):
            if spec == "I" and rpg3 and _col(line, 53, 58):
                self.p.problems.append(f"{self.p.file}:{number}: program-described input fields are not parsed")
        elif spec != " ":
            self.p.problems.append(f"{self.p.file}:{number}: unknown specification {spec}")

    def _f_spec(self, number: int, line: str, rpg3: bool) -> None:
        if rpg3:
            name, usage, device = _col(line, 7, 14), _col(line, 15, 15), _col(line, 40, 46)
            keyed, external = _col(line, 31, 31).upper() == "K", _col(line, 19, 19).upper() == "E"
            primary = _col(line, 16, 16).upper() == "P"
        else:
            name, usage, device = _col(line, 7, 16), _col(line, 17, 17), _col(line, 36, 42)
            keyed, external = _col(line, 34, 34).upper() == "K", _col(line, 22, 22).upper() == "E"
            primary = _col(line, 18, 18).upper() == "P"
        if name:
            self.p.files.append(FileDecl(name.upper(), usage.upper() or "I", device.upper() or "DISK", keyed, number,
                                         external, primary))  # fmt: skip
            self.p.control += f" FILE({name.upper()}: {_col(line, 44 if not rpg3 else 54, 80).upper()})"

    def _d_spec(self, number: int, line: str) -> None:
        name = _col(line, 7, 21).upper()
        definition = _col(line, 24, 25).upper()
        to_length = _int(_col(line, 33, 39))
        kind = _col(line, 40, 40).upper()
        decimals = _int(_col(line, 41, 42))
        keywords = _col(line, 44, 80).upper()
        if definition == "DS":
            self.ds, self.interface = True, False
            if name:
                self.p.fields.append(FieldDecl(name, "DS", to_length, None, number, "ds"))
            return
        if definition in ("PI", "PR"):
            self.interface = definition == "PI"
            self.prototype = definition == "PR"
            self.ds = False
            return
        if definition in ("S", "C"):
            self.ds = self.interface = False
            self.prototype = False
        if not name or (self.prototype and not definition):
            return
        if not kind and to_length is not None:
            kind = "S" if self.ds else "P" if decimals is not None else "A"
        if "LIKE(" in keywords and not kind:
            kind = "LIKE"
        if definition == "C" and not kind:  # a named constant takes the type of its literal
            literal = re.match(r"(?:CONST\()?\s*([-+]?\d*\.?\d+)\s*\)?$", keywords)
            if literal:
                whole, _, fraction = literal.group(1).lstrip("+-").partition(".")
                kind, to_length, decimals = "P", len(whole.lstrip("0") or "0") + len(fraction), len(fraction)
        role = "constant" if definition == "C" else "parameter" if self.interface and not definition else \
            "subfield" if self.ds and not definition else "standalone"  # fmt: skip
        self.p.fields.append(FieldDecl(name, kind or "A", to_length, decimals, number, role))
        if role == "parameter" and self.procedure is None:
            self.p.parameters.append(name)

    def _c_spec(self, number: int, line: str, rpg3: bool) -> None:
        if line[6:7] == "/":  # C/EXEC SQL ... C+ ... C/END-EXEC
            word = line[7:].strip().upper()
            if word.startswith("EXEC SQL"):
                self.sql = (number, [line[7:].strip()[8:]])
            elif word.startswith("END-EXEC") and self.sql is not None:
                start, parts = self.sql
                self._statement(Statement("EXEC SQL", start, number, factor2=" ".join(parts).strip()))
                self.sql = None
            return
        if line[6:7] == "+" and self.sql is not None:
            self.sql[1].append(line[7:].strip())
            return
        if rpg3:
            factor1, opcode, factor2 = _col(line, 18, 27), _col(line, 28, 32), _col(line, 33, 42)
            result, length, decimals = _col(line, 43, 48), _int(_col(line, 49, 51)), _int(_col(line, 52, 52))
            half, indicators = _col(line, 53, 53).upper() == "H", _col(line, 54, 59)
        else:
            factor1, opcode, factor2 = _col(line, 12, 25), _col(line, 26, 35), _col(line, 36, 49)
            result, length, decimals = _col(line, 50, 63), _int(_col(line, 64, 68)), _int(_col(line, 69, 70))
            half, indicators = False, _col(line, 71, 76)
        opcode, _, extender = opcode.upper().partition("(")
        extender = extender.rstrip(")") or ("H" if half else "")
        level = _col(line, 7, 8).upper()  # L1..L9, LR: a calculation of the cycle's level breaks
        if not rpg3 and opcode in EXTENDED:
            factor2, result = _col(line, 36, 80), ""
        if not opcode:  # a continuation of the extended factor 2 of the previous statement
            target = self.current.statements[-1] if self.current.statements else None
            if target is not None and target.opcode in EXTENDED:
                target.factor2 = f"{target.factor2} {_col(line, 36, 80)}".strip()
                target.line_end = number
            return
        if result and length is not None:  # a field defined in the calculation (RPG III and IV)
            kind = "P" if decimals is not None else "A"
            self.p.fields.append(FieldDecl(result.upper(), kind, length, decimals, number))
        if opcode == "BEGSR":
            self._open_subroutine(factor1.upper(), number)
            return
        if opcode == "ENDSR":
            self._close_subroutine(number)
            return
        if opcode == "PLIST":
            self.entry_plist = factor1.upper() == "*ENTRY"
            return
        if opcode == "PARM":
            if self.entry_plist and result:
                self.p.parameters.append(result.upper())
                for item in self.p.fields:
                    if item.name == result.upper():
                        item.role = "parameter"
            return
        self.entry_plist = False
        if not rpg3 and opcode in EXTENDED:
            indicators = ""  # columns 71-76 belong to the extended factor 2
        self._statement(Statement(opcode, number, number, factor1, factor2, result, extender, indicators,
                                  level if level.startswith("L") else ""))  # fmt: skip

    # -- routines -----------------------------------------------------------------------------------------------
    def _statement(self, statement: Statement) -> None:
        self.current.statements.append(statement)
        self.current.line_end = max(self.current.line_end, statement.line_end)

    def _open_subroutine(self, name: str, line: int) -> None:
        self.current = Routine(name, "subroutine", line, line)
        self.p.routines.append(self.current)

    def _close_subroutine(self, line: int) -> None:
        self.current.line_end = line
        self.current = self.procedure or self.main

    def _open_procedure(self, name: str, line: int, exported: bool) -> None:
        self.procedure = Routine(name, "procedure", line, line, exported=exported)
        self.p.routines.append(self.procedure)
        self.current = self.procedure

    def _close_procedure(self, line: int) -> None:
        if self.procedure is not None:
            self.procedure.line_end = line
        self.procedure = None
        self.current = self.main

    def finish(self, last: int) -> None:
        if self.main.statements:
            self.main.line_start = self.main.statements[0].line_start
            self.p.routines.insert(0, self.main)
        if self.sql is not None:
            self.p.problems.append(f"{self.p.file}:{self.sql[0]}: EXEC SQL without END-EXEC")
        self.p.parameters = list(dict.fromkeys(self.p.parameters))


def _free_type(text: str) -> tuple[str, int | None, int | None]:
    """`packed(9:2) inz(0)` -> ("PACKED", 9, 2); `char(10)` -> ("CHAR", 10, None); `like(x)` -> ("LIKE", ...)."""
    match = re.match(r"\s*([A-Za-z-]+)\s*(?:\(\s*([^)]*)\))?", text)
    if not match:
        return "A", None, None
    kind = match.group(1).upper()
    numbers = [n.strip() for n in (match.group(2) or "").split(":")]
    length = _int(numbers[0]) if numbers and numbers[0] else None
    decimals = _int(numbers[1]) if len(numbers) > 1 else None
    if kind in ("INT", "UNS") and length is None:
        length = 10
    return kind, length, decimals


def sql_tables(statement: Statement) -> tuple[set[str], set[str]]:
    """The tables an embedded SQL statement reads and writes (upper case, without library)."""
    text = _STRING.sub(" ", statement.factor2)
    verb = text.strip().split(None, 1)[0].upper() if text.strip() else ""
    found = {re.split(r"[./]", m)[-1].upper() for m in _SQL_TABLE.findall(text)}
    if verb in ("INSERT", "UPDATE", "DELETE", "MERGE"):
        target = re.search(r"\b(?:INTO|UPDATE|FROM)\s+([\w#$@./]+)", text, re.I)
        written = {re.split(r"[./]", target.group(1))[-1].upper()} if target else set()
        return found - written, written
    return found, set()
