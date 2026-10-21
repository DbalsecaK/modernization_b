"""The local engine of a COBOL/CICS program (ADR-0056, point 7): the customer's programs compiled by GnuCOBOL, the
CICS services as substitutes of the platform, the VSAM files as GnuCOBOL indexed files. This module is the
deterministic half, pure text and bytes: it translates each program (every `EXEC CICS` becomes standard COBOL or a
call to NXCICS, the file control the program needs is declared from the schema of the suite), lays out the records,
the symbolic maps and the COMMAREAs byte by byte from the pictures, encodes a case into those bytes and decodes what
the program left into an observation. `gnucobol.py` runs it in the sandbox."""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from nexti_adapter_bms.parser import BmsMap, Mapset
from nexti_adapter_cobol.parser import DataItem, Program
from nexti_adapter_cobol.types import expand
from nexti_core.spec.characterization import Call, Case, Observation, Scalar, Schema, Table

ENGINE = "gnucobol-3"
IMAGE = "nexti-sandbox-gnucobol:1"
AREA = 11 * " "  # area B of a fixed-format line, where the translated statements go

# EXEC CICS conditions the programs test through DFHRESP(...), with the number CICS gives each one.
DFHRESP = {
    "NORMAL": 0,
    "ERROR": 1,
    "RDATT": 2,
    "WRBRK": 3,
    "EOF": 4,
    "EODS": 5,
    "EOC": 6,
    "INBFMH": 7,
    "NOSTART": 10,
    "TERMIDERR": 11,
    "FILENOTFOUND": 12,
    "NOTFND": 13,
    "DUPREC": 14,
    "DUPKEY": 15,
    "INVREQ": 16,
    "IOERR": 17,
    "NOSPACE": 18,
    "NOTOPEN": 19,
    "ENDFILE": 20,
    "ILLOGIC": 21,
    "LENGERR": 22,
    "QZERO": 23,
    "SIGNAL": 24,
    "QBUSY": 25,
    "ITEMERR": 26,
    "PGMIDERR": 27,
    "TRANSIDERR": 28,
    "ENDDATA": 29,
    "INVTSREQ": 30,
    "EXPIRED": 31,
    "RETPAGE": 32,
    "RTEFAIL": 33,
    "RTESOME": 34,
    "TSIOERR": 35,
    "MAPFAIL": 36,
    "INVERRTERM": 37,
    "INVMPSZ": 38,
    "IGREQID": 39,
    "OVERFLOW": 40,
    "INVLDC": 41,
    "NOSTG": 42,
    "JIDERR": 43,
    "QIDERR": 44,
    "NOJBUFSP": 45,
    "DSSTAT": 46,
    "SELNERR": 47,
    "FUNCERR": 48,
    "UNEXPIN": 49,
    "NOPASSBKRD": 50,
    "NOPASSBKWR": 51,
    "SYSIDERR": 53,
    "ISCINVREQ": 54,
    "ENQBUSY": 55,
    "ENVDEFERR": 56,
    "IGREQCD": 57,
    "SESSIONERR": 58,
    "SYSBUSY": 59,
    "SESSBUSY": 60,
    "NOTALLOC": 61,
    "CBIDERR": 62,
    "INVEXITREQ": 63,
    "INVPARTNSET": 64,
    "INVPARTN": 65,
    "PARTNFAIL": 66,
    "USERIDERR": 69,
    "NOTAUTH": 70,
    "VOLIDERR": 71,
    "SUPPRESSED": 72,
    "RESIDERR": 75,
    "NOSPOOL": 80,
    "TERMERR": 81,
    "ROLLEDBACK": 82,
    "END": 83,
    "DISABLED": 84,
    "ALLOCERR": 85,
    "STRELERR": 86,
    "OPENERR": 87,
    "SPOLBUSY": 88,
    "SPOLERR": 89,
    "NODEIDERR": 90,
    "TASKIDERR": 91,
    "TCIDERR": 92,
    "DSNNOTFOUND": 93,
    "LOADING": 94,
    "MODELIDERR": 95,
    "OUTDESCRERR": 96,
    "PARTNERIDERR": 97,
    "PROFILEIDERR": 98,
    "NETNAMEIDERR": 99,
    "LOCKED": 100,
    "RECORDBUSY": 101,
    "UOWNOTFOUND": 102,
    "UOWLNOTFOUND": 103,
    "LINKABEND": 104,
    "CHANGED": 105,
    "PROCESSBUSY": 106,
    "ACTIVITYBUSY": 107,
    "PROCESSERR": 108,
    "ACTIVITYERR": 109,
    "CONTAINERERR": 110,
    "EVENTERR": 111,
    "TOKENERR": 112,
    "NOTFINISHED": 113,
    "POOLERR": 114,
    "TIMERERR": 115,
    "SYMBOLERR": 116,
    "TEMPLATERR": 117,
    "NOTSUPERUSER": 118,
    "CSDERR": 119,
    "DUPRES": 120,
    "RESUNAVAIL": 121,
    "CHANNELERR": 122,
    "CCSIDERR": 123,
    "TIMEDOUT": 124,
    "CODEPAGEERR": 125,
    "INCOMPLETE": 126,
    "APPNOTFOUND": 127,
    "BUSY": 128,
}

AID = {"ENTER": "'", "CLEAR": "_", "PA1": "%", "PA2": ">", "PA3": ",", "PF1": "1", "PF2": "2", "PF3": "3", "PF4": "4",
       "PF5": "5", "PF6": "6", "PF7": "7", "PF8": "8", "PF9": "9", "PF10": ":", "PF11": "#", "PF12": "@",
       "PF13": "A", "PF14": "B", "PF15": "C", "PF16": "D", "PF17": "E", "PF18": "F", "PF19": "G", "PF20": "H",
       "PF21": "I", "PF22": "[", "PF23": ".", "PF24": "<"}  # fmt: skip

