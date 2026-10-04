"""A statement-level parser of Sybase ASE stored procedures: deterministic, no model involved (spec 6.1, phase 2).

Transact-SQL has no statement terminator: a statement ends where the next one begins. The parser reads the procedure
header (name, parameters with their types, defaults and OUTPUT), then a tree of statements (blocks, IF/ELSE, WHILE,
labels) where each statement knows its exact lines, the tables it reads and writes, the variables it reads and
writes, the procedures it calls, and whether it controls a transaction or checks an error.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

from nexti_adapter_sybase.lexer import Comment, Token, split_batches, tokenize

StatementKind = Literal[
    "block", "if", "while", "declare", "select", "set", "insert", "update", "delete", "exec", "return", "goto",
    "label", "begin_tran", "commit", "rollback", "save_tran", "raiserror", "print", "cursor", "create_table",
    "drop_table", "truncate", "break", "continue", "waitfor", "other",
]  # fmt: skip

# Words that begin a statement (at parenthesis depth 0, outside the clauses that own them).
STARTERS = {
    "BEGIN", "END", "IF", "ELSE", "WHILE", "DECLARE", "SELECT", "SET", "INSERT", "UPDATE", "DELETE", "EXEC",
    "EXECUTE", "RETURN", "GOTO", "COMMIT", "ROLLBACK", "SAVE", "RAISERROR", "PRINT", "OPEN", "FETCH", "CLOSE",
    "DEALLOCATE", "CREATE", "DROP", "TRUNCATE", "BREAK", "CONTINUE", "WAITFOR", "USE", "GRANT", "DUMP", "LOAD",
    "CHECKPOINT", "READTEXT", "WRITETEXT", "UPDATETEXT", "KILL", "SETUSER", "DBCC",
}  # fmt: skip
TABLE_INTRODUCERS = {"FROM", "JOIN", "INTO", "UPDATE"}
CLAUSE_ENDS = {
    "WHERE", "GROUP", "ORDER", "HAVING", "UNION", "ON", "SET", "VALUES", "SELECT", "COMPUTE", "FOR", "AT", "PLAN",
    "HOLDLOCK", "NOHOLDLOCK", "SHARED", "READPAST", "INDEX",
}  # fmt: skip


class ParseError(ValueError):
    def __init__(self, line: int, message: str) -> None:
        super().__init__(f"line {line}: {message}")
        self.line = line


@dataclass(frozen=True)
class Parameter:
    name: str
    type: str  # as written in the source, e.g. "varchar(14)", "money", a user-defined type
    default: str | None
    output: bool
    line: int


@dataclass
class Statement:
    kind: StatementKind
    line_start: int
    line_end: int
    reads: set[str] = field(default_factory=set)  # tables
    writes: set[str] = field(default_factory=set)
    vars_read: set[str] = field(default_factory=set)
    vars_written: set[str] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)
    label: str | None = None  # for label and goto
    checks_error: bool = False  # reads @@error / @@rowcount / @@transtate
    condition_lines: tuple[int, int] | None = None  # for if / while
    children: list["Statement"] = field(default_factory=list)  # block body, if-then, while body
    orelse: list["Statement"] = field(default_factory=list)
    declared: dict[str, str] = field(default_factory=dict)  # declare: variable -> type
    id: int = 0  # position in the procedure, assigned after parsing

    def walk(self) -> Iterator["Statement"]:
        yield self
        for child in (*self.children, *self.orelse):
            yield from child.walk()


@dataclass
class Procedure:
    name: str
    parameters: list[Parameter]
    body: list[Statement]
    line_start: int
    line_end: int
    comments: list[Comment]

    def statements(self) -> list[Statement]:
        return [s for top in self.body for s in top.walk()]


def _name(tokens: list[Token], i: int) -> tuple[str, int]:
    """A (possibly qualified) object name starting at i: db.owner.obj, db..obj, #temp. Returns (name, next index)."""
    parts: list[str] = []
    j = i
    expect_part = True
    while j < len(tokens):
        tok = tokens[j]
        if expect_part and tok.kind in ("word", "temp", "string"):
            parts.append(tok.text.strip('"'))
            expect_part = False
            j += 1
        elif tok.is_symbol("."):
            if expect_part:  # db..obj: the empty owner
                parts.append("")
            expect_part = True
            j += 1
        else:
            break
    return ".".join(parts).replace("...", ".."), j


