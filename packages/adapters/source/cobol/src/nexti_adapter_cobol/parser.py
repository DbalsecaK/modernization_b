"""A deterministic parser of the COBOL/CICS subset documented in ADR-0015: fixed-format source (sequence area,
indicator column, areas A and B up to column 72), COPY, the DATA DIVISION (levels, PICTURE, USAGE, OCCURS,
REDEFINES, VALUE and 88 conditions), the PROCEDURE DIVISION (sections, paragraphs, statements, PERFORM, CALL,
GO TO) and EXEC CICS / EXEC SQL blocks with their command and options. Line numbers are those of the file, so the
knowledge graph and the rules point at real lines. What the parser does not recognise is reported, never guessed."""

import re
from dataclasses import dataclass, field

_TOKEN = re.compile(
    r"""(?P<string>'(?:[^']|'')*'|"(?:[^"]|"")*")"""
    r"""|(?P<number>[+-]?\d+(?:\.\d+)?(?![A-Z0-9-]))"""
    r"""|(?P<word>[A-Z0-9][A-Z0-9-]*[A-Z0-9]|[A-Z0-9])"""
    r"""|(?P<period>\.(?=\s|$))"""
    r"""|(?P<symbol>>=|<=|[()=<>+*/,:])""",
    re.IGNORECASE,
)
VERBS = frozenset({
    "ACCEPT", "ADD", "CALL", "CLOSE", "COMPUTE", "CONTINUE", "DELETE", "DISPLAY", "DIVIDE", "ELSE", "END-EVALUATE",
    "END-IF", "END-PERFORM", "EVALUATE", "EXEC", "EXIT", "GO", "GOBACK", "IF", "INITIALIZE", "INSPECT", "MOVE",
    "MULTIPLY", "OPEN", "PERFORM", "READ", "REWRITE", "SEARCH", "SET", "STOP", "STRING", "SUBTRACT", "UNSTRING",
    "WHEN", "WRITE",
})  # fmt: skip
KEYWORDS = VERBS | frozenset({
    "AND", "OR", "NOT", "TO", "FROM", "INTO", "GIVING", "BY", "OF", "IN", "IS", "THAN", "EQUAL", "GREATER", "LESS",
    "TRUE", "FALSE", "OTHER", "ALSO", "THRU", "THROUGH", "UNTIL", "VARYING", "TIMES", "ZERO", "ZEROS", "ZEROES",
    "SPACE", "SPACES", "LOW-VALUE", "LOW-VALUES", "HIGH-VALUE", "HIGH-VALUES", "NUMERIC", "ALPHABETIC", "FUNCTION",
    "LENGTH", "ROUNDED", "END-EXEC", "CICS", "SQL", "DFHRESP", "EIBCALEN", "EIBAID", "RETURN", "CORRESPONDING",
    "ON", "SIZE", "ERROR", "WITH", "TEST", "BEFORE", "AFTER", "ALL", "NUMVAL", "UPPER-CASE", "LOWER-CASE",
})  # fmt: skip
# Verbs whose target (after TO / GIVING / FROM / INTO) the statement writes.
_WRITES_AFTER = {"MOVE": ("TO",), "ADD": ("TO", "GIVING"), "SUBTRACT": ("FROM", "GIVING"),
                 "MULTIPLY": ("BY", "GIVING"), "DIVIDE": ("INTO", "GIVING"), "SET": ("SET",),
                 "INITIALIZE": ("INITIALIZE",), "COMPUTE": ("COMPUTE",)}  # fmt: skip
# IBM-supplied copybooks: known, never part of the application.
SYSTEM_COPYBOOKS = frozenset({"DFHAID", "DFHBMSCA", "DFHEIBLK", "DFHCOMMAREA", "SQLCA"})
_TWO_WORD = {("SEND", "MAP"), ("SEND", "TEXT"), ("SEND", "CONTROL"), ("RECEIVE", "MAP"), ("HANDLE", "CONDITION"),
             ("HANDLE", "AID"), ("HANDLE", "ABEND")}  # fmt: skip


class CobolError(ValueError):
    def __init__(self, message: str, line: int) -> None:
        super().__init__(message)
        self.line = line


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    line: int
    column: int  # 1-based column of the source line

    @property
    def upper(self) -> str:
        return self.text.upper()