# The EXEC interface block as DFHEIBLK.cpy lays it out: (name, picture, usage).
EIB_LAYOUT: tuple[tuple[str, str, str], ...] = (
    ("EIBTIME", "S9(7)", "COMP-3"), ("EIBDATE", "S9(7)", "COMP-3"), ("EIBTRNID", "X(4)", "DISPLAY"),
    ("EIBTASKN", "S9(7)", "COMP-3"), ("EIBTRMID", "X(4)", "DISPLAY"), ("DFHEIGDI", "S9(4)", "COMP"),
    ("EIBCPOSN", "S9(4)", "COMP"), ("EIBCALEN", "S9(4)", "COMP"), ("EIBAID", "X(1)", "DISPLAY"),
    ("EIBFN", "X(2)", "DISPLAY"), ("EIBRCODE", "X(6)", "DISPLAY"), ("EIBDS", "X(8)", "DISPLAY"),
    ("EIBREQID", "X(8)", "DISPLAY"), ("EIBRSRCE", "X(8)", "DISPLAY"), ("EIBSYNC", "X(1)", "DISPLAY"),
    ("EIBFREE", "X(1)", "DISPLAY"), ("EIBRECV", "X(1)", "DISPLAY"), ("EIBSEND", "X(1)", "DISPLAY"),
    ("EIBATT", "X(1)", "DISPLAY"), ("EIBEOC", "X(1)", "DISPLAY"), ("EIBFMH", "X(1)", "DISPLAY"),
    ("EIBCOMPL", "X(1)", "DISPLAY"), ("EIBSIG", "X(1)", "DISPLAY"), ("EIBCONF", "X(1)", "DISPLAY"),
    ("EIBERR", "X(1)", "DISPLAY"), ("EIBERRCD", "X(4)", "DISPLAY"), ("EIBSYNRB", "X(1)", "DISPLAY"),
    ("EIBNODAT", "X(1)", "DISPLAY"), ("EIBRESP", "S9(8)", "COMP"), ("EIBRESP2", "S9(8)", "COMP"),
    ("EIBRLDBK", "X(1)", "DISPLAY"),
)  # fmt: skip


class LocalEngineError(ValueError):
    """The program cannot run on the local engine as it is (an EXEC CICS command it does not substitute, a
    copybook or a file layout it lacks): the phase waits with the list, it never guesses."""


# -- pictures as bytes --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Field:
    """One elementary item of a record, a map or a COMMAREA: where it is and how its picture lays its bytes."""

    name: str
    picture: str
    usage: str
    offset: int
    length: int

    @property
    def kind(self) -> str:
        body = expand(self.picture).upper()
        if set(body) <= set("XA") or any(c in body for c in "Z*$,./B+-") or "CR" in body or "DB" in body:
            return "text"
        return {"COMP-3": "packed", "COMP": "binary", "COMP-5": "binary", "BINARY": "binary"}.get(
            self.usage.upper(), "zoned"
        )

    @property
    def signed(self) -> bool:
        return expand(self.picture).upper().startswith("S")

    @property
    def scale(self) -> int:
        body = expand(self.picture).upper()
        return body.partition("V")[2].count("9")

    @property
    def digits(self) -> int:
        return expand(self.picture).upper().count("9")


def byte_length(picture: str | None, usage: str = "DISPLAY") -> int:
    """The bytes an item with this picture takes in storage, as GnuCOBOL lays it out (and the mainframe too)."""
    if not picture:
        return 0
    body = expand(picture).upper()
    use = usage.upper()
    digits = body.count("9")
    if use == "COMP-3":
        return (digits + 2) // 2
    if use in ("COMP", "COMP-5", "BINARY"):
        return 2 if digits <= 4 else 4 if digits <= 9 else 8
    if set(body) <= set("XA"):
        return len(body)
    # DISPLAY numeric or edited: every symbol but V, S and P takes a byte (CR/DB take two, already two symbols).
    return sum(1 for c in body if c not in "VSP")


def _picture_and_usage(declared: str) -> tuple[str, str]:
    """`PIC S9(9)V99 COMP-3` (the schema of a CICS suite) -> ('S9(9)V99', 'COMP-3')."""
    text = declared.strip()
    text = re.sub(r"^(PIC|PICTURE)\s+(IS\s+)?", "", text, flags=re.IGNORECASE)
    parts = text.split()
    picture = parts[0] if parts else "X"
    usage = "DISPLAY"
    for part in parts[1:]:
        upper = part.upper()
        if upper in ("COMP", "COMP-3", "COMP-5", "BINARY", "COMPUTATIONAL", "COMPUTATIONAL-3"):
            usage = {"COMPUTATIONAL": "COMP", "COMPUTATIONAL-3": "COMP-3"}.get(upper, upper)
    return picture, usage


def record_layout(table: Table) -> list[Field]:
    """The fields of a file record from the schema's columns, in order, each at its offset."""
    found: list[Field] = []
    offset = 0
    for column in table.columns:
        picture, usage = _picture_and_usage(column.type)
        length = byte_length(picture, usage)
        found.append(Field(column.name, picture, usage, offset, length))
        offset += length
    return found


def group_layout(items: Sequence[DataItem], root: str) -> list[Field]:
    """The elementary items under a group (a COMMAREA, a record), each at its offset: children by level number,
    OCCURS expanded, REDEFINES sharing the offset of what they redefine, 88 levels skipped."""
    rows = list(items)
    start = next((i for i, it in enumerate(rows) if it.name.upper() == root.upper()), None)
    if start is None:
        return []
    level = rows[start].level
    body = []
    for it in rows[start + 1 :]:
        if it.level <= level or it.level == 1:
            break
        body.append(it)
    return _lay_out(body, 0)[0]


def _lay_out(items: list[DataItem], base: int) -> tuple[list[Field], int]:
    found: list[Field] = []
    offset = base
    starts: dict[str, int] = {}
    i = 0
    while i < len(items):
        it = items[i]
        if it.level == 88:
            i += 1
            continue
        children: list[DataItem] = []
        j = i + 1
        while j < len(items) and items[j].level > it.level:
            children.append(items[j])
            j += 1
        here = starts.get((it.redefines or "").upper(), offset) if it.redefines else offset
        starts[it.name.upper()] = here
        occurs = it.occurs or 1
        if children:
            inner, end = _lay_out(list(children), here)
            size = end - here
            for n in range(occurs):
                shift = n * size
                found += [Field(f.name if occurs == 1 else f"{f.name}({n + 1})", f.picture, f.usage,
                                f.offset + shift, f.length) for f in inner]  # fmt: skip
            size *= occurs
        else:
            size = byte_length(it.picture, it.usage) * occurs
            if it.picture:
                for n in range(occurs):
                    name = it.name if occurs == 1 else f"{it.name}({n + 1})"
                    found.append(Field(name, it.picture, it.usage, here + n * byte_length(it.picture, it.usage),
                                       byte_length(it.picture, it.usage)))  # fmt: skip
        if not it.redefines:
            offset = max(offset, here + size)
        i = j
    return found, offset


def encode(value: Scalar, item: Field) -> bytes:
    """A case value as the bytes of the item, as GnuCOBOL stores it (ASCII, big-endian binary, packed decimal with
    its sign nibble, zoned decimal with the sign in the last byte)."""
    if item.kind == "text":
        text = "" if value is None else str(value)
        return text.encode("latin-1", "replace")[: item.length].ljust(item.length, b" ")
    number = _decimal(value).scaleb(item.scale).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    negative = number < 0
    digits = str(abs(int(number))).rjust(item.digits, "0")[-item.digits :]
    if item.kind == "binary":
        return int(number).to_bytes(item.length, "big", signed=True)
    if item.kind == "packed":
        nibbles = digits.rjust(item.length * 2 - 1, "0") + ("D" if negative else "C" if item.signed else "F")
        return bytes.fromhex(nibbles)
    if negative:  # zoned, GnuCOBOL: the last digit carries the sign as 'p'..'y'
        return (digits[:-1] + chr(ord(digits[-1]) + 0x40)).encode("ascii")
    return digits.encode("ascii")


