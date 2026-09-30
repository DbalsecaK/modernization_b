"""BMS maps as they are written (spec 8.3): assembler macros `DFHMSD` (mapset), `DFHMDI` (map) and `DFHMDF` (field),
with exact line numbers. Assembler layout: label in columns 1-8, operation, operands; a non-blank column 72 continues
the statement on the next line from column 16; a `*` in column 1 is a comment; columns 73-80 are ignored. Operands
end at the first blank outside a quoted string, and a string may run across a continuation."""

from dataclasses import dataclass, field

CONTINUATION_COLUMN = 72
CONTINUED_FROM = 16


class BmsError(ValueError):
    def __init__(self, line: int, message: str) -> None:
        super().__init__(f"line {line}: {message}")
        self.line = line


@dataclass(frozen=True)
class Statement:
    label: str
    operation: str
    operands: dict[str, str]
    line_start: int
    line_end: int


@dataclass
class BmsField:
    label: str | None
    row: int
    column: int
    length: int
    attributes: tuple[str, ...]
    initial: str
    picin: str
    picout: str
    validn: tuple[str, ...]
    line_start: int
    line_end: int


@dataclass
class BmsMap:
    name: str
    rows: int
    columns: int
    line_start: int
    line_end: int
    fields: list[BmsField] = field(default_factory=list)


@dataclass
class Mapset:
    name: str
    options: dict[str, str]
    line_start: int
    maps: list[BmsMap] = field(default_factory=list)


def _operand_part(segment: str, in_quote: bool) -> tuple[str, bool, bool]:
    """The operand text of one line: up to the first blank outside quotes. Returns (text, in_quote, ended)."""
    out: list[str] = []
    for char in segment:
        if char == "'":
            in_quote = not in_quote  # a doubled quote toggles twice: still inside
        elif char == " " and not in_quote:
            return "".join(out), in_quote, True
        out.append(char)
    return "".join(out), in_quote, False


def _split(text: str) -> list[str]:
    """Top-level comma-separated items (parentheses and quotes group)."""
    items: list[str] = []
    current: list[str] = []
    depth, quoted = 0, False
    for char in text:
        if char == "'":
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth -= 1
        if char == "," and depth == 0 and not quoted:
            items.append("".join(current))
            current = []
        else:
            current.append(char)
    if current:
        items.append("".join(current))
    return items


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def _operands(text: str, line: int) -> dict[str, str]:
    found: dict[str, str] = {}
    for item in _split(text):
        key, equal, value = item.partition("=")
        if not equal:
            found[key.strip().upper()] = ""
            continue
        if not key.strip():
            raise BmsError(line, f"an operand without a keyword: {item!r}")
        found[key.strip().upper()] = value.strip()
    return found


def statements(text: str) -> list[Statement]:
    lines = text.splitlines()
    found: list[Statement] = []
    index = 0
    while index < len(lines):
        raw = lines[index].rstrip("\n")
        if not raw.strip() or raw.startswith("*"):
            index += 1
            continue
        start = index
        label = raw[:8].strip() if not raw[:1].isspace() else ""
        rest = raw[: CONTINUATION_COLUMN - 1][len(label) :] if label else raw[: CONTINUATION_COLUMN - 1]
        rest = rest.lstrip()
        operation, _, after = rest.partition(" ")
        operand_text, in_quote, ended = _operand_part(after.lstrip(), False)
        pieces = [operand_text]
        continued = len(raw) >= CONTINUATION_COLUMN and raw[CONTINUATION_COLUMN - 1] != " "
        while continued:
            index += 1
            if index >= len(lines):
                raise BmsError(start + 1, "the statement continues past the end of the file")
            nxt = lines[index]
            segment = nxt[CONTINUED_FROM - 1 : CONTINUATION_COLUMN - 1]
            if not in_quote:
                segment = segment.lstrip()
            if not ended or in_quote:
                part, in_quote, ended = _operand_part(segment, in_quote)
                pieces.append(part)
            else:  # after a blank the rest was remarks; a continued line starts a new run of operands
                part, in_quote, ended = _operand_part(segment, False)
                pieces.append(part)
            continued = len(nxt) >= CONTINUATION_COLUMN and nxt[CONTINUATION_COLUMN - 1] != " "
        if in_quote:
            raise BmsError(start + 1, "a quoted string is not closed")
        found.append(Statement(label, operation.upper(), _operands("".join(pieces), start + 1), start + 1, index + 1))
        index += 1
    return found


def _pair(value: str, line: int, what: str) -> tuple[int, int]:
    inner = value.strip("()")
    try:
        first, second = (int(v) for v in inner.split(","))
    except ValueError as exc:
        raise BmsError(line, f"{what} must be (a,b), got {value!r}") from exc
    return first, second


def _list(value: str) -> tuple[str, ...]:
    return tuple(v.strip().upper() for v in value.strip("()").split(",") if v.strip())


def parse(text: str) -> list[Mapset]:
    """Every mapset of a file with its maps and fields."""
    mapsets: list[Mapset] = []
    current_set: Mapset | None = None
    current_map: BmsMap | None = None
    for stmt in statements(text):
        if stmt.operation == "DFHMSD":
            if stmt.operands.get("TYPE", "").upper() == "FINAL":
                current_set, current_map = None, None
                continue
            current_set = Mapset(stmt.label, stmt.operands, stmt.line_start)
            mapsets.append(current_set)
            current_map = None
        elif stmt.operation == "DFHMDI":
            if current_set is None:
                raise BmsError(stmt.line_start, "a map outside a mapset")
            rows, columns = _pair(stmt.operands.get("SIZE", "(24,80)"), stmt.line_start, "SIZE")
            current_map = BmsMap(stmt.label, rows, columns, stmt.line_start, stmt.line_end)
            current_set.maps.append(current_map)
        elif stmt.operation == "DFHMDF":
            if current_map is None:
                raise BmsError(stmt.line_start, "a field outside a map")
            position = stmt.operands.get("POS")
            if position is None:
                raise BmsError(stmt.line_start, "a field without POS")
            if position.startswith("("):
                row, column = _pair(position, stmt.line_start, "POS")
            else:  # an offset from the top left corner
                offset = int(position)
                row, column = offset // current_map.columns + 1, offset % current_map.columns + 1
            current_map.fields.append(BmsField(
                label=stmt.label or None, row=row, column=column, length=int(stmt.operands.get("LENGTH", "0")),
                attributes=_list(stmt.operands.get("ATTRB", "ASKIP")),
                initial=_unquote(stmt.operands.get("INITIAL", "")),
                picin=_unquote(stmt.operands.get("PICIN", "")), picout=_unquote(stmt.operands.get("PICOUT", "")),
                validn=_list(stmt.operands.get("VALIDN", "")), line_start=stmt.line_start, line_end=stmt.line_end,
            ))  # fmt: skip
            current_map.line_end = stmt.line_end
    return mapsets
