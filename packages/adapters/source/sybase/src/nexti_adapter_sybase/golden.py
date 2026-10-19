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
    OMITTED,
    SUBSTITUTE_MESSAGE,
    Call,
    Case,
    Column,
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
OMITTED_MARK = "^"  # an argument the caller did not pass (ADR-0056): the substitute saw its sentinel default
# The number a substitute raises its messages with (ADR-0056): in the user range, so `observe` reads them as
# business messages, as it reads the program's own raiserror.
STUB_MESSAGE_NUMBER = SUBSTITUTE_MESSAGE
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


def sentinel(legacy_type: str) -> str | None:
    """The default a substitute declares for an input parameter (ADR-0056): a value no caller passes, so the
    substitute can tell an omitted argument from an explicit NULL (`= null` made both look the same). None for the
    types that cannot carry one (bit, text, image, binary): there the distinction is not observed."""
    base, _, rest = legacy_type.partition("(")
    base = base.strip().lower()
    if base in ("char", "varchar", "nchar", "nvarchar", "unichar", "univarchar", "sysname"):
        return "'~'"
    if base in ("int", "integer"):
        return "-2147483647"
    if base == "bigint":
        return "-9223372036854775807"
    if base == "smallint":
        return "-32767"
    if base == "tinyint":
        return "255"
    if base in ("numeric", "decimal"):
        digits = [int(x) for x in re.findall(r"\d+", rest)] or [18, 0]
        precision, scale = digits[0], digits[1] if len(digits) > 1 else 0
        whole = precision - scale
        return "-" + ("9" * whole if whole > 0 else "0") + ("." + "9" * scale if scale > 0 else "")
    if base == "money":
        return "-922337203685477.5807"
    if base == "smallmoney":
        return "-214748.3648"
    if base in ("float", "real", "double precision"):
        return "-1.0e30"
    if base in ("datetime", "bigdatetime"):
        return "'1753-01-01 00:00:00'"
    if base == "smalldatetime":
        return "'2079-06-06 00:00:00'"
    if base == "date":
        return "'0001-01-01'"
    return None


def _argument(parameter: "StubParameter") -> str:
    """How a substitute logs one input: the omitted mark when the caller left it to the sentinel default, else the
    length-prefixed value (NULL included)."""
    printed = _prefixed(parameter.name, parameter.type)
    default = sentinel(parameter.type)
    if default is None:
        return printed
    return f"case when {parameter.name} = {default} then '{OMITTED_MARK}' else {printed} end"


def read_values(text: str) -> list[str | None]:
    """The inverse of `_prefixed` joined with `|`; the omitted mark reads as `OMITTED`."""
    values: list[str | None] = []
    i = 0
    while i < len(text):
        if text[i] == NULL:
            values.append(None)
            i += 1
        elif text[i] == OMITTED_MARK:
            values.append(OMITTED)
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
    # The database the program is called in and the call log lives in: the platform's work database on its own
    # engine, the program's own database on a Sybase of the customer (ADR-0055).
    work: str = WORK_DB


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
                for table_name, rows in answer.effects.items():
                    spec = suite.schema_.table(table_name)
                    if spec is None:
                        raise GoldenError(f"{case.name}: {name} writes {table_name}, which is not in the schema")
                    for row in rows:
                        bad = sorted(c for c in row if spec.column(c) is None)
                        if bad:
                            raise GoldenError(f"{case.name}: {table_name} has no column {', '.join(bad)}")
                        given = {c.lower() for c in row}
                        lacking = [k for k in spec.key if k.lower() not in given]
                        if lacking:
                            raise GoldenError(f"{case.name}: the effect of {name} on {table_name} lacks its key "
                                              f"column(s) {', '.join(lacking)}")  # fmt: skip
    names = [t.name for t in suite.schema_.tables] + list(external)
    databases = sorted({d for n in names if (d := _database(n))} | {WORK_DB})
    return Plan(program, suite.schema_, external, databases, files)