def decode(data: bytes, item: Field) -> str | None:
    """The bytes of the item as canonical text: text without trailing blanks, numbers with the scale of the
    picture; None when the item is LOW-VALUES (never written)."""
    raw = data[item.offset : item.offset + item.length]
    if not raw or not raw.strip(b"\x00"):
        return None if item.kind == "text" else _scaled(0, item.scale)
    if item.kind == "text":
        return raw.decode("latin-1").rstrip(" ")
    if item.kind == "binary":
        return _scaled(int.from_bytes(raw, "big", signed=True), item.scale)
    if item.kind == "packed":
        nibbles = raw.hex().upper()
        sign = -1 if nibbles[-1] == "D" else 1
        return _scaled(sign * int(nibbles[:-1] or "0"), item.scale)
    text = raw.decode("latin-1")
    sign = 1
    last = text[-1]
    if "p" <= last <= "y":
        sign, text = -1, text[:-1] + chr(ord(last) - 0x40)
    elif last == "{" or last == "}":
        sign, text = (1 if last == "{" else -1), text[:-1] + "0"
    cleaned = "".join(c for c in text if c.isdigit()) or "0"
    return _scaled(sign * int(cleaned), item.scale)


def _decimal(value: Scalar) -> Decimal:
    if value is None or value == "":
        return Decimal(0)
    if isinstance(value, bool):
        return Decimal(int(value))
    try:
        return Decimal(str(value).strip())
    except InvalidOperation:
        return Decimal(0)


def _scaled(units: int, scale: int) -> str:
    return str(Decimal(units).scaleb(-scale)) if scale else str(units)


def encode_record(row: Mapping[str, Scalar], layout: Sequence[Field]) -> bytes:
    values = {k.upper(): v for k, v in row.items()}
    out = bytearray(b" " * (max((f.offset + f.length for f in layout), default=0)))
    for item in layout:
        out[item.offset : item.offset + item.length] = encode(values.get(item.name.upper()), item)
    return bytes(out)


def decode_record(data: bytes, layout: Sequence[Field]) -> dict[str, str | None]:
    return {item.name: decode(data, item) for item in layout}


# -- symbolic maps -------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class MapField:
    name: str
    offset: int  # of the L (length) half-word; F follows, then the data (I/O) at offset + 3
    length: int

    @property
    def data_offset(self) -> int:
        return self.offset + 3


def symbolic_layout(bms_map: BmsMap) -> list[MapField]:
    """The named fields of a map as DFHMSD lays the symbolic map out: TIOAPFX (12 bytes), then per field the
    length (COMP S9(4)), the flag/attribute byte and the data."""
    found = []
    offset = 12
    for bms_field in bms_map.fields:
        if not bms_field.label:
            continue
        found.append(MapField(bms_field.label.upper(), offset, bms_field.length))
        offset += 3 + bms_field.length
    return found


def symbolic_copybook(mapset: Mapset) -> str:
    """The symbolic map copybook of a mapset, as DFHMSD generates it for COBOL (the `I` and `O` groups), when the
    inputs carry the BMS source and not the copybook."""
    lines = [f"      * {mapset.name} - symbolic map generated by the platform from the BMS source (ADR-0056)"]
    for bms_map in mapset.maps:
        name = bms_map.name.upper()
        lines += [f"       01  {name}I.", "           05  FILLER                 PIC X(12)."]
        for item in symbolic_layout(bms_map):
            lines += [f"           05  {item.name}L".ljust(38) + "PIC S9(4) COMP.",
                      f"           05  {item.name}F".ljust(38) + "PIC X.",
                      f"           05  {item.name}I".ljust(38) + f"PIC X({item.length})."]  # fmt: skip
        lines += [f"       01  {name}O REDEFINES {name}I.", "           05  FILLER                 PIC X(12)."]
        for item in symbolic_layout(bms_map):
            lines += ["           05  FILLER                 PIC X(3).",
                      f"           05  {item.name}O".ljust(38) + f"PIC X({item.length})."]  # fmt: skip
    return "\n".join(lines) + "\n"


def map_input(bms_map: BmsMap, inputs: Mapping[str, Scalar]) -> bytes:
    """The symbolic map a RECEIVE MAP fills, from the inputs of the case (field label -> value): the length of
    each value in its L, the data in its I, LOW-VALUES where the case says nothing."""
    layout = symbolic_layout(bms_map)
    size = 12 + sum(3 + f.length for f in layout)
    out = bytearray(size)
    given = {k.upper(): v for k, v in inputs.items()}
    pictures = {f.label.upper(): f.picin for f in bms_map.fields if f.label}
    for item in layout:
        if item.name not in given or given[item.name] is None:
            continue
        text = _typed(given[item.name], pictures.get(item.name, "")).encode("latin-1", "replace")[: item.length]
        out[item.offset : item.offset + 2] = len(text).to_bytes(2, "big")
        out[item.data_offset : item.data_offset + item.length] = text.ljust(item.length, b" ")
    return bytes(out)


def _typed(value: Scalar, picin: str) -> str:
    """The value as the operator types it in a field with that PICIN: a numeric picture with an implied decimal
    point (`9(9)V99`) takes the digits without the point, scaled, as the terminal sends them."""
    body = expand(picin).upper() if picin else ""
    if body and set(body) <= set("9VS") and "V" in body:
        scale = body.partition("V")[2].count("9")
        number = _decimal(value).scaleb(scale).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        return str(abs(int(number)))
    return str(value)


def output_layout(bms_map: BmsMap) -> list[dict[str, Any]]:
    """What the helper needs to read a sent map: the data offset and length of every named field."""
    return [{"name": f.name, "offset": f.data_offset, "length": f.length} for f in symbolic_layout(bms_map)]


# -- the translation of EXEC CICS ---------------------------------------------------------------------------------
_EXEC_SQL = re.compile(r"[ \t]*EXEC\s+SQL\s+(?P<body>.*?)\s*END-EXEC(?P<period>\.?)", re.IGNORECASE | re.DOTALL)
_EXEC_CICS = re.compile(r"[ \t]*EXEC\s+CICS\s+(?P<body>.*?)\s*END-EXEC(?P<period>\.?)", re.IGNORECASE | re.DOTALL)
_DFHRESP = re.compile(r"DFHRESP\s*\(\s*([A-Z0-9]+)\s*\)", re.IGNORECASE)
_DIVISION = re.compile(
    r"^(.{7})(IDENTIFICATION|ID|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b(.*)$", re.IGNORECASE | re.MULTILINE
)
_SECTION = re.compile(
    r"^(.{7})(WORKING-STORAGE|LINKAGE|FILE|INPUT-OUTPUT)\s+SECTION\s*\.", re.IGNORECASE | re.MULTILINE
)