@dataclass
class DataItem:
    level: int
    name: str
    line: int
    file: str
    picture: str | None = None
    usage: str = "DISPLAY"
    occurs: int | None = None
    redefines: str | None = None
    value: str | None = None
    parent: str | None = None
    conditions: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    section: str = "WORKING-STORAGE"


@dataclass(frozen=True)
class CicsCommand:
    command: str
    options: dict[str, str | None]
    line_start: int
    line_end: int

    def option(self, name: str) -> str | None:
        """The argument of an option, without quotes when it is a literal."""
        value = self.options.get(name)
        if value is None:
            return None
        return value[1:-1] if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0] else value


@dataclass
class Statement:
    verb: str
    line_start: int
    line_end: int
    tokens: list[Token]
    cics: CicsCommand | None = None
    sql: str | None = None

    def names(self) -> list[str]:
        """The data names the statement mentions (words that are not keywords), in order."""
        return [
            t.upper for t in self.tokens if t.kind == "word" and t.upper not in KEYWORDS and not t.upper[0].isdigit()
        ]

    def writes(self) -> set[str]:
        words = [t.upper for t in self.tokens if t.kind == "word"]
        after = _WRITES_AFTER.get(self.verb)
        if not after:
            return set()
        if self.verb == "COMPUTE":
            texts = [t.upper for t in self.tokens]
            end = texts.index("=") if "=" in texts else len(texts)
            return {t.upper for t in self.tokens[1:end] if t.kind == "word" and t.upper not in KEYWORDS}
        if self.verb in ("SET", "INITIALIZE"):
            names = [w for w in words[1:] if w not in KEYWORDS]
            return set(names[:1] if self.verb == "SET" else names)
        for marker in reversed(after):
            if marker in words[1:]:
                index = len(words) - 1 - words[::-1].index(marker)
                return {w for w in words[index + 1 :] if w not in KEYWORDS and not w[0].isdigit()}
        return set()


@dataclass
class Paragraph:
    name: str
    line_start: int
    line_end: int
    section: str | None = None
    statements: list[Statement] = field(default_factory=list)

    def performs(self) -> list[tuple[str, int]]:
        found = []
        for s in self.statements:
            if s.verb == "PERFORM":
                words = [t for t in s.tokens[1:] if t.kind == "word"]
                if words and words[0].upper not in KEYWORDS:
                    found.append((words[0].upper, s.line_start))
        return found

    def calls(self) -> list[tuple[str, int]]:
        found = []
        for s in self.statements:
            if s.verb == "CALL" and len(s.tokens) > 1 and s.tokens[1].kind == "string":
                found.append((s.tokens[1].text[1:-1].upper(), s.line_start))
        return found

    def cics(self) -> list[CicsCommand]:
        return [s.cics for s in self.statements if s.cics is not None]


@dataclass
class Program:
    name: str
    file: str
    line_start: int
    line_end: int
    copies: list[tuple[str, int]] = field(default_factory=list)
    data: list[DataItem] = field(default_factory=list)
    paragraphs: list[Paragraph] = field(default_factory=list)
    procedure_line: int | None = None
    problems: list[str] = field(default_factory=list)
    linkage_copies: set[str] = field(default_factory=set)

    def paragraph(self, name: str) -> Paragraph | None:
        return next((p for p in self.paragraphs if p.name == name.upper()), None)

    def statements(self) -> list[Statement]:
        return [s for p in self.paragraphs for s in p.statements]


@dataclass
class Copybook:
    name: str
    file: str
    data: list[DataItem]
    copies: list[tuple[str, int]] = field(default_factory=list)


@dataclass(frozen=True)
class TransactionDef:
    transid: str
    program: str
    file: str
    line: int
    description: str = ""