def _go(*statements: str) -> str:
    return "\n".join(statements) + "\ngo\n"


def _use(database: str) -> str:
    """Alone in its batch: ASE resolves the names of a batch when it compiles it, before `use` runs."""
    return _go(f"use {database}")


def setup_script(p: Plan, with_sources: bool = True) -> str:
    """Once per engine: databases, tables, the call log and the procedures of the source files. Without the sources
    (ADR-0055) the engine is the one a target runs against: the tables and the substitutes, not the program."""
    out = [_go("use master")]
    out.append(_go(f"disk init name = 'nxdev', physname = '/opt/sybase/data/nxdev.dat', size = '{DEVICE_MB}m'"))
    for database in p.databases:
        out.append(_go(f"create database {database} on nxdev = '{DATABASE_MB}m'"))
        out.append(_go(f"exec sp_dboption {database}, 'trunc log on chkpt', true"))
    out.append(_use(p.work))
    out.append(_go(_CALL_LOG))
    for table in p.schema.tables:
        columns = ", ".join(f"{c.name} {c.type} {'null' if c.nullable else 'not null'}" for c in table.columns)
        out.append(_go(f"create table {table.name} ({columns})"))
    for program, stub in p.stubs.items():  # placeholders, so the procedures below resolve their calls
        out.append(_use(_database(program) or p.work) + _go(_stub_body(stub, [], p.work)) + _go(_anymode(program)))
    for source in p.sources if with_sources else []:
        out.append(_use(p.work) + source.text.rstrip() + "\ngo\n")
    return "".join(out)


def case_setup_batches(p: Plan, case: Case) -> list[str]:
    """What `case_script` does before calling the program, as batches a JDBC client runs one by one (ADR-0055): the
    data reset to the case's rows and the substitutes written with the case's answers."""
    batches = [f"use {p.work}", "truncate table nx_call"]
    for table in p.schema.tables:
        batches.append(f"truncate table {table.name}")
    for table_name, rows in case.setup.items():
        spec = p.schema.table(table_name)
        if spec is None:  # plan() already rejected it
            raise GoldenError(f"{case.name}: the table {table_name} is not in the schema")
        for row in rows:
            columns = ", ".join(row)
            values = ", ".join(literal(v, (spec.column(c) or spec.columns[0]).type) for c, v in row.items())
            batches.append(f"insert {spec.name} ({columns}) values ({values})")
    for program, stub in p.stubs.items():
        answers = next((a for n, a in case.stubs.items() if n.lower() == program or _short(n) == _short(program)), [])
        batches.append(f"use {_database(program) or p.work}")
        batches.append(f"if object_id('{_local(program)}') is not null drop procedure {_local(program)}")
        batches.append(_stub_body(stub, answers, p.work, p.schema))
        batches.append(_anymode(program))
    batches.append(f"use {p.work}")
    return batches


CALLS_QUERY = f"select program, args from {WORK_DB}..nx_call order by seq"


_CALL_LOG = "create table nx_call (seq numeric(10,0) identity, program varchar(200), args varchar(1700) null)"


def live_setup_script(p: Plan) -> str:
    """On a Sybase of the customer (`kind = sybase`, ADR-0055): nothing of the platform is installed but the call
    log in the program's database (`p.work`). The program, its tables and the programs it calls are the customer's
    and run for real: each one is checked to exist (`NXMISSING|` lines, read by `missing_objects`)."""
    checks = [f"if object_id('{p.program.name}') is null select 'NXMISSING|procedure {p.program.name}'"]
    checks += [f"if object_id('{t.name}') is null select 'NXMISSING|table {t.name}'" for t in p.schema.tables]
    checks += [f"if object_id('{program}') is null select 'NXMISSING|procedure {program}'" for program in p.stubs]
    return _use(p.work) + _go(*checks) + _go("if object_id('nx_call') is not null drop table nx_call", _CALL_LOG)