# Options whose argument may come without parentheses: a literal, a name or `LENGTH OF name`.
_BARE_ARGUMENTS = frozenset({"TRANSID", "COMMAREA", "LENGTH", "PROGRAM", "MAPSET", "MAP", "FROM", "INTO", "QUEUE"})
_BARE_ARGUMENT = re.compile(r"\s+('[^']*'|\"[^\"]*\"|LENGTH\s+OF\s+[A-Z0-9-]+|[A-Z0-9][A-Z0-9-]*)", re.IGNORECASE)


def _parse_exec(body: str) -> tuple[str, dict[str, str], list[str]]:
    """(command words, options with an argument, options without one) of the text between EXEC CICS and END-EXEC;
    the arguments keep their text (`LENGTH OF X` included, parentheses balanced)."""
    words: list[str] = []
    options: dict[str, str] = {}
    flags: list[str] = []
    i = 0
    text = " ".join(body.split())
    while i < len(text):
        m = re.match(r"([A-Z0-9-]+)", text[i:], re.IGNORECASE)
        if not m:
            i += 1
            continue
        word = m.group(1).upper()
        i += m.end()
        if i < len(text) and text[i] == "(":
            depth, j = 0, i
            while j < len(text):
                depth += text[j] == "("
                depth -= text[j] == ")"
                j += 1
                if depth == 0:
                    break
            options[word] = text[i + 1 : j - 1].strip()
            i = j
        elif word in _BARE_ARGUMENTS and words and (bare := _BARE_ARGUMENT.match(text, i)):
            # The estate writes `RETURN TRANSID I002 COMMAREA REG LENGTH LENGTH OF REG` without parentheses.
            options[word] = bare.group(1)
            i = bare.end()
        elif not options and not flags:
            words.append(word)
        else:
            flags.append(word)
    return " ".join(words), options, flags


def _wrapped(code: str, width: int = 72 - len(AREA)) -> list[str]:
    """A generated statement in lines that fit the fixed format (columns 12-72): broken at blanks outside the
    quotes, the continuation lines indented four more."""
    if len(code) <= width:
        return [code]
    parts: list[str] = []
    rest = code
    first = True
    while len(rest) > (width if first else width - 4):
        limit = width if first else width - 4
        cut = -1
        quoted = False
        for i, char in enumerate(rest[:limit]):
            if char == "'":
                quoted = not quoted
            elif char == " " and not quoted:
                cut = i
        if cut <= 0:
            break
        parts.append(rest[:cut] if first else "    " + rest[:cut])
        rest = rest[cut + 1 :]
        first = False
    parts.append(rest if first else "    " + rest)
    return parts


def _literal(value: str | None) -> str:
    if value is None:
        return ""
    return value[1:-1] if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0] else value


def _lit8(text: str) -> str:
    return "'" + text.upper()[:8].ljust(8) + "'"


@dataclass
class Translation:
    text: str
    files: dict[str, tuple[int, int]] = field(default_factory=dict)  # file -> (record length, key length)
    unsupported: list[str] = field(default_factory=list)
    linked: list[str] = field(default_factory=list)  # programs called by LINK/XCTL
    maps: list[str] = field(default_factory=list)
    sql: bool = False  # the program embeds EXEC SQL: it runs against the PostgreSQL of the sandbox


def translate(program: Program, text: str, schema: Schema, local_programs: set[str], *, main: bool) -> Translation:
    """The program as GnuCOBOL compiles it: EXEC CICS commands replaced, the EIB and the COMMAREA received from the
    driver, the files of the schema declared and opened. `main` says the program is the task's entry (its RETURN
    ends the task and is logged); a linked program's RETURN goes back to its caller."""
    files = {t.name.upper(): t for t in schema.tables}
    found = Translation(text="")
    used: dict[str, tuple[int, int]] = {}
    found.sql = bool(_EXEC_SQL.search(text))

    def file_of(name: str) -> str:
        table = files.get(name.upper())
        if table is None:
            found.unsupported.append(f"FILE('{name}') is not a table of the suite's schema")
            return name.upper()
        layout = record_layout(table)
        keys = {k.upper() for k in table.key}
        key_length = sum(f.length for f in layout if f.name.upper() in keys)
        used[name.upper()] = (sum(f.length for f in layout), key_length or layout[0].length if layout else 0)
        return name.upper()

    def replacement(match: re.Match[str]) -> str:
        command, options, flags = _parse_exec(match.group("body"))
        period = match.group("period")
        lines = _translate_command(command, options, flags, file_of, local_programs, main, found)
        if lines is None:
            found.unsupported.append(f"EXEC CICS {command}")
            lines = ["CONTINUE"]
        out = "\n".join(AREA + part for line in lines for part in _wrapped(line))
        return out + period

    def sql_replacement(match: re.Match[str]) -> str:
        from nexti_adapter_cobol.sql import rewrite_sql

        rewritten = rewrite_sql(match.group("body"), list(files))
        period = match.group("period")
        if rewritten is None:  # a DECLARE TABLE only documents the table: a comment keeps the line count honest
            return "      * EXEC SQL DECLARE TABLE: table in PostgreSQL (NX)"
        return "\n".join(AREA + part for part in _wrapped(f"EXEC SQL {rewritten} END-EXEC")) + period

    body = _EXEC_CICS.sub(replacement, text)
    body = _DFHRESP.sub(lambda m: str(DFHRESP.get(m.group(1).upper(), 1)), body)
    if found.sql:
        body = _EXEC_SQL.sub(sql_replacement, body)
    found.files = used
    found.text = _with_environment(body, program, used, sql=found.sql, main=main)
    return found


