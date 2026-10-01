"""A deterministic reader of a subset of ASP.NET WebForms (spec 8.3, ADR-0020): the `asp:` controls of a page's markup
with their attributes and lines, and the classes and methods of C# code-behind and App_Code files with their line
ranges, the calls between them, the controls they read and write, the SQL they run and where they redirect. It never
executes anything and never uses a model."""

import re
from dataclasses import dataclass, field

_COMMENT = re.compile(r"<%--.*?--%>", re.DOTALL)
_DIRECTIVE = re.compile(r"<%@\s*(Page|Control|Master)\b([^%]*)%>", re.IGNORECASE)
_TAG = re.compile(r"<asp:(\w+)\b((?:[^>\"']|\"[^\"]*\"|'[^']*')*?)(/?)>", re.IGNORECASE)
_ATTRIBUTE = re.compile(r"([\w:.-]+)\s*=\s*(\"[^\"]*\"|'[^']*')")
_ITEM = re.compile(r"<asp:ListItem\b([^>]*?)/?>", re.IGNORECASE)
_REGISTER = re.compile(r"<%@\s*Register\b", re.IGNORECASE)

_CLASS = re.compile(r"\b(?:public|internal)?\s*(?:static\s+|partial\s+|sealed\s+|abstract\s+)*class\s+(\w+)"
                    r"(?:\s*:\s*([\w.]+))?")  # fmt: skip
_METHOD = re.compile(r"^\s*(?:(?:public|protected|private|internal|static|override|virtual|async)\s+)+"
                     r"([\w<>\[\],.?]+)\s+(\w+)\s*\(([^)]*)\)\s*$|^\s*(?:(?:public|protected|private|internal|static|"
                     r"override|virtual|async)\s+)+([\w<>\[\],.?]+)\s+(\w+)\s*\(([^)]*)\)\s*\{")  # fmt: skip
_STRING = re.compile(r'@?"((?:[^"\\]|\\.)*)"')
_STATIC_CALL = re.compile(r"\b([A-Z]\w*)\.([A-Z]\w*)\s*\(")
_LOCAL_CALL = re.compile(r"(?<![.\w])([A-Za-z_]\w*)\s*\(")
_WRITES_CONTROL = re.compile(r"\b(\w+)\.(Text|SelectedValue|Checked|Visible)\s*=(?!=)")
_READS_CONTROL = re.compile(r"\b(\w+)\.(Text|SelectedValue|Checked)\b(?!\s*=(?!=))")
_REDIRECT = re.compile(r"Response\.Redirect\(\s*\"([\w./~-]+?\.aspx)", re.IGNORECASE)
_READ_TABLES = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w.]*)", re.IGNORECASE)
_WRITE_TABLES = re.compile(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+([A-Za-z_][\w.]*)", re.IGNORECASE)
_SQL = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE)\b", re.IGNORECASE)
_KEYWORDS = {"if", "for", "foreach", "while", "switch", "using", "catch", "return", "new", "typeof", "nameof", "lock",
             "sizeof", "base", "this"}  # fmt: skip


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


@dataclass(frozen=True)
class Control:
    kind: str  # TextBox, DropDownList, Label, Button, HyperLink, RequiredFieldValidator...
    id: str
    attributes: dict[str, str]
    line: int
    line_end: int
    items: tuple[str, ...] = ()  # ListItem values of a list control

    def get(self, name: str, default: str = "") -> str:
        return next((v for k, v in self.attributes.items() if k.lower() == name.lower()), default)


@dataclass
class Markup:
    path: str
    kind: str  # Page, Control, Master
    code_file: str  # the code-behind file named by CodeFile / CodeBehind
    inherits: str
    title: str
    controls: list[Control] = field(default_factory=list)
    registers: int = 0  # user controls or third-party controls registered (outside the subset)

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1].split(".", 1)[0]


def parse_markup(path: str, text: str) -> Markup:
    clean = _COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    directive = _DIRECTIVE.search(clean)
    attributes = {k: v[1:-1] for k, v in _ATTRIBUTE.findall(directive.group(2))} if directive else {}
    code_file = attributes.get("CodeFile") or attributes.get("CodeBehind") or ""
    title = re.search(r"<title>\s*(.*?)\s*</title>", clean, re.IGNORECASE | re.DOTALL)
    markup = Markup(path, directive.group(1).title() if directive else "Page", code_file,
                    attributes.get("Inherits", ""), title.group(1).strip() if title else "")  # fmt: skip
    markup.registers = len(_REGISTER.findall(clean))
    for match in _TAG.finditer(clean):
        kind = match.group(1)
        if kind.lower() == "listitem":
            continue
        attrs = {k: v[1:-1] for k, v in _ATTRIBUTE.findall(match.group(2))}
        items: tuple[str, ...] = ()
        end = match.end()
        if not match.group(3):  # an open tag: its items until the closing tag
            closing = re.search(rf"</asp:{kind}\s*>", clean[match.end() :], re.IGNORECASE)
            if closing:
                body = clean[match.end() : match.end() + closing.start()]
                items = tuple({k: v[1:-1] for k, v in _ATTRIBUTE.findall(i)}.get("Value", "")
                              for i in _ITEM.findall(body))  # fmt: skip
                end = match.end() + closing.end()
        control_id = next((v for k, v in attrs.items() if k.lower() == "id"), "")
        markup.controls.append(Control(kind, control_id, attrs, line_of(clean, match.start()), line_of(clean, end),
                                       items))  # fmt: skip
    return markup


