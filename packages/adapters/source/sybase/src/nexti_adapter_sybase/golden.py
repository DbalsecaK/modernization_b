# ruff: noqa: S608 - these T-SQL scripts only ever run inside the throw-away engine of a suite (ase.py)
"""Golden master scripts for Sybase ASE (spec 8.2 `runner()`, 8.3): everything needed to run a stored procedure in a
throw-away ASE with the data of a characterization case, and to read back what it did. Pure text in and out; the
engine itself is started by `nexti_adapter_sybase.ase`.

- Every database the code names (`db..table`, `db..proc`) is created; the procedures of the source files are
  created in a work database, unchanged.
- An external program (called but not in the source files) is replaced by a stub with the parameters of its call
  sites: it records the call and answers what the case says, one answer per call in order.
- Values come back length-prefixed (`5:hello|~|...`, `~` is NULL) so no data can break the parsing, and are made
  canonical with the neutral type of their column or parameter.
- Calls made inside a transaction the program rolls back are rolled back with it: they had no effect.
"""

import re
from dataclasses import dataclass, field

from nexti_adapter_sybase.lexer import Token, tokenize
from nexti_adapter_sybase.parser import Procedure, parse
from nexti_adapter_sybase.types import to_neutral
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import (
    Call,
    Case,
    Observation,
    Scalar,
    Schema,
    StubAnswer,
    Suite,
    canonical,
)

ENGINE = "sybase-ase-16.0"
WORK_DB = "nexti_gm"
DATABASE_MB = 30  # at least the size of model (24 MB on a 2 KB page server)
DEVICE_MB = 400
NULL = "~"
_MESSAGE = re.compile(r"^Msg (?P<number>\d+), Level (?P<level>\d+), State \d+:")


class GoldenError(ValueError):
    """The suite cannot run against this code (unknown program, table or parameter)."""


@dataclass(frozen=True)
class StubParameter:
    name: str
    type: str
    output: bool


@dataclass
class Stub:
    program: str  # as the code calls it, lowercase: db..proc or proc
    parameters: list[StubParameter] = field(default_factory=list)

    def parameter(self, name: str) -> StubParameter | None:
        return next((p for p in self.parameters if p.name == name.lower()), None)


def _database(name: str) -> str | None:
    return name.split("..", 1)[0].lower() if ".." in name else None


def _local(name: str) -> str:
    """`db..x` -> `dbo.x`; `owner.x` stays."""
    return "dbo." + name.split("..", 1)[1] if ".." in name else name