def _translate_command(
    command: str, options: dict[str, str], flags: list[str], file_of: Any, local_programs: set[str], main: bool,
    found: Translation,
) -> list[str] | None:  # fmt: skip
    resp = options.get("RESP")
    after_resp = [f"MOVE EIBRESP TO {resp}"] if resp else []
    if command == "READ":
        name = file_of(_literal(options.get("FILE") or options.get("DATASET")))
        into = options.get("INTO")
        key = options.get("RIDFLD", "")
        read = [f"MOVE {key} TO NX-F-{name}-KEY", f"READ NX-F-{name}" + (f" INTO {into}" if into else ""),
                "    INVALID KEY MOVE 13 TO EIBRESP", "    NOT INVALID KEY MOVE 0 TO EIBRESP", "END-READ"]  # fmt: skip
        return read + after_resp
    if command in ("REWRITE", "WRITE"):
        name = file_of(_literal(options.get("FILE") or options.get("DATASET")))
        source = options.get("FROM", "")
        bad = 13 if command == "REWRITE" else 14
        verb = f"REWRITE NX-F-{name}-REC" if command == "REWRITE" else f"WRITE NX-F-{name}-REC"
        return [f"MOVE {source} TO NX-F-{name}-REC", verb, f"    INVALID KEY MOVE {bad} TO EIBRESP",
                "    NOT INVALID KEY MOVE 0 TO EIBRESP", f"END-{command}",
                f"MOVE LENGTH OF NX-F-{name}-REC TO NX-LEN",
                f"CALL 'NXCICS' USING 'FILEOP  ' '{name}:{command}' NX-F-{name}-REC NX-LEN", *after_resp]  # fmt: skip
    if command == "DELETE" and ("FILE" in options or "DATASET" in options):
        name = file_of(_literal(options.get("FILE") or options.get("DATASET")))
        rid = options.get("RIDFLD")
        move = [f"MOVE {rid} TO NX-F-{name}-KEY"] if rid else []
        return [*move, f"DELETE NX-F-{name} RECORD", "    INVALID KEY MOVE 13 TO EIBRESP",
                "    NOT INVALID KEY MOVE 0 TO EIBRESP", "END-DELETE",
                f"MOVE LENGTH OF NX-F-{name}-REC TO NX-LEN",
                f"CALL 'NXCICS' USING 'FILEOP  ' '{name}:DELETE' NX-F-{name}-REC NX-LEN", *after_resp]  # fmt: skip
    if command == "RECEIVE MAP" or (command == "RECEIVE" and "MAP" in options):
        map_name = _literal(options.get("MAP"))
        area = options.get("INTO") or f"{map_name}I"
        found.maps.append(map_name.upper())
        return [f"MOVE LENGTH OF {area} TO NX-LEN",
                f"CALL 'NXCICS' USING 'RECEIVE ' {_lit8(map_name)} {area} NX-LEN",
                "MOVE 0 TO EIBRESP", *after_resp]  # fmt: skip
    if command == "SEND MAP" or (command == "SEND" and "MAP" in options):
        map_name = _literal(options.get("MAP"))
        area = options.get("FROM") or f"{map_name}O"
        found.maps.append(map_name.upper())
        return [f"MOVE LENGTH OF {area} TO NX-LEN",
                f"CALL 'NXCICS' USING 'SEND    ' {_lit8(map_name)} {area} NX-LEN",
                "MOVE 0 TO EIBRESP", *after_resp]  # fmt: skip
    if command == "SEND TEXT" or (command == "SEND" and "TEXT" in flags):
        area = options.get("FROM", "NX-NAME")
        length = options.get("LENGTH", f"LENGTH OF {area}")
        return [f"MOVE {length} TO NX-LEN", f"CALL 'NXCICS' USING 'TEXT    ' '-' {area} NX-LEN", "MOVE 0 TO EIBRESP"]
    if command in ("SEND CONTROL", "SEND PAGE", "HANDLE AID", "HANDLE CONDITION", "HANDLE ABEND", "IGNORE CONDITION",
                   "ISSUE ERASEAUP", "PUSH HANDLE", "POP HANDLE", "FREEMAIN", "ADDRESS", "ENDBR", "UNLOCK",
                   "FREEMAIN DATA"):  # fmt: skip
        return ["CONTINUE"]
    if command == "LINK":
        target = _literal(options.get("PROGRAM")).upper()
        area = options.get("COMMAREA", "NX-NAME")
        length = options.get("LENGTH", f"LENGTH OF {area}" if "COMMAREA" in options else "0")
        found.linked.append(target)
        if target in local_programs:
            return [
                f"MOVE {length} TO EIBCALEN",
                f"CALL '{target}' USING DFHEIBLK {area}",
                "MOVE 0 TO EIBRESP",
                *after_resp,
            ]
        return [f"MOVE {length} TO NX-LEN", f"CALL 'NXCICS' USING 'LINK    ' {_lit8(target)} {area} NX-LEN",
                "MOVE 0 TO EIBRESP", *after_resp]  # fmt: skip
    if command == "XCTL":
        target = _literal(options.get("PROGRAM")).upper()
        area = options.get("COMMAREA", "NX-NAME")
        length = options.get("LENGTH", f"LENGTH OF {area}" if "COMMAREA" in options else "0")
        found.linked.append(target)
        return [f"MOVE {length} TO NX-LEN", f"CALL 'NXCICS' USING 'XCTL    ' {_lit8(target)} {area} NX-LEN"]
    if command == "RETURN":
        if not main:
            return ["GOBACK"]
        transid = _literal(options.get("TRANSID")) or "-"
        area = options.get("COMMAREA", "NX-NAME")
        length = options.get("LENGTH", f"LENGTH OF {area}" if "COMMAREA" in options else "0")
        commit = ["EXEC SQL COMMIT WORK END-EXEC"] if found.sql else []  # the task ends: its work is confirmed
        return [*commit, f"MOVE {length} TO NX-LEN", f"CALL 'NXCICS' USING 'RETURN  ' {_lit8(transid)} {area} NX-LEN",
                "GOBACK"]  # fmt: skip
    if command in ("SYNCPOINT", "SYNCPOINT ROLLBACK"):
        kind = "ROLLBACK" if "ROLLBACK" in command or "ROLLBACK" in flags else "COMMIT"
        sql = [f"EXEC SQL {kind} WORK END-EXEC"] if found.sql else []
        return [*sql, "MOVE 0 TO NX-LEN", f"CALL 'NXCICS' USING 'SYNC    ' '{kind}' NX-NAME NX-LEN"]
    if command == "ASSIGN":
        lines = []
        for what, target in options.items():
            lines += [f"MOVE LENGTH OF {target} TO NX-LEN", f"CALL 'NXCICS' USING 'ASSIGN  ' '{what}' {target} NX-LEN"]
        return lines or ["CONTINUE"]
    if command == "ASKTIME":
        abstime = options.get("ABSTIME")
        return [f"MOVE 0 TO {abstime}"] if abstime else ["CONTINUE"]
    if command == "FORMATTIME":
        lines = []
        for what, target in options.items():
            if what in ("ABSTIME", "DATESEP", "TIMESEP"):
                continue
            lines += [f"MOVE LENGTH OF {target} TO NX-LEN", f"CALL 'NXCICS' USING 'ASSIGN  ' '{what}' {target} NX-LEN"]
        return lines or ["CONTINUE"]
    if command == "GETMAIN":
        pointer = options.get("SET")
        length = options.get("LENGTH") or options.get("FLENGTH") or "0"
        if pointer and pointer.upper().startswith("ADDRESS OF"):
            pointer = pointer[len("ADDRESS OF") :].strip()
            return [f"MOVE {length} TO NX-LEN", "CALL 'CBL_ALLOC_MEM' USING NX-POINTER BY VALUE NX-LEN BY VALUE 0",
                    f"SET ADDRESS OF {pointer} TO NX-POINTER"]  # fmt: skip
        return [f"MOVE {length} TO NX-LEN", f"CALL 'CBL_ALLOC_MEM' USING {pointer} BY VALUE NX-LEN BY VALUE 0"]
    if command == "ABEND":
        code = _literal(options.get("ABCODE")) or "NXAB"
        return ["MOVE 0 TO NX-LEN", f"CALL 'NXCICS' USING 'ABEND   ' '{code}' NX-NAME NX-LEN"]
    return None