# -- source lines and tokens --------------------------------------------------------------------------------------
def source_lines(text: str) -> list[tuple[int, int, str]]:
    """(line number, column of the first character, content) of the code lines: columns 8-72, comments and blank
    lines dropped. A continuation line (indicator '-') keeps its own number; a split literal is joined by the
    tokenizer."""
    lines = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\n\r")
        if len(line) >= 7 and line[6] in "*/":
            continue
        indicator = line[6] if len(line) >= 7 else " "
        content = line[7:72] if len(line) > 7 else ""
        if not content.strip():
            continue
        if indicator == "-":
            stripped = content.lstrip()
            lines.append((number, 8 + len(content) - len(stripped), "\x00" + stripped))
        else:
            lines.append((number, 8, content))
    return lines


def tokens(text: str) -> list[Token]:
    found: list[Token] = []
    open_literal = False  # the last token is a literal continued on the next line
    for number, first, content in source_lines(text):
        position = 0
        if content.startswith("\x00"):  # a continuation line
            content = content[1:]
            if open_literal and content[:1] in "'\"":
                close = content.find(content[0], 1)
                end = close + 1 if close > 0 else len(content)
                last = found.pop()
                found.append(Token("string", last.text + content[1:end], last.line, last.column))
                open_literal = close <= 0
                position = end
        while position < len(content):
            char = content[position]
            if char.isspace() or char == ";":
                position += 1
                continue
            match = _TOKEN.match(content, position)
            if match is None and char in "'\"":  # a literal that continues on the next line
                found.append(Token("string", content[position:].rstrip(), number, first + position))
                open_literal = True
                break
            open_literal = False
            if match is None:
                found.append(Token("unknown", char, number, first + position))
                position += 1
                continue
            found.append(Token(match.lastgroup or "unknown", match.group(0), number, first + position))
            position = match.end()
    return found


def _sentences(toks: list[Token]) -> list[list[Token]]:
    sentences: list[list[Token]] = []
    current: list[Token] = []
    for token in toks:
        if token.kind == "period":
            if current:
                sentences.append(current)
            current = []
        else:
            current.append(token)
    if current:
        sentences.append(current)
    return sentences


# -- data division ------------------------------------------------------------------------------------------------
def _data_items(
    sentences: list[list[Token]], file: str, problems: list[str]
) -> tuple[list[DataItem], list[tuple[str, int]], set[str]]:
    """The data items, the COPY statements and the copybooks copied into the LINKAGE SECTION."""
    items: list[DataItem] = []
    copies: list[tuple[str, int]] = []
    linkage: set[str] = set()
    stack: list[DataItem] = []
    section = "WORKING-STORAGE"
    for sentence in sentences:
        head = sentence[0]
        if head.upper == "COPY" and len(sentence) > 1:
            copies.append((sentence[1].text.strip("'\"").upper(), head.line))
            if section == "LINKAGE":
                linkage.add(copies[-1][0])
            continue
        if head.kind != "number" or not head.text.isdigit():
            if head.upper in ("WORKING-STORAGE", "LINKAGE", "LOCAL-STORAGE", "FILE"):
                section = head.upper
            elif head.upper not in ("FD", "SD"):
                problems.append(
                    f"{file}:{head.line}: unrecognised data entry '{' '.join(t.text for t in sentence[:4])}'"
                )
            continue
        level = int(head.text)
        name = sentence[1].upper if len(sentence) > 1 and sentence[1].kind == "word" else "FILLER"
        words = [t.upper for t in sentence]
        if level == 88:
            values = tuple(t.text.strip("'\"") for t in sentence[2:] if t.kind in ("string", "number")
                           or t.upper in ("SPACES", "ZERO", "ZEROS"))  # fmt: skip
            if stack:
                stack[-1].conditions.append((name, values))
            items.append(DataItem(88, name, head.line, file, value=",".join(values),
                                  parent=stack[-1].name if stack else None, section=section))  # fmt: skip
            continue
        item = DataItem(level, name, head.line, file, section=section)
        for i, word in enumerate(words):
            if word in ("PIC", "PICTURE"):
                j = i + 1 + (words[i + 1 : i + 2] == ["IS"])
                picture = ""
                # the picture is the run of tokens until the next clause (it may be split by the tokenizer)
                while j < len(sentence) and sentence[j].upper not in ("COMP", "COMP-3", "COMP-4", "COMP-5", "BINARY",
                                                                      "PACKED-DECIMAL", "DISPLAY", "USAGE", "VALUE",
                                                                      "OCCURS", "REDEFINES", "VALUES"):  # fmt: skip
                    picture += sentence[j].text
                    j += 1
                item.picture = picture.upper()
            elif word in ("COMP", "COMPUTATIONAL", "BINARY", "COMP-4", "COMP-5"):
                item.usage = "COMP"
            elif word in ("COMP-3", "COMPUTATIONAL-3", "PACKED-DECIMAL"):
                item.usage = "COMP-3"
            elif word == "OCCURS" and i + 1 < len(sentence) and sentence[i + 1].text.isdigit():
                item.occurs = int(sentence[i + 1].text)
            elif word == "REDEFINES" and i + 1 < len(sentence):
                item.redefines = sentence[i + 1].upper
            elif word in ("VALUE", "VALUES") and i + 1 < len(sentence):
                j = i + 1 + (words[i + 1 : i + 2] == ["IS"])
                if j < len(sentence):
                    item.value = sentence[j].text.strip("'\"")
        while stack and stack[-1].level >= level:
            stack.pop()
        item.parent = stack[-1].name if stack else None
        stack.append(item)
        items.append(item)
    return items, copies, linkage