name_at = _name  # for the adapter: the object name that starts at a token (CREATE TABLE in DDL files)


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.t = tokens
        self.i = 0

    # -- helpers -------------------------------------------------------------------------------------------------
    def peek(self, offset: int = 0) -> Token | None:
        j = self.i + offset
        return self.t[j] if j < len(self.t) else None

    def at_word(self, *words: str) -> bool:
        tok = self.peek()
        return tok is not None and tok.is_word(*words)

    def expect_word(self, word: str) -> Token:
        tok = self.peek()
        if tok is None or not tok.is_word(word):
            raise ParseError(tok.line if tok else (self.t[-1].line if self.t else 1), f"expected {word}")
        self.i += 1
        return tok

    def last_line(self) -> int:
        return self.t[self.i - 1].line if self.i else 1

    def is_label(self) -> bool:
        tok, nxt = self.peek(), self.peek(1)
        return (
            tok is not None
            and tok.kind == "word"
            and nxt is not None
            and nxt.is_symbol(":")
            and (
                self.peek(2) is None or self.peek(2).line > nxt.line or tok.upper not in STARTERS  # type: ignore[union-attr]
            )
        )

    def starts_statement(self, j: int, owner: str | None) -> bool:
        """Whether the token at j begins a new statement, given the kind of the statement being read."""
        tok = self.t[j]
        if tok.kind != "word" or tok.upper not in STARTERS:
            if tok.kind == "word" and j + 1 < len(self.t) and self.t[j + 1].is_symbol(":"):
                nxt = self.t[j + 2] if j + 2 < len(self.t) else None
                return nxt is None or nxt.line > tok.line  # a label alone on its line
            return False
        word = tok.upper
        prev = self.t[j - 1] if j else None
        if word == "SELECT" and (owner == "insert" or (prev is not None and prev.is_word("UNION", "ALL", "EXISTS"))):
            return False
        if word == "SET" and owner == "update":
            return False
        if word in ("UPDATE", "DELETE") and prev is not None and prev.is_word("FOR", "ON", "CASCADE"):
            return False
        if word == "FOR" and owner == "cursor":
            return False
        if word == "BEGIN" and prev is not None and prev.is_word("END"):  # END BEGIN is two statements
            return True
        return not (word == "END" and prev is not None and prev.is_word("CASE"))

    def span(self, owner: str | None) -> list[Token]:
        """Tokens of the current simple statement: until the next statement starter at depth 0, or `;`."""
        start = self.i
        depth = 0
        case_depth = 0
        while self.i < len(self.t):
            tok = self.t[self.i]
            if tok.is_symbol("("):
                depth += 1
            elif tok.is_symbol(")"):
                depth = max(0, depth - 1)
            elif tok.is_word("CASE"):
                case_depth += 1
            elif tok.is_word("END") and case_depth:
                case_depth -= 1
                self.i += 1
                continue
            elif tok.is_symbol(";") and depth == 0:
                self.i += 1
                break
            if self.i > start and depth == 0 and not case_depth and self.starts_statement(self.i, owner):
                break
            self.i += 1
        return self.t[start : self.i]

    # -- statements ----------------------------------------------------------------------------------------------
    def block_until_end(self) -> list[Statement]:
        body: list[Statement] = []
        while self.i < len(self.t) and not self.at_word("END"):
            body.append(self.statement())
        return body

    def statement(self) -> Statement:
        tok = self.peek()
        assert tok is not None  # noqa: S101 - callers check
        if self.is_label():
            self.i += 2
            return Statement("label", tok.line, tok.line, label=tok.text)
        word = tok.upper if tok.kind == "word" else ""
        if word == "BEGIN":
            nxt = self.peek(1)
            if nxt is not None and nxt.is_word("TRAN", "TRANSACTION"):
                tokens = self.span("tran")
                return Statement("begin_tran", tok.line, tokens[-1].line)
            self.i += 1
            children = self.block_until_end()
            end = self.expect_word("END")
            return Statement("block", tok.line, end.line, children=children)
        if word in ("IF", "WHILE"):
            self.i += 1
            condition = self.condition()
            first = condition[0].line if condition else tok.line
            last = condition[-1].line if condition else tok.line
            body = [self.statement()] if self.i < len(self.t) else []
            stmt = Statement("if" if word == "IF" else "while", tok.line, self.last_line(), children=body,
                             condition_lines=(first, last))  # fmt: skip
            _analyse(stmt, condition, "condition")
            if word == "IF" and self.at_word("ELSE"):
                self.i += 1
                stmt.orelse = [self.statement()] if self.i < len(self.t) else []
                stmt.line_end = self.last_line()
            return stmt
        if word == "ELSE":
            raise ParseError(tok.line, "ELSE without IF")
        owner = {"INSERT": "insert", "UPDATE": "update", "DECLARE": "declare"}.get(word)
        if word == "DECLARE" and self.peek(2) is not None and self.peek(2).is_word("CURSOR"):  # type: ignore[union-attr]
            owner = "cursor"
        tokens = self.span(owner)
        if not tokens:
            self.i += 1
            return Statement("other", tok.line, tok.line)
        kind = _kind(tokens)
        stmt = Statement(kind, tokens[0].line, tokens[-1].line)
        _analyse(stmt, tokens, kind)
        return stmt

    def condition(self) -> list[Token]:
        """The condition of IF / WHILE: until the statement it guards begins at depth 0."""
        start = self.i
        depth = 0
        case_depth = 0
        while self.i < len(self.t):
            tok = self.t[self.i]
            if tok.is_symbol("("):
                depth += 1
            elif tok.is_symbol(")"):
                depth -= 1
            elif tok.is_word("CASE"):
                case_depth += 1
            elif tok.is_word("END") and case_depth:
                case_depth -= 1
            elif depth == 0 and not case_depth and self.i > start and self.starts_statement(self.i, "condition"):
                break
            self.i += 1
        return self.t[start : self.i]