def _with_environment(
    body: str, program: Program, files: Mapping[str, tuple[int, int]], *, sql: bool = False, main: bool = False
) -> str:
    """The declarations the translated program needs: the files it uses, the working items of the substitutes,
    the EIB and the COMMAREA in LINKAGE, the PROCEDURE DIVISION receiving them and the files opened at the start."""
    lines = body.split("\n")
    work = [
        "       01  NX-LEN                 PIC S9(8) COMP-5 VALUE 0.",
        "       01  NX-NAME                PIC X(32) VALUE SPACES.",
        "       01  NX-POINTER             USAGE POINTER.",
    ] + [f"       01  NX-FS-{name:<16} PIC XX VALUE '00'." for name in files]
    selects = [
        line
        for name in files
        for line in (
            f"           SELECT NX-F-{name} ASSIGN TO '/work/case/{name}.idx'",
            "               ORGANIZATION IS INDEXED ACCESS MODE IS DYNAMIC",
            f"               RECORD KEY IS NX-F-{name}-KEY",
            f"               FILE STATUS IS NX-FS-{name}.",
        )
    ]
    fds = [
        line
        for name, (length, key) in files.items()
        for line in (
            f"       FD  NX-F-{name}.",
            f"       01  NX-F-{name}-REC.",
            f"           05  NX-F-{name}-KEY".ljust(38) + f"PIC X({key}).",
            "           05  FILLER".ljust(38) + f"PIC X({max(length - key, 1)}).",
        )
    ]
    opens = [f"           OPEN I-O NX-F-{name}." for name in files]
    if sql:
        work += [
            "       01  NX-DB-NAME             PIC X(30)",
            "                               VALUE 'nexti@localhost:5432'.",
            "       01  NX-DB-USER             PIC X(30) VALUE 'nexti'.",
            "       01  NX-DB-PASS             PIC X(30) VALUE SPACE.",
        ]
        if "INCLUDE SQLCA" not in body.upper():
            work.append("           EXEC SQL INCLUDE SQLCA END-EXEC.")
        if main:  # one connection per task, opened by the program that starts it (ADR-0056, point 7)
            opens = [
                "           EXEC SQL CONNECT :NX-DB-USER IDENTIFIED BY :NX-DB-PASS",
                "                USING :NX-DB-NAME END-EXEC.",
                *opens,
            ]
    out: list[str] = []
    seen_env = seen_data = seen_ws = seen_linkage = seen_proc = False
    has_commarea = any(it.name.upper() == "DFHCOMMAREA" for it in program.data)
    i = 0
    while i < len(lines):
        line = lines[i]
        division = _DIVISION.match(line)
        section = _SECTION.match(line)
        if division and division.group(2).upper() == "ENVIRONMENT":
            seen_env = True
            out.append(line)
            if files:
                out += ["       INPUT-OUTPUT SECTION.", "       FILE-CONTROL.", *selects]
            i += 1
            continue
        if division and division.group(2).upper() == "DATA":
            if files and not seen_env:
                out += [
                    "       ENVIRONMENT DIVISION.",
                    "       INPUT-OUTPUT SECTION.",
                    "       FILE-CONTROL.",
                    *selects,
                ]
            seen_data = True
            out.append(line)
            if files:
                out += ["       FILE SECTION.", *fds]
            i += 1
            continue
        if section and section.group(2).upper() == "WORKING-STORAGE":
            seen_ws = True
            out.append(line)
            out += work
            i += 1
            continue
        if section and section.group(2).upper() == "LINKAGE":
            seen_linkage = True
            out.append(line)
            out += ["       01  DFHEIBLK.", "           COPY DFHEIBLK."]
            if not has_commarea:
                out.append("       01  DFHCOMMAREA            PIC X(32767).")
            i += 1
            continue
        if division and division.group(2).upper() == "PROCEDURE":
            if not seen_ws:
                out += ["       WORKING-STORAGE SECTION.", *work]
            if not seen_linkage:
                out += ["       LINKAGE SECTION.", "       01  DFHEIBLK.", "           COPY DFHEIBLK.",
                        "       01  DFHCOMMAREA            PIC X(32767)."]  # fmt: skip
            seen_proc = True
            out.append("       PROCEDURE DIVISION USING DFHEIBLK DFHCOMMAREA.")
            if opens:
                out += ["       NX-0000-OPEN-FILES.", *opens]
            i += 1
            continue
        out.append(line)
        i += 1
    if not seen_data or not seen_proc:
        raise LocalEngineError(f"{program.name}: the program has no DATA or PROCEDURE DIVISION the translator can find")
    return "\n".join(out)