def parse_copybook(name: str, file: str, text: str) -> Copybook:
    problems: list[str] = []
    items, copies, _ = _data_items(_sentences(tokens(text)), file, problems)
    return Copybook(name.upper(), file, items, copies)


# -- procedure division -------------------------------------------------------------------------------------------
def _cics(toks: list[Token]) -> CicsCommand:
    body = toks[2:]
    if body and body[-1].upper == "END-EXEC":
        body = body[:-1]
    words = [t for t in body if t.kind == "word"]
    command = words[0].upper if words else "?"
    rest = body[1:]
    if len(words) > 1 and (command, words[1].upper) in _TWO_WORD:
        command = f"{command} {words[1].upper}"
    options: dict[str, str | None] = {}
    i = 0
    while i < len(rest):
        token = rest[i]
        if token.kind == "word":
            if i + 1 < len(rest) and rest[i + 1].text == "(":
                depth, j, parts = 0, i + 1, []
                while j < len(rest):
                    if rest[j].text == "(":
                        depth += 1
                        if depth > 1:
                            parts.append("(")
                    elif rest[j].text == ")":
                        depth -= 1
                        if depth == 0:
                            break
                        parts.append(")")
                    else:
                        parts.append(rest[j].text)
                    j += 1
                options[token.upper] = " ".join(parts).replace(" ( ", "(").replace(" )", ")")
                i = j + 1
                continue
            options.setdefault(token.upper, None)
        i += 1
    return CicsCommand(command, options, toks[0].line, toks[-1].line)


def _statements(toks: list[Token]) -> list[Statement]:
    statements: list[Statement] = []
    i = 0
    while i < len(toks):
        token = toks[i]
        if token.upper == "EXEC" and i + 1 < len(toks):
            end = next((j for j in range(i, len(toks)) if toks[j].upper == "END-EXEC"), len(toks) - 1)
            block = toks[i : end + 1]
            kind = block[1].upper
            statement = Statement("EXEC", block[0].line, block[-1].line, block)
            if kind == "CICS":
                statement.cics = _cics(block)
            elif kind == "SQL":
                statement.sql = " ".join(t.text for t in block[2:-1])
            statements.append(statement)
            i = end + 1
            continue
        if token.kind == "word" and token.upper in VERBS:
            start = i
            i += 1
            while i < len(toks) and not (toks[i].kind == "word" and toks[i].upper in VERBS):
                i += 1
            chunk = toks[start:i]
            statements.append(Statement(token.upper, chunk[0].line, chunk[-1].line, chunk))
            continue
        if statements:  # a continuation (e.g. a condition split over lines) belongs to the statement before
            statements[-1].tokens.append(token)
            statements[-1].line_end = token.line
        i += 1
    return statements