def live_check_script(database: str) -> str:
    """The connection test on a Sybase of the customer: sign on, use the program's database, say the version."""
    return _use(database) + _go("select 'NXREADY|' + @@version")


def missing_objects(output: str) -> list[str]:
    return [line.strip()[len("NXMISSING|") :] for line in output.splitlines() if line.strip().startswith("NXMISSING|")]


def install_script(procedure: str, text: str, work: str = WORK_DB) -> str:
    """Replaces the program with another text of it (the instrumented copy of ADR-0047), in the same engine."""
    return _use(work) + _go(f"drop procedure {procedure}") + text.rstrip() + "\ngo\n"


def _effects(schema: Schema | None, answer: StubAnswer) -> list[str]:
    """The rows a substitute leaves (ADR-0055), as statements that run inside the caller's transaction: a row with
    the same key is updated, a new one inserted; a table without key is always inserted."""
    out = []
    for table_name, rows in answer.effects.items():
        table = schema.table(table_name) if schema is not None else None
        if table is None:  # plan() already rejected it
            continue
        keys = {k.lower() for k in table.key}
        for row in rows:
            typed = {c: literal(v, (table.column(c) or table.columns[0]).type) for c, v in row.items()}
            where = " and ".join(f"{c} = {v}" for c, v in typed.items() if c.lower() in keys)
            sets = ", ".join(f"{c} = {v}" for c, v in typed.items() if c.lower() not in keys)
            insert = f"insert {table.name} ({', '.join(typed)}) values ({', '.join(typed.values())})"
            if not where:
                out.append(insert)
            elif sets:
                out.append(f"if exists (select 1 from {table.name} where {where}) update {table.name} set {sets} "
                           f"where {where} else {insert}")  # fmt: skip
            else:
                out.append(f"if not exists (select 1 from {table.name} where {where}) {insert}")
    return out


def _anymode(program: str) -> str:
    """A substitute runs in any transaction mode (ADR-0055): a target that calls it from a JDBC transaction works in
    chained mode, and a procedure created in unchained mode would refuse it. A real procedure of the customer needs
    the same (`sp_procxmode ... 'anymode'`) before a chained caller can use it."""
    return f"exec sp_procxmode '{_local(program)}', 'anymode'"


def _default(parameter: StubParameter) -> str:
    # An output is always bound to a variable; an input takes the sentinel, so an omitted argument is logged apart
    # from an explicit NULL (ADR-0056).
    return "null" if parameter.output else (sentinel(parameter.type) or "null")


def _stub_body(stub: Stub, answers: list[StubAnswer], work: str = WORK_DB, schema: Schema | None = None) -> str:
    params = ", ".join(f"{s.name} {s.type} = {_default(s)}{' output' if s.output else ''}" for s in stub.parameters)
    args = _joined([_argument(s) for s in stub.parameters if not s.output])
    lines = [
        f"create procedure {_local(stub.program)} {params} as",
        "begin",
        "  declare @nx_n int",
        f"  select @nx_n = count(*) + 1 from {work}..nx_call where program = {_quote(stub.program)}",
        f"  insert {work}..nx_call (program, args) values ({_quote(stub.program)}, {args})",
        # The attempt is reported the moment it happens (`NXC|`), as a result set the client already holds. Whether
        # the call is still in the final state is read from nx_call at the end of the case (`NXK|`, ADR-0055): a
        # `rollback` after it undoes the row, as it undoes every other effect of the program. This replaces P29.
        f"  select 'NXC|' + {_quote(stub.program)} + '|' + {args}",
    ]
    for n, answer in enumerate(answers or [StubAnswer()], start=1):
        sets = [f"{name.lower()} = {literal(v, (stub.parameter(name) or StubParameter(name, 'varchar', True)).type)}"
                for name, v in answer.outputs.items()]  # fmt: skip
        effects = "".join(f"{statement}\n    " for statement in _effects(schema, answer))
        # The messages the real program would raise (ADR-0056): raised before the status, as a procedure does, so
        # the caller is observed going on (Sybase: a callee's raiserror does not abort it) or stopping.
        raised = "".join(f"raiserror {STUB_MESSAGE_NUMBER} {_quote(text)}\n    " for text in answer.messages)
        body = effects + raised + (f"select {', '.join(sets)} " if sets else "") + f"return {answer.returns}"
        last = n == len(answers or [StubAnswer()])
        lines.append(f"  {body}" if last else f"  if @nx_n = {n} begin\n    {body}\n  end")
    lines.append("end")
    return "\n".join(lines)