def _kind(tokens: list[Token]) -> StatementKind:
    first = tokens[0].upper
    second = tokens[1].upper if len(tokens) > 1 else ""
    simple: dict[str, StatementKind] = {
        "SELECT": "select", "SET": "set", "INSERT": "insert", "UPDATE": "update", "DELETE": "delete",
        "EXEC": "exec", "EXECUTE": "exec", "RETURN": "return", "GOTO": "goto", "COMMIT": "commit",
        "ROLLBACK": "rollback", "RAISERROR": "raiserror", "PRINT": "print", "OPEN": "cursor", "FETCH": "cursor",
        "CLOSE": "cursor", "DEALLOCATE": "cursor", "TRUNCATE": "truncate", "BREAK": "break",
        "CONTINUE": "continue", "WAITFOR": "waitfor",
    }  # fmt: skip
    if first == "DECLARE":
        return "cursor" if len(tokens) > 2 and tokens[2].is_word("CURSOR") else "declare"
    if first == "SAVE":
        return "save_tran"
    if first == "CREATE" and second == "TABLE":
        return "create_table"
    if first == "DROP" and second == "TABLE":
        return "drop_table"
    return simple.get(first, "other")


def _tables(tokens: list[Token]) -> tuple[set[str], set[str]]:
    """Tables read and written by one DML statement (FROM/JOIN lists, INTO, UPDATE target, DELETE target)."""
    reads: set[str] = set()
    writes: set[str] = set()
    first = tokens[0].upper if tokens else ""
    depth = 0
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.is_symbol("("):
            depth += 1
        elif tok.is_symbol(")"):
            depth -= 1
        elif tok.kind == "word" and tok.upper in TABLE_INTRODUCERS:
            if i + 1 < len(tokens) and tokens[i + 1].is_symbol("("):
                i += 1
                continue
            name, j = _name(tokens, i + 1)
            if name and not name.startswith("@"):
                target = (tok.upper == "INTO" and first in ("INSERT", "SELECT")) or (
                    tok.upper == "UPDATE" and first == "UPDATE" and i == 0
                )
                (writes if target else reads).add(name.lower())
                # FROM a x, b y: the following comma-separated tables
                while tok.upper in ("FROM", "JOIN") and j < len(tokens):
                    k = j
                    while (
                        k < len(tokens)
                        and not tokens[k].is_symbol(",")
                        and not (tokens[k].kind == "word" and tokens[k].upper in CLAUSE_ENDS | STARTERS | {"JOIN"})
                        and not tokens[k].is_symbol("(", ")")
                    ):
                        k += 1
                    if k < len(tokens) and tokens[k].is_symbol(","):
                        more, j = _name(tokens, k + 1)
                        if more:
                            reads.add(more.lower())
                            continue
                    break
            i = j
            continue
        i += 1
    if first == "DELETE":
        k = 2 if len(tokens) > 1 and tokens[1].is_word("FROM") else 1
        name, _ = _name(tokens, k)
        if name:
            writes.add(name.lower())
            reads.discard(name.lower())
    if first == "UPDATE":
        for name in writes:
            reads.discard(name)
    return reads, writes