def _short(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower()


_CREATE_PROC = re.compile(r"\bcreate\s+proc(edure)?\b", re.IGNORECASE)
_EXTENSIONS = (".sp", ".sql", ".prc", ".proc", ".tsql", ".syb")


def procedures(files: list[SourceFile]) -> list[tuple[SourceFile, Procedure]]:
    """The procedures of the inputs; other files (COBOL, traces, maps) are not parsed as T-SQL."""
    return [(f, p) for f in files if f.path.lower().endswith(_EXTENSIONS) or _CREATE_PROC.search(f.text)
            for p in parse(f.text)]  # fmt: skip


def _groups(tokens: list[Token]) -> list[list[Token]]:
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
    return [g for g in groups if g]


def _literal_type(tokens: list[Token], variables: dict[str, str]) -> str:
    if len(tokens) == 1:
        tok = tokens[0]
        if tok.kind == "variable":
            return variables.get(tok.text.lower(), "varchar(255)")
        if tok.kind == "number":
            return "numeric(38,10)" if "." in tok.text else "int"
    return "varchar(255)"


def stubs(files: list[SourceFile]) -> dict[str, Stub]:
    """The external programs the code calls, with the named parameters of every call site."""
    found = procedures(files)
    local = {_short(p.name) for _, p in found}
    result: dict[str, Stub] = {}
    for file, proc in found:
        tokens, _ = tokenize(file.text)
        variables = {p.name: p.type for p in proc.parameters}
        for stmt in proc.statements():
            variables.update(stmt.declared)
        for stmt in proc.statements():
            if stmt.kind != "exec" or not stmt.calls or stmt.calls[0].startswith("@"):
                continue
            program = stmt.calls[0]
            if _short(program) in local:
                continue
            span = [t for t in tokens if stmt.line_start <= t.line <= stmt.line_end]
            start = next((k for k, t in enumerate(span) if t.is_word("EXEC", "EXECUTE")), None)
            if start is None:
                continue
            k = start + 1
            if k + 1 < len(span) and span[k].kind == "variable" and span[k + 1].is_symbol("="):
                k += 2
            while k < len(span) and (span[k].kind == "word" or span[k].is_symbol(".")):
                k += 1  # the callee name
            stub = result.setdefault(program, Stub(program))
            for group in _groups(span[k:]):
                if len(group) < 3 or group[0].kind != "variable" or not group[1].is_symbol("="):
                    continue  # positional arguments cannot be named in the stub
                output = group[-1].is_word("OUTPUT", "OUT")
                value = group[2:-1] if output else group[2:]
                name = group[0].text.lower()
                known = stub.parameter(name)
                if known is None:
                    stub.parameters.append(StubParameter(name, _literal_type(value, variables), output))
                elif output and not known.output:
                    stub.parameters[stub.parameters.index(known)] = StubParameter(name, known.type, True)
    return result


def _neutral(legacy_type: str) -> str | None:
    mapped = to_neutral(legacy_type)
    return str(mapped.neutral) if mapped.neutral is not None else None


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def literal(value: Scalar, legacy_type: str) -> str:
    """A case value as a T-SQL literal of the column or parameter type."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | float):
        return repr(value) if isinstance(value, float) else str(value)
    base = legacy_type.split("(", 1)[0].strip().lower()
    if base in ("datetime", "smalldatetime", "bigdatetime", "date"):
        return _quote(value.replace("T", " "))
    if base in ("int", "integer", "smallint", "tinyint", "bigint", "decimal", "numeric", "money", "smallmoney", "float",
                "real", "bit") and re.fullmatch(r"-?\d+(\.\d+)?", value):  # fmt: skip
        return value
    return _quote(value)


def _text(expr: str, legacy_type: str) -> str:
    """A T-SQL expression that prints the value without losing precision."""
    base = legacy_type.split("(", 1)[0].strip().lower()
    if base in ("money", "smallmoney"):
        return f"convert(varchar(60), convert(numeric(19,4), {expr}))"
    if base in ("float", "real", "double precision"):
        return f"convert(varchar(60), convert(numeric(38,15), {expr}))"
    if base in ("datetime", "smalldatetime", "bigdatetime"):
        return (f"convert(varchar(10), {expr}, 23) + 'T' + convert(varchar(8), {expr}, 108) + '.' + "
                f"right('00' + convert(varchar(3), datepart(ms, {expr})), 3)")  # fmt: skip
    if base == "date":
        return f"convert(varchar(10), {expr}, 23)"
    if base in ("binary", "varbinary", "image", "timestamp"):
        return f"bintostr({expr})"
    if base in ("char", "varchar", "nchar", "nvarchar", "unichar", "univarchar", "sysname"):
        return expr
    return f"convert(varchar(16384), {expr})"


def _prefixed(expr: str, legacy_type: str) -> str:
    text = _text(expr, legacy_type)
    return (f"case when {expr} is null then '{NULL}' else convert(varchar(10), char_length({text})) + ':' + "
            f"{text} end")  # fmt: skip


def _joined(parts: list[str]) -> str:
    return " + '|' + ".join(parts) if parts else "''"


def read_values(text: str) -> list[str | None]:
    """The inverse of `_prefixed` joined with `|`."""
    values: list[str | None] = []
    i = 0
    while i < len(text):
        if text[i] == NULL:
            values.append(None)
            i += 1
        else:
            colon = text.index(":", i)
            size = int(text[i:colon])
            values.append(text[colon + 1 : colon + 1 + size])
            i = colon + 1 + size
        if i < len(text) and text[i] == "|":
            i += 1
        elif i < len(text):
            break  # the padding isql adds after the last column
    return values


@dataclass(frozen=True)
class Plan:
    """What a suite needs from the engine, checked against the code before anything runs."""

    program: Procedure
    schema: Schema
    stubs: dict[str, Stub]
    databases: list[str]
    sources: list[SourceFile]


def unassigned_outputs(program: Procedure) -> list[str]:
    """The OUTPUT parameters no statement of the program writes (no `select @p =`, `set @p =`, `fetch into @p`,
    nor `@x = @p output` in a nested call): Sybase returns to the caller the value it passed in, so the recorded
    value is the case's input echoed, not behaviour of the program (ADR-0044). A real procedure of 2 173 lines
    declared one and 72 of 73 cases "differed" on it whatever the target did."""
    written = {v for stmt in program.statements() for v in stmt.vars_written}
    return sorted(q.name for q in program.parameters if q.output and q.name not in written)


def plan(files: list[SourceFile], suite: Suite) -> Plan:
    found = procedures(files)
    program = next((p for _, p in found if _short(p.name) == _short(suite.program)), None)
    if program is None:
        raise GoldenError(f"the program {suite.program} is not in the source files")
    external = stubs(files)
    touched = {t for _, p in found for s in p.statements() for t in s.reads | s.writes if not t.startswith("#")}
    missing = sorted(t for t in touched if suite.schema_.table(t) is None)
    if missing:
        raise GoldenError(f"the schema lacks tables the code uses: {', '.join(missing)}")
    parameters = {p.name for p in program.parameters}
    for case in suite.cases:
        unknown = sorted(n for n in case.inputs if n.lower() not in parameters)
        if unknown:
            raise GoldenError(f"{case.name}: {program.name} has no parameter {', '.join(unknown)}")
        for table, rows in case.setup.items():
            spec = suite.schema_.table(table)
            if spec is None:
                raise GoldenError(f"{case.name}: the table {table} is not in the schema")
            for row in rows:
                bad = sorted(c for c in row if spec.column(c) is None)
                if bad:
                    raise GoldenError(f"{case.name}: {table} has no column {', '.join(bad)}")
        for name, answers in case.stubs.items():
            stub = next((s for p, s in external.items() if p == name.lower() or _short(p) == _short(name)), None)
            if stub is None:
                raise GoldenError(f"{case.name}: {name} is not an external program of the code")
            for answer in answers:
                bad = sorted(o for o in answer.outputs if (param := stub.parameter(o)) is None or not param.output)
                if bad:
                    raise GoldenError(f"{case.name}: {name} has no output parameter {', '.join(bad)}")
    names = [t.name for t in suite.schema_.tables] + list(external)
    databases = sorted({d for n in names if (d := _database(n))} | {WORK_DB})
    return Plan(program, suite.schema_, external, databases, files)


def _go(*statements: str) -> str:
    return "\n".join(statements) + "\ngo\n"


def _use(database: str) -> str:
    """Alone in its batch: ASE resolves the names of a batch when it compiles it, before `use` runs."""
    return _go(f"use {database}")


def setup_script(p: Plan) -> str:
    """Once per engine: databases, tables, the call log and the procedures of the source files."""
    out = [_go("use master")]
    out.append(_go(f"disk init name = 'nxdev', physname = '/opt/sybase/data/nxdev.dat', size = '{DEVICE_MB}m'"))
    for database in p.databases:
        out.append(_go(f"create database {database} on nxdev = '{DATABASE_MB}m'"))
        out.append(_go(f"exec sp_dboption {database}, 'trunc log on chkpt', true"))
    out.append(_use(WORK_DB))
    out.append(_go("create table nx_call (seq numeric(10,0) identity, program varchar(200), args varchar(1700) null)"))
    for table in p.schema.tables:
        columns = ", ".join(f"{c.name} {c.type} {'null' if c.nullable else 'not null'}" for c in table.columns)
        out.append(_go(f"create table {table.name} ({columns})"))
    for program, stub in p.stubs.items():  # placeholders, so the procedures below resolve their calls
        out.append(_use(_database(program) or WORK_DB) + _go(_stub_body(stub, [])))
    for source in p.sources:
        out.append(_use(WORK_DB) + source.text.rstrip() + "\ngo\n")
    return "".join(out)


def _stub_body(stub: Stub, answers: list[StubAnswer]) -> str:
    params = ", ".join(f"{s.name} {s.type} = null{' output' if s.output else ''}" for s in stub.parameters)
    args = _joined([_prefixed(s.name, s.type) for s in stub.parameters if not s.output])
    lines = [
        f"create procedure {_local(stub.program)} {params} as",
        "begin",
        "  declare @nx_n int",
        f"  select @nx_n = count(*) + 1 from {WORK_DB}..nx_call where program = {_quote(stub.program)}",
        f"  insert {WORK_DB}..nx_call (program, args) values ({_quote(stub.program)}, {args})",
        # The call is reported the moment it happens, as a result set the client already holds: a `rollback`
        # after it undoes the row in nx_call (the count that picks the answer) but not the fact that the program
        # was called, which is what the comparison with the target needs (ADR-0044).
        f"  select 'NXC|' + {_quote(stub.program)} + '|' + {args}",
    ]
    for n, answer in enumerate(answers or [StubAnswer()], start=1):
        sets = [f"{name.lower()} = {literal(v, (stub.parameter(name) or StubParameter(name, 'varchar', True)).type)}"
                for name, v in answer.outputs.items()]  # fmt: skip
        body = (f"select {', '.join(sets)} " if sets else "") + f"return {answer.returns}"
        last = n == len(answers or [StubAnswer()])
        lines.append(f"  {body}" if last else f"  if @nx_n = {n} begin {body} end")
    lines.append("end")
    return "\n".join(lines)


def case_script(p: Plan, case: Case) -> str:
    """Resets the data, writes the stubs with the case's answers, calls the program and prints what it did."""
    out = [_use(WORK_DB), _go("truncate table nx_call")]
    resets = [f"truncate table {t.name}" for t in p.schema.tables]
    for table_name, rows in case.setup.items():
        table = p.schema.table(table_name)
        if table is None:  # plan() already rejected it
            raise GoldenError(f"{case.name}: the table {table_name} is not in the schema")
        for row in rows:
            columns = ", ".join(row)
            values = ", ".join(literal(v, (table.column(c) or table.columns[0]).type) for c, v in row.items())
            resets.append(f"insert {table.name} ({columns}) values ({values})")
    out.append(_go(*resets))
    for program, stub in p.stubs.items():
        answers = next((a for n, a in case.stubs.items() if n.lower() == program or _short(n) == _short(program)), [])
        database = _database(program) or WORK_DB
        out.append(_use(database))
        out.append(_go(f"if object_id('{_local(program)}') is not null drop procedure {_local(program)}"))
        out.append(_go(_stub_body(stub, answers)))
    params = p.program.parameters
    declares = ", ".join(["@nx_rc int"] + [f"{q.name} {q.type}" for q in params if q.output])
    inputs = {k.lower(): v for k, v in case.inputs.items()}
    arguments = []
    for q in params:
        if q.output:  # always bound to a variable, preset with the case value when there is one
            arguments.append(f"{q.name} = {q.name} output")
        elif q.name in inputs:
            arguments.append(f"{q.name} = {literal(inputs[q.name], q.type)}")
    presets = [f"select {q.name} = {literal(inputs[q.name], q.type)}" for q in params if q.output and q.name in inputs]
    call = f"exec @nx_rc = {p.program.name} " + ", ".join(arguments)
    prints = ["select 'NXR|' + " + _prefixed("@nx_rc", "int")]
    prints += [f"select 'NXO|{q.name}|' + {_prefixed(q.name, q.type)}" for q in params if q.output]
    out.append(_use(WORK_DB) + _go(f"declare {declares}", *presets, call, *prints))
    for table in p.schema.tables:
        order = ", ".join(table.key or [c.name for c in table.columns])
        printed = _joined([_prefixed(c.name, c.type) for c in table.columns])
        out.append(_go(f"select 'NXT|{table.name}|' + {printed} from {table.name} order by {order}"))
    return "".join(out)


_WARNINGS = {2007}  # a dependency missing from sysdepends: the object is created anyway


def engine_errors(output: str) -> list[str]:
    """System errors in isql output (level 11 or more, below the user range 17000), each with its text."""
    lines = output.splitlines()
    found = []
    for index, raw in enumerate(lines):
        message = _MESSAGE.match(raw.strip())
        if message and int(message["level"]) >= 11 and int(message["number"]) < 17000:
            if int(message["number"]) in _WARNINGS:
                continue
            detail = " ".join(x.strip() for x in lines[index + 1 : index + 3] if x.strip() and not _MESSAGE.match(x))
            found.append(f"Msg {message['number']}: {detail}"[:500])
    return found


def observe(p: Plan, output: str) -> Observation:
    """What the program did, read from the isql output of `case_script`."""
    returns: int | None = None
    outputs: dict[str, str | None] = {}
    tables: dict[str, list[dict[str, str | None]]] = {t.name: [] for t in p.schema.tables}
    calls: list[Call] = []
    messages: list[str] = []
    errors: list[str] = []
    types = {q.name: q.type for q in p.program.parameters}
    lines = output.splitlines()
    for index, raw in enumerate(lines):
        line = raw.strip()
        message = _MESSAGE.match(line)
        if message:
            detail = " ".join(x.strip() for x in lines[index + 1 : index + 3] if x.strip() and not _MESSAGE.match(x))
            number, level = int(message["number"]), int(message["level"])
            if number >= 17000:
                messages.append(f"{number}: {detail}"[:500])
            elif level >= 11 and number not in _WARNINGS:
                errors.append(f"Msg {number}: {detail}"[:500])
            continue
        if line.startswith("NXR|"):
            value = read_values(line[4:])[0]
            returns = int(value) if value is not None else None
        elif line.startswith("NXO|"):
            name, rest = line[4:].split("|", 1)
            outputs[name] = canonical(_neutral(types.get(name, "varchar")), read_values(rest)[0])
        elif line.startswith("NXT|"):
            name, rest = line[4:].split("|", 1)
            table = p.schema.table(name)
            if table is not None:
                values = read_values(rest)
                tables[table.name].append({c.name: canonical(_neutral(c.type), v)
                                           for c, v in zip(table.columns, values, strict=False)})  # fmt: skip
        elif line.startswith("NXC|"):
            program, rest = line[4:].split("|", 1)
            stub = p.stubs.get(program)
            values = read_values(rest) if rest else []
            params = [s for s in stub.parameters if not s.output] if stub else []
            calls.append(Call(program=program, arguments={
                s.name: canonical(_neutral(s.type), v) for s, v in zip(params, values, strict=False)}))  # fmt: skip
    error = "; ".join(errors)[:2000] if errors else None
    if returns is None and error is None:
        error = "the program did not return (no result was printed)"
    return Observation(returns=returns, outputs=outputs, tables=tables, calls=calls, messages=messages, error=error)


def parameter_defaults(files: list[SourceFile], program: str) -> dict[str, Scalar]:
    """The literal defaults of the program's parameters: a case that omits one runs with it on both sides."""
    found = next((p for _, p in procedures(files) if _short(p.name) == _short(program)), None)
    defaults: dict[str, Scalar] = {}
    for parameter in found.parameters if found else []:
        text = (parameter.default or "").strip()
        if not text or parameter.output:
            continue
        if text.lower() == "null":
            defaults[parameter.name] = None
        elif len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
            defaults[parameter.name] = text[1:-1].replace(text[0] * 2, text[0])
        elif re.fullmatch(r"-?\d+", text):
            defaults[parameter.name] = int(text)
        elif re.fullmatch(r"-?\d+\.\d+", text):
            defaults[parameter.name] = text
    return defaults