@dataclass(frozen=True)
class Method:
    owner: str
    name: str
    returns: str
    parameters: str
    line_start: int
    line_end: int
    calls: tuple[tuple[str, str], ...]  # (class or "", method)
    reads: tuple[str, ...]  # controls read
    writes: tuple[str, ...]  # controls written
    tables_read: tuple[str, ...]
    tables_written: tuple[str, ...]
    redirects: tuple[str, ...]
    sql: int  # SQL statements


@dataclass
class CSharpClass:
    path: str
    name: str
    base: str
    line_start: int
    line_end: int
    methods: list[Method] = field(default_factory=list)
    usings: tuple[str, ...] = ()


def _strip_comments(text: str) -> str:
    """Comments blanked (lines kept): strings stay, so SQL in literals is still read."""
    out = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.DOTALL)
    lines = []
    for line in out.split("\n"):
        position = 0
        in_string = False
        while position < len(line):
            char = line[position]
            if char == '"' and (position == 0 or line[position - 1] != "\\"):
                in_string = not in_string
            elif not in_string and line.startswith("//", position):
                line = line[:position]
                break
            position += 1
        lines.append(line)
    return "\n".join(lines)


def _block_end(lines: list[str], start: int) -> int:
    """The line (0-based) where the block opened at or after `start` closes, counting braces outside strings."""
    depth = 0
    opened = False
    for index in range(start, len(lines)):
        text = _STRING.sub('""', lines[index])
        for char in text:
            if char == "{":
                depth += 1
                opened = True
            elif char == "}":
                depth -= 1
                if opened and depth == 0:
                    return index
    return len(lines) - 1


def _tables(statements: list[str]) -> tuple[set[str], set[str]]:
    """Tables read (by SELECT statements) and written (by INSERT, UPDATE and DELETE), statement by statement."""
    read: set[str] = set()
    written: set[str] = set()
    for sql in statements:
        if re.match(r"\s*SELECT\b", sql, re.IGNORECASE):
            read |= {t.upper() for t in _READ_TABLES.findall(sql)}
        else:
            written |= {t.upper() for t in _WRITE_TABLES.findall(sql)}
    return read, written


def _statements(literals: list[str]) -> list[str]:
    """The SQL statements among a method's string literals; a literal that continues a statement (concatenated over
    several lines) is joined to it."""
    statements: list[str] = []
    for literal in literals:
        if re.match(r"\s*(SELECT|INSERT|UPDATE|DELETE|WITH)\b", literal, re.IGNORECASE):
            statements.append(literal)
        elif (
            statements
            and _SQL.search(statements[-1])
            and not statements[-1].rstrip().endswith(";")
            and re.match(r"\s*(VALUES|WHERE|AND|OR|SET|FROM|JOIN|ORDER|GROUP|\()", literal, re.IGNORECASE)
        ):
            statements[-1] += " " + literal
    return statements


def parse_csharp(path: str, text: str) -> list[CSharpClass]:
    clean = _strip_comments(text)
    lines = clean.split("\n")
    usings = tuple(m.group(1) for m in re.finditer(r"^\s*using\s+([\w.]+)\s*;", clean, re.MULTILINE))
    classes: list[CSharpClass] = []
    for index, line in enumerate(lines):
        found = _CLASS.search(line)
        if not found or line.strip().startswith(("//", "*")):
            continue
        end = _block_end(lines, index)
        classes.append(CSharpClass(path, found.group(1), found.group(2) or "", index + 1, end + 1, usings=usings))
    for owner in classes:
        index = owner.line_start
        while index < owner.line_end:
            signature = _METHOD.match(lines[index])
            if not signature:
                index += 1
                continue
            returns = signature.group(1) or signature.group(4) or ""
            name = signature.group(2) or signature.group(5) or ""
            parameters = signature.group(3) if signature.group(2) else signature.group(6) or ""
            end = _block_end(lines, index)
            body = "\n".join(lines[index + 1 : end + 1])
            sql_parts = _statements(_STRING.findall(body))
            read, written = _tables(sql_parts)
            calls = {(c, m) for c, m in _STATIC_CALL.findall(body)}
            calls |= {("", m) for m in _LOCAL_CALL.findall(_STRING.sub('""', body)) if m not in _KEYWORDS}
            writes = sorted({c for c, _ in _WRITES_CONTROL.findall(body)})
            reads = sorted({c for c, _ in _READS_CONTROL.findall(body)} - set())
            owner.methods.append(Method(
                owner.name, name, returns, parameters.strip(), index + 1, end + 1, tuple(sorted(calls)),
                tuple(reads), tuple(writes), tuple(sorted(read)), tuple(sorted(written)),
                tuple(sorted({r.lstrip("~/") for r in _REDIRECT.findall(body)})),
                len(sql_parts),
            ))  # fmt: skip
            index = end + 1
    return classes


# C# types to neutral types (4.3); a screen field's length comes from its MaxLength.
CSHARP_TYPES = {
    "decimal": "decimal(19,4,signed)", "int": "integer(32,signed)", "long": "integer(64,signed)",
    "short": "integer(16,signed)", "string": "text(var,max,utf8)", "bool": "boolean", "DateTime": "timestamp(local)",
    "double": "decimal(19,6,signed)", "float": "decimal(19,6,signed)", "byte": "integer(8,unsigned)",
}  # fmt: skip