# -- the generated programs of the run ------------------------------------------------------------------------------
def driver_source(main_program: str) -> str:
    """NXMAIN: reads the EIB and the COMMAREA of the case and calls the program as CICS would."""
    return (
        "\n".join(
            [
                "       IDENTIFICATION DIVISION.",
                "       PROGRAM-ID. NXMAIN.",
                "       DATA DIVISION.",
                "       WORKING-STORAGE SECTION.",
                "       01  NX-EIB.",
                "           COPY DFHEIBLK.",
                "       01  NX-COMMAREA            PIC X(32767) VALUE LOW-VALUES.",
                "       01  NX-NAME                PIC X(256).",
                "       01  NX-HANDLE              PIC X(4).",
                "       01  NX-OFFSET              PIC X(8) VALUE LOW-VALUES.",
                "       01  NX-COUNT               PIC X(4) COMP-X.",
                "       01  NX-FLAGS               PIC X VALUE LOW-VALUE.",
                "       01  NX-ZERO                PIC X VALUE LOW-VALUE.",
                "       01  NX-MODE                PIC X VALUE X'01'.",
                "       01  NX-RC                  PIC S9(8) COMP-5.",
                "       PROCEDURE DIVISION.",
                "       0000-MAIN.",
                "           MOVE '/work/case/eib.bin' TO NX-NAME",
                "           INSPECT NX-NAME REPLACING ALL SPACE BY X'00'",
                "           CALL 'CBL_OPEN_FILE' USING NX-NAME NX-MODE NX-FLAGS NX-ZERO",
                "                                      NX-HANDLE RETURNING NX-RC",
                "           IF NX-RC = 0",
                f"              MOVE {eib_length()} TO NX-COUNT",
                "              CALL 'CBL_READ_FILE' USING NX-HANDLE NX-OFFSET NX-COUNT",
                "                                         NX-ZERO NX-EIB",
                "              CALL 'CBL_CLOSE_FILE' USING NX-HANDLE",
                "           END-IF",
                "           MOVE '/work/case/commarea.bin' TO NX-NAME",
                "           INSPECT NX-NAME REPLACING ALL SPACE BY X'00'",
                "           CALL 'CBL_OPEN_FILE' USING NX-NAME NX-MODE NX-FLAGS NX-ZERO",
                "                                      NX-HANDLE RETURNING NX-RC",
                "           IF NX-RC = 0 AND EIBCALEN OF NX-EIB > 0",
                "              MOVE EIBCALEN OF NX-EIB TO NX-COUNT",
                "              CALL 'CBL_READ_FILE' USING NX-HANDLE NX-OFFSET NX-COUNT",
                "                                         NX-ZERO NX-COMMAREA",
                "              CALL 'CBL_CLOSE_FILE' USING NX-HANDLE",
                "           END-IF",
                f"           CALL '{main_program.upper()}' USING NX-EIB NX-COMMAREA",
                "           STOP RUN.",
            ]
        )
        + "\n"
    )


def eib_layout() -> list[Field]:
    found = []
    offset = 0
    for name, picture, usage in EIB_LAYOUT:
        length = byte_length(picture, usage)
        found.append(Field(name, picture, usage, offset, length))
        offset += length
    return found


def eib_length() -> int:
    return sum(f.length for f in eib_layout())


def eib_bytes(transid: str, aid: str, commarea_length: int, date: int = 0, time: int = 0) -> bytes:
    values: dict[str, Scalar] = {"EIBTRNID": transid[:4], "EIBAID": AID.get(aid.upper(), aid[:1] if aid else "'"),
                                 "EIBCALEN": commarea_length, "EIBDATE": date, "EIBTIME": time, "EIBTASKN": 1,
                                 "EIBTRMID": "NX01"}  # fmt: skip
    return encode_record(values, eib_layout())


def loader_source(name: str, length: int, key: int) -> str:
    """NXLOAD_<FILE>: the rows of the case (fixed records in <FILE>.seq) into the indexed file the program opens."""
    return _file_program(f"NXLD{name[:4]}", name, length, key, load=True)


def dumper_source(name: str, length: int, key: int) -> str:
    """NXDUMP_<FILE>: the indexed file after the case as fixed records (<FILE>.dump), key order."""
    return _file_program(f"NXDP{name[:4]}", name, length, key, load=False)


def _file_program(program: str, name: str, length: int, key: int, load: bool) -> str:
    seq, idx = f"/work/case/{name}.seq", f"/work/case/{name}.idx"
    dump = f"/work/case/{name}.dump"
    lines = [
        "       IDENTIFICATION DIVISION.",
        f"       PROGRAM-ID. {program}.",
        "       ENVIRONMENT DIVISION.",
        "       INPUT-OUTPUT SECTION.",
        "       FILE-CONTROL.",
        f"           SELECT NX-SEQ ASSIGN TO '{seq if load else dump}'",
        "               ORGANIZATION IS SEQUENTIAL FILE STATUS IS NX-FS-SEQ.",
        f"           SELECT NX-IDX ASSIGN TO '{idx}'",
        "               ORGANIZATION IS INDEXED ACCESS MODE IS DYNAMIC",
        "               RECORD KEY IS NX-IDX-KEY",
        "               FILE STATUS IS NX-FS-IDX.",
        "       DATA DIVISION.",
        "       FILE SECTION.",
        "       FD  NX-SEQ.",
        f"       01  NX-SEQ-REC             PIC X({length}).",
        "       FD  NX-IDX.",
        "       01  NX-IDX-REC.",
        f"           05  NX-IDX-KEY             PIC X({key}).",
        f"           05  FILLER                 PIC X({max(length - key, 1)}).",
        "       WORKING-STORAGE SECTION.",
        "       01  NX-FS-SEQ              PIC XX.",
        "       01  NX-FS-IDX              PIC XX.",
        "       01  NX-EOF                 PIC X VALUE 'N'.",
        "       PROCEDURE DIVISION.",
        "       0000-MAIN.",
    ]
    if load:
        lines += [
            "           OPEN INPUT NX-SEQ",
            "           OPEN OUTPUT NX-IDX",
            "           PERFORM UNTIL NX-EOF = 'Y'",
            "              READ NX-SEQ",
            "                 AT END MOVE 'Y' TO NX-EOF",
            "                 NOT AT END",
            "                    MOVE NX-SEQ-REC TO NX-IDX-REC",
            "                    WRITE NX-IDX-REC",
            "              END-READ",
            "           END-PERFORM",
        ]
    else:
        lines += [
            "           OPEN INPUT NX-IDX",
            "           OPEN OUTPUT NX-SEQ",
            "           PERFORM UNTIL NX-EOF = 'Y'",
            "              READ NX-IDX NEXT RECORD",
            "                 AT END MOVE 'Y' TO NX-EOF",
            "                 NOT AT END",
            "                    MOVE NX-IDX-REC TO NX-SEQ-REC",
            "                    WRITE NX-SEQ-REC",
            "              END-READ",
            "           END-PERFORM",
        ]
    lines += ["           CLOSE NX-SEQ NX-IDX", "           STOP RUN."]
    return "\n".join(lines) + "\n"


# -- a case as bytes, and what the program left as an observation --------------------------------------------------
@dataclass(frozen=True)
class CasePlan:
    """What the sandbox needs for one case: the files the program opens, the EIB, the COMMAREA, the maps and the
    answers of the substitutes, all as bytes; the layouts the helper reads the sent maps with."""

    name: str
    files: dict[str, bytes]  # <FILE>.seq
    eib: bytes
    commarea: bytes
    case_json: str