def case_script(p: Plan, case: Case) -> str:
    """Resets the data, writes the stubs with the case's answers, calls the program and prints what it did."""
    out = [_use(p.work), _go("truncate table nx_call")]
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
        database = _database(program) or p.work
        out.append(_use(database))
        out.append(_go(f"if object_id('{_local(program)}') is not null drop procedure {_local(program)}"))
        out.append(_go(_stub_body(stub, answers, p.work, p.schema)))
        out.append(_go(_anymode(program)))
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
    out.append(_use(p.work) + _go(f"declare {declares}", *presets, call, *prints))
    # The calls that survived the program's unit of work (ADR-0055): the count first, so an empty log is told
    # apart from a case that never reached this point.
    out.append(_go("select 'NXKN|' + convert(varchar(10), count(*)) from nx_call",
                   "select 'NXK|' + program + '|' + isnull(args, '') from nx_call order by seq"))  # fmt: skip
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
    attempted: list[str] = []
    survived: list[str] | None = None
    messages: list[str] = []
    errors: list[tuple[int, str]] = []
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
                errors.append((level, f"Msg {number}: {detail}"[:500]))
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
            attempted.append(line[4:])
        elif line.startswith("NXKN|"):
            survived = []
        elif line.startswith("NXK|") and survived is not None:
            survived.append(line[4:])
    calls, undone = _calls(p, attempted, survived)
    # ADR-0056: a statement-level error the program lived through (level 11-16: a NULL into a NOT NULL column, a
    # constraint) is behaviour the program handles with @@error, the way its rollback branches are entered; it is
    # a message of the case, not a failure of the engine. Only a fatal error (level 17 or more) or a program that
    # never returned fails the case.
    handled = [text for level, text in errors if level < 17] if returns is not None else []
    fatal = [text for level, text in errors if level >= 17 or returns is None]
    messages += handled
    error = "; ".join(fatal)[:2000] if fatal else None
    if returns is None and error is None:
        error = "the program did not return (no result was printed)"
    return Observation(returns=returns, outputs=outputs, tables=tables, calls=calls, undone=undone,
                       messages=messages, error=error)  # fmt: skip


def _calls(p: Plan, attempted: list[str], survived: list[str] | None) -> tuple[list[Call], list[Call]]:
    """The calls in the final state (the rows of nx_call at the end of the case) and the attempts a rollback undid,
    each attempt matched in order against the rows (ADR-0055). Without the dump (the case was cut before it) every
    attempt counts as a call, which is what the recordings before the dump mean."""
    if survived is None:
        return [_call(p, text) for text in attempted], []
    calls: list[Call] = []
    undone: list[Call] = []
    pending = list(survived)
    for text in attempted:
        if pending and pending[0] == text:
            calls.append(_call(p, pending.pop(0)))
        else:
            undone.append(_call(p, text))
    return calls + [_call(p, text) for text in pending], undone


def _call(p: Plan, text: str) -> Call:
    program, rest = text.split("|", 1)
    stub = p.stubs.get(program)
    values = read_values(rest) if rest else []
    params = [s for s in stub.parameters if not s.output] if stub else []
    passed = [(s, v) for s, v in zip(params, values, strict=False) if v != OMITTED]
    return Call(program=program, arguments={s.name: canonical(_neutral(s.type), v) for s, v in passed})