def _analyse(stmt: Statement, tokens: list[Token], kind: str) -> None:
    names = [t for t in tokens if t.kind == "variable"]
    written: set[str] = set()
    if kind in ("select", "set"):
        depth = 0
        for j, tok in enumerate(tokens):
            if tok.is_symbol("("):
                depth += 1
            elif tok.is_symbol(")"):
                depth -= 1
            elif tok.kind == "variable" and depth == 0 and j + 1 < len(tokens) and tokens[j + 1].is_symbol("="):
                prev = tokens[j - 1] if j else None
                if prev is None or prev.is_symbol(",") or prev.is_word("SELECT", "SET", "DISTINCT"):
                    written.add(tok.text.lower())
    if kind == "exec":
        if len(tokens) > 2 and tokens[1].kind == "variable" and tokens[2].is_symbol("="):
            written.add(tokens[1].text.lower())
        callee_at = 3 if len(tokens) > 2 and tokens[2].is_symbol("=") else 1
        callee, _ = _name(tokens, callee_at)
        if callee:
            stmt.calls.append(callee.lower() if not callee.startswith("@") else callee)
        for j, tok in enumerate(tokens):
            if tok.is_word("OUTPUT", "OUT") and j and tokens[j - 1].kind == "variable":
                written.add(tokens[j - 1].text.lower())
    if kind == "cursor" and tokens and tokens[0].is_word("FETCH"):
        into = next((j for j, t in enumerate(tokens) if t.is_word("INTO")), None)
        if into is not None:
            written |= {t.text.lower() for t in tokens[into + 1 :] if t.kind == "variable"}
    if kind == "declare":
        j = 1
        while j < len(tokens):
            if tokens[j].kind == "variable":
                type_tokens: list[Token] = []
                k = j + 1
                if k < len(tokens) and tokens[k].is_word("AS"):
                    k += 1
                while k < len(tokens) and not tokens[k].is_symbol(","):
                    type_tokens.append(tokens[k])
                    k += 1
                stmt.declared[tokens[j].text.lower()] = _type_text(type_tokens)
                j = k
            j += 1
        return
    if kind in ("goto", "label"):
        stmt.label = tokens[1].text if kind == "goto" and len(tokens) > 1 else stmt.label
    stmt.vars_written |= written
    stmt.vars_read |= {t.text.lower() for t in names} - written
    # `select @a = @a + 1` reads @a too
    for j, tok in enumerate(tokens):
        if tok.kind == "variable" and tok.text.lower() in written:
            nxt = tokens[j + 1] if j + 1 < len(tokens) else None
            if nxt is None or not nxt.is_symbol("="):
                stmt.vars_read.add(tok.text.lower())
    stmt.checks_error = any(t.kind == "global" and t.upper in ("@@ERROR", "@@ROWCOUNT", "@@TRANSTATE") for t in tokens)
    if kind in ("select", "insert", "update", "delete", "cursor", "condition", "set", "create_table", "truncate",
                "drop_table"):  # fmt: skip
        reads, writes = _tables(tokens)
        if kind == "create_table" and len(tokens) > 2:
            name, _ = _name(tokens, 2)
            writes.add(name.lower())
        if kind in ("truncate", "drop_table") and len(tokens) > 2:
            name, _ = _name(tokens, 2)
            writes.add(name.lower())
        stmt.reads |= reads
        stmt.writes |= writes