def case_plan(
    case: Case, schema: Schema, maps: Mapping[str, BmsMap], transid: str, commarea_layouts: Mapping[str, list[Field]],
    aid: str = "ENTER", commarea: bytes = b"", commarea_length: int = 0,
) -> CasePlan:  # fmt: skip
    """The case as the sandbox receives it. The inputs of the case fill the map the program receives (every named
    field it knows); `COMMAREA`, `AID`, `TRANSID`, `USERID` inputs (when present) set the task's context. The
    substitutes' answers (`outputs` by field of the COMMAREA the caller passes) become byte patches."""
    inputs = {k.upper(): v for k, v in case.inputs.items()}
    files: dict[str, bytes] = {}
    for table in schema.tables:
        layout = record_layout(table)
        rows = next((r for n, r in case.setup.items() if n.upper() == table.name.upper()), [])
        files[f"{table.name.upper()}.seq"] = b"".join(encode_record(row, layout) for row in rows)
    aid = str(inputs.pop("AID", aid))
    transid = str(inputs.pop("TRANSID", transid))
    given = inputs.pop("COMMAREA", None)
    if given is not None:
        commarea = str(given).encode("latin-1")
    elif inputs and commarea_length > 0:
        # A pseudo-conversational task that receives a map comes with the COMMAREA of its previous RETURN (its
        # length is what the program tests first); the case gives the map, so the task is that continuation.
        commarea = b"\x00" * commarea_length
    map_bytes = {name: map_input(bms_map, inputs).hex() for name, bms_map in maps.items()}
    layouts = {name: output_layout(bms_map) for name, bms_map in maps.items()}
    stubs: dict[str, list[dict[str, Any]]] = {}
    for program, answers in case.stubs.items():
        layout = commarea_layouts.get(program.upper(), [])
        by_name = {f.name.upper().replace("-", "_"): f for f in layout}
        stubs[program.upper()] = [
            {"returns": a.returns, "patches": [
                {"offset": by_name[k.upper().replace("-", "_")].offset,
                 "hex": encode(v, by_name[k.upper().replace("-", "_")]).hex()}
                for k, v in a.outputs.items() if k.upper().replace("-", "_") in by_name
            ]}
            for a in answers
        ]  # fmt: skip
    assign = {"USERID": str(inputs.pop("USERID", "NXUSER")), "APPLID": "NXCICS", "SYSID": "NX01",
              "YYYYMMDD": "20260101", "YYMMDD": "260101", "DDMMYY": "010126", "DDMMYYYY": "01012026",
              "MMDDYY": "010126", "TIME": "120000"}  # fmt: skip
    plan = {"maps": map_bytes, "layouts": layouts, "stubs": stubs, "assign": assign}
    return CasePlan(case.name, files, eib_bytes(transid, aid, len(commarea)), commarea,
                    json.dumps(plan, ensure_ascii=False))  # fmt: skip


def observe(
    output: str,
    schema: Schema,
    case: Case,
    commarea_layouts: Mapping[str, list[Field]],
    files: Sequence[str] | None = None,
) -> Observation:
    """What the program did, from the lines the sandbox printed for the case: the sent map fields as outputs, the
    calls to substitutes, the RETURN, the files after the task (a rollback undoes the writes since the last
    syncpoint: the writes are replayed on the rows of the case), and an abend as a failure."""
    outputs: dict[str, str | None] = {}
    calls: list[Call] = []
    undone: list[Call] = []
    messages: list[str] = []
    writes: list[tuple[str, str, bytes]] = []
    rolled_back = False
    pending_calls: list[Call] = []
    returns: int | None = 0
    dumps: dict[str, bytes] = {}
    error: str | None = None
    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith("NXO|"):
            _, name, value = line.split("|", 2)
            outputs[name] = value if value != "" else None
        elif line.startswith("NXC|") or line.startswith("NXX|"):
            _, program, data = line.split("|", 2)
            layout = commarea_layouts.get(program.upper(), [])
            arguments = {f.name.upper().replace("-", "_"): decode(bytes.fromhex(data), f) for f in layout}
            pending_calls.append(Call(program=program, arguments=arguments))
        elif line.startswith("NXR|"):
            pass  # the RETURN closes the task; its transid and COMMAREA are the next task's business
        elif line.startswith("NXS|"):
            if line.endswith("ROLLBACK"):
                writes = [w for w in writes if w[0] == "committed"]
                undone += pending_calls
                pending_calls = []
                rolled_back = True
            else:
                writes = [("committed", op, data) for _, op, data in writes]
                calls += pending_calls
                pending_calls = []
        elif line.startswith("NXW|"):
            _, file_name, op, data = line.split("|", 3)
            writes.append((file_name.upper(), op.upper(), bytes.fromhex(data)))
        elif line.startswith("NXA|"):
            messages.append(f"ABEND {line[4:]}")
            returns = -1
        elif line.startswith("NXU|"):
            error = f"the local engine does not substitute {line[4:]}"
        elif line.startswith("NXF|"):
            import base64

            _, file_name, blob = line.split("|", 2)
            dumps[file_name.upper()] = base64.b64decode(blob) if blob else b""
        elif line.startswith("NXERR|"):
            error = line[6:]
    calls += pending_calls
    from nexti_adapter_cobol.sql import parse_dump

    # `files` names the tables reached as files (the runner knows them); None, from older callers, means all of them
    as_files = {f.upper() for f in files} if files is not None else {t.name.upper() for t in schema.tables}
    sql_tables = parse_dump(output, schema)
    tables: dict[str, list[dict[str, str | None]]] = {}
    for table in schema.tables:
        if table.name.upper() not in as_files:
            tables[table.name] = sql_tables.get(table.name, [])
            continue
        layout = record_layout(table)
        length = sum(f.length for f in layout)
        if rolled_back:
            rows = _replay(table, layout, case, writes)
        else:
            dumped = dumps.get(table.name.upper(), b"")
            rows = [decode_record(dumped[i : i + length], layout) for i in range(0, len(dumped) - length + 1, length)]
        tables[table.name] = rows
    return Observation(returns=returns, outputs=outputs, tables=tables, calls=calls, undone=undone,
                       messages=messages, error=error)  # fmt: skip


def _replay(
    table: Table, layout: Sequence[Field], case: Case, writes: Sequence[tuple[str, str, bytes]]
) -> list[dict[str, str | None]]:
    """The rows of a file after the task when a rollback happened: the rows of the case plus the writes that
    survived (the ones before the last syncpoint and the ones after the rollback), by key."""
    keys = [f for f in layout if f.name.upper() in {k.upper() for k in table.key}] or layout[:1]
    length = sum(f.length for f in layout)
    rows = next((r for n, r in case.setup.items() if n.upper() == table.name.upper()), [])
    state: dict[bytes, bytes] = {}
    for row in rows:
        record = encode_record(row, layout)
        state[_key_of(record, keys)] = record
    for file_name, op, data in writes:
        if file_name not in (table.name.upper(), "committed"):
            continue
        record = data[:length].ljust(length, b" ")
        key = _key_of(record, keys)
        if op == "DELETE":
            state.pop(key, None)
        else:
            state[key] = record
    return [decode_record(state[k], layout) for k in sorted(state)]


def _key_of(record: bytes, keys: Sequence[Field]) -> bytes:
    return b"".join(record[f.offset : f.offset + f.length] for f in keys)