# -- The customer's Sybase (ADR-0055, point 8): the tables the called programs touch ---------------------------------

SOURCE_MARK = "NXSRC|"
COLUMN_MARK = "NXCOL|"
_CHUNK = re.compile(r"<<NX>>(.*?)<<XN>>", re.S)
_SIZED = ("char", "varchar", "nchar", "nvarchar", "unichar", "univarchar", "binary", "varbinary")


def source_script(programs: list[str], work: str) -> str:
    """The text of each program as the customer's server keeps it (syscomments), each chunk between markers so the
    rows isql prints can be joined back without the newlines it puts between them."""
    out = []
    for program in programs:
        out.append(_use(_database(program) or work))
        out.append(_go(f"select '{SOURCE_MARK}{program}'",
                       "select '<<NX>>' + text + '<<XN>>' from syscomments "
                       f"where id = object_id('{_local(program)}') order by colid"))  # fmt: skip
    return "".join(out)


def read_sources(output: str) -> dict[str, str]:
    """Program -> its text, from the output of `source_script` (a program the server lacks has no text)."""
    found: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith(SOURCE_MARK):
            if current is not None:
                found[current] = "".join(_CHUNK.findall("\n".join(buffer)))
            current, buffer = line[len(SOURCE_MARK) :], []
        elif current is not None:
            buffer.append(raw)
    if current is not None:
        found[current] = "".join(_CHUNK.findall("\n".join(buffer)))
    return {program: text for program, text in found.items() if text.strip()}


def dependencies(program: str, text: str, work: str) -> tuple[set[str], set[str]]:
    """The tables a program reads or writes and the programs it calls, each qualified with its database (an
    unqualified name lives in the program's own database); temporary tables and calls through variables are not
    dependencies."""
    database = _database(program) or work
    tables: set[str] = set()
    calls: set[str] = set()
    for procedure in parse(text):
        for stmt in procedure.statements():
            for table in stmt.reads | stmt.writes:
                if not table.startswith("#"):
                    tables.add(table if ".." in table else f"{database}..{_short(table)}")
            for callee in stmt.calls:
                if not callee.startswith("@"):
                    calls.add(callee if ".." in callee else f"{database}..{_short(callee)}")
    return tables, calls


def columns_script(tables: list[str], work: str) -> str:
    """The columns of each table from the catalog: name, system type, length, precision, scale, nullability."""
    out = []
    for table in tables:
        out.append(_use(_database(table) or work))
        out.append(_go(
            f"select '{COLUMN_MARK}{table}|' + c.name + '|' + (select min(s.name) from systypes s "
            "where s.type = c.type and s.usertype < 100) + '|' + convert(varchar(10), c.length) + '|' + "
            "convert(varchar(10), isnull(c.prec, 0)) + '|' + convert(varchar(10), isnull(c.scale, 0)) + '|' + "
            "convert(varchar(2), "
            f"c.status & 8) from syscolumns c where c.id = object_id('{_local(table)}') order by c.colid"
        ))  # fmt: skip
    return "".join(out)


def read_columns(output: str) -> dict[str, list[Column]]:
    """Table -> its columns with the legacy type written as the code would (char(10), numeric(19,4), int)."""
    found: dict[str, list[Column]] = {}
    for raw in output.splitlines():
        line = raw.strip()
        if not line.startswith(COLUMN_MARK):
            continue
        parts = line[len(COLUMN_MARK) :].split("|")
        if len(parts) != 7:
            continue
        table, name, base, length, prec, scale, status = parts
        base = base.lower()
        if base in _SIZED:
            legacy = f"{base}({length})"
        elif base in ("numeric", "decimal"):
            legacy = f"{base}({prec},{scale})"
        else:
            legacy = base
        found.setdefault(table, []).append(Column(name=name, type=legacy, nullable=status == "8"))
    return found


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