def _type_text(tokens: list[Token]) -> str:
    """A type as written, normalised: words apart, symbols glued (`numeric(12,2)`, `double precision`)."""
    text = ""
    for tok in tokens:
        glue = tok.kind == "symbol" or (text and text[-1] in "(,")
        text += tok.text if glue or not text else " " + tok.text
    return text.lower()


def _parameters(tokens: list[Token]) -> list[Parameter]:
    params: list[Parameter] = []
    groups: list[list[Token]] = [[]]
    depth = 0
    for tok in tokens:
        if tok.is_symbol("("):
            depth += 1
        elif tok.is_symbol(")"):
            depth -= 1
        if tok.is_symbol(",") and depth == 0:
            groups.append([])
        else:
            groups[-1].append(tok)
    for group in groups:
        if not group or group[0].kind != "variable":
            continue
        rest = group[1:]
        if rest and rest[0].is_word("AS"):
            rest = rest[1:]
        output = any(t.is_word("OUTPUT", "OUT") for t in rest)
        rest = [t for t in rest if not t.is_word("OUTPUT", "OUT")]
        eq = next((k for k, t in enumerate(rest) if t.is_symbol("=")), None)
        type_tokens = rest if eq is None else rest[:eq]
        default = None if eq is None else " ".join(t.text for t in rest[eq + 1 :]) or None
        params.append(Parameter(group[0].text.lower(), _type_text(type_tokens), default, output, group[0].line))
    return params


def parse(source: str) -> list[Procedure]:
    """Every CREATE PROCEDURE of the file (usually one per batch)."""
    tokens, comments = tokenize(source)
    procedures: list[Procedure] = []
    for batch in split_batches(tokens):
        start = next((k for k, t in enumerate(batch) if t.is_word("CREATE")), None)
        if start is None or start + 1 >= len(batch) or not batch[start + 1].is_word("PROC", "PROCEDURE"):
            continue
        name, j = _name(batch, start + 2)
        if j < len(batch) and batch[j].is_symbol(";"):  # proc;2 groups
            j += 2
        k = j
        while k < len(batch) and not batch[k].is_word("AS"):
            k += 1
        if k == len(batch):
            raise ParseError(batch[start].line, "CREATE PROCEDURE without AS")
        header = [t for t in batch[j:k] if not t.is_word("WITH", "RECOMPILE")]
        if header and header[0].is_symbol("(") and header[-1].is_symbol(")"):
            header = header[1:-1]
        parser = _Parser(batch[k + 1 :])
        body: list[Statement] = []
        while parser.i < len(parser.t):
            body.append(parser.statement())
        proc = Procedure(name.lower(), _parameters(header), body, batch[start].line, batch[-1].line,
                         [c for c in comments if batch[start].line <= c.line_start <= batch[-1].line])  # fmt: skip
        for position, stmt in enumerate(proc.statements(), start=1):
            stmt.id = position
        procedures.append(proc)
    return procedures