def parse_program(file: str, text: str) -> Program:
    toks = tokens(text)
    problems: list[str] = []
    sentences = _sentences(toks)
    name = None
    for index, token in enumerate(toks[:-1]):
        if token.upper == "PROGRAM-ID":  # PROGRAM-ID. NAME. (the name follows the period)
            following = next((t for t in toks[index + 1 :] if t.kind != "period"), None)
            name = following.text.strip("'\"").upper() if following else None
            break
    if name is None:
        raise CobolError("no PROGRAM-ID", toks[0].line if toks else 1)
    last_line = len(text.splitlines())
    program = Program(name, file, 1, last_line)
    division = None
    data_sentences: list[list[Token]] = []
    procedure_tokens: list[Token] = []
    for sentence in sentences:
        words = [t.upper for t in sentence[:2]]
        if len(words) == 2 and words[1] == "DIVISION":
            division = words[0]
            if division == "PROCEDURE":
                program.procedure_line = sentence[0].line
            continue
        if division == "DATA":
            data_sentences.append(sentence)
        elif division == "PROCEDURE":
            procedure_tokens.extend(sentence)
            procedure_tokens.append(Token("period", ".", sentence[-1].line, sentence[-1].column + 1))
    program.data, program.copies, program.linkage_copies = _data_items(data_sentences, file, problems)
    # paragraphs: a single word in area A (column 8-11) followed by a period, or "name SECTION."
    current: Paragraph | None = None
    section: str | None = None
    body: list[Token] = []
    i = 0

    def close(end_line: int) -> None:
        if current is not None:
            current.statements = _statements([t for t in body if t.kind != "period"])
            current.line_end = max([s.line_end for s in current.statements] or [current.line_start])
            program.paragraphs.append(current)

    while i < len(procedure_tokens):
        token = procedure_tokens[i]
        nxt = procedure_tokens[i + 1] if i + 1 < len(procedure_tokens) else None
        after = procedure_tokens[i + 2] if i + 2 < len(procedure_tokens) else None
        in_area_a = token.column <= 11
        if in_area_a and token.kind in ("word", "number") and token.upper not in VERBS:
            if nxt is not None and nxt.kind == "period":
                close(token.line)
                current, body = Paragraph(token.upper, token.line, token.line, section), []
                i += 2
                continue
            if nxt is not None and nxt.upper == "SECTION" and after is not None and after.kind == "period":
                close(token.line)
                section, current, body = token.upper, None, []
                i += 3
                continue
        if current is None:
            current, body = Paragraph(section or "MAIN", token.line, token.line, section), []
        body.append(token)
        i += 1
    close(last_line)
    # the last paragraph runs to its last statement; the program to the last line of the file
    program.problems = problems
    for statement in program.statements():
        if statement.verb == "EXEC" and statement.cics is None and statement.sql is None:
            problems.append(f"{file}:{statement.line_start}: unsupported EXEC block")
        if statement.verb == "CALL" and (len(statement.tokens) < 2 or statement.tokens[1].kind != "string"):
            problems.append(f"{file}:{statement.line_start}: dynamic CALL")
    return program


def detect_programs(text: str) -> bool:
    return bool(re.search(r"^.{6}[ ]\s*(IDENTIFICATION|ID)\s+DIVISION\s*\.", text, re.IGNORECASE | re.MULTILINE))


# -- CICS system definitions (CSD) --------------------------------------------------------------------------------
_DEFINE = re.compile(r"DEFINE\s+TRANSACTION\s*\(\s*(?P<id>[A-Z0-9#@$]{1,4})\s*\)(?P<rest>.*?)(?=DEFINE\s|\Z)",
                     re.IGNORECASE | re.DOTALL)  # fmt: skip
_OPTION = re.compile(r"(?P<name>[A-Z]+)\s*\(\s*(?P<value>[^)]*)\)", re.IGNORECASE)


def parse_csd(file: str, text: str) -> list[TransactionDef]:
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("*"))
    found = []
    for match in _DEFINE.finditer(body):
        options = {m.group("name").upper(): m.group("value").strip() for m in _OPTION.finditer(match.group("rest"))}
        if "PROGRAM" not in options:
            continue
        line = text[: text.upper().find(f"TRANSACTION({match.group('id').upper()})")].count("\n") + 1
        found.append(TransactionDef(match.group("id").upper(), options["PROGRAM"].upper(), file, line,
                                    options.get("DESCRIPTION", "")))  # fmt: skip
    return found
