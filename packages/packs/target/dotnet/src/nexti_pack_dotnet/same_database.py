# ruff: noqa: E501 - the lines of generated C# are kept whole, so the code reads like the file it writes
"""`same_database` in the .NET pack (ADR-0055, ADR-0056 phase H): the data and the programs the legacy calls stay on
the legacy's Sybase ASE. The project talks to it through AdoNetCore.AseClient (a managed TDS client, no native
library), the unit of work is the legacy's own T-SQL (`begin tran`, `commit tran`, `rollback tran`, `save tran`) on
the request's connection in the engine's unchained mode, and every port that replaces a called program gets an
adapter the platform writes itself: one T-SQL batch with the arguments as literals (the statement the legacy ran),
its return status read back and its raised messages kept for the caller, never aborting the call.

The generators here are deterministic: everything follows from the design."""

from collections.abc import Callable

from nexti_core.spec import neutral_types as nt
from nexti_core.spec.design import Design, Port

UNIT_OF_WORK_PORT = "UnitOfWork"
UNIT_OF_WORK_METHODS = ("begin", "commit", "rollback")
SP_STATUS = "nx_rc"
STATUS = "return"  # the reserved legacy name of a called program's return status (ADR-0055, phase F)
ASE_PACKAGE = "AdoNetCore.AseClient"


def same_database(design: Design) -> bool:
    return design.data_strategy == "same_database"


def unit_of_work_port(design: Design) -> Port | None:
    """The port the architect declares when the legacy has savepoints or owns its transaction: the platform writes
    its adapter."""
    return next((p for p in design.ports if p.name == UNIT_OF_WORK_PORT and not p.legacy_program), None)


def owns_transaction(port: Port | None) -> bool:
    """Whether the UnitOfWork port begins, commits and rolls back (phase F): the service then owns the transaction
    and the request only closes what the use case left open."""
    if port is None:
        return False
    declared = {m.name for m in port.methods}
    return all(m in declared for m in UNIT_OF_WORK_METHODS)


def sybase_type(neutral: str) -> str:
    """The T-SQL type of a neutral type, for the variables that receive a procedure's outputs."""
    value = nt.parse(neutral)
    if isinstance(value, nt.Decimal):
        return f"numeric({value.precision},{value.scale})"
    if isinstance(value, nt.Integer):
        return {8: "tinyint", 16: "smallint", 32: "int", 64: "bigint"}[value.bits]
    if isinstance(value, nt.Text):
        return f"{'char' if value.kind == 'fixed' else 'varchar'}({value.length or 255})"
    if isinstance(value, nt.Enum):
        return f"varchar({max(len(v) for v in value.values)})"
    if isinstance(value, nt.Date):
        return "date"
    if isinstance(value, nt.Timestamp):
        return "datetime"
    if isinstance(value, nt.Boolean):
        return "bit"
    return "varbinary(255)"


def db_file(ns: str) -> str:
    """The database session on the legacy's engine: one AseConnection per request (or golden case), the unit of work
    as T-SQL on it, and the informational messages the engine sends kept in order."""
    return (
        "using System.Data.Common;\nusing AdoNetCore.AseClient;\n\n"
        f"namespace {ns}.Infrastructure;\n\n"
        "/// <summary>One connection to the legacy's Sybase ASE (same database, ADR-0055): every adapter of a request (or\n"
        "/// of a golden case) works on it. The unit of work is the legacy's own T-SQL on this connection, in the engine's\n"
        "/// unchained mode (ADR-0056): `begin tran`, `commit tran`, `rollback tran` and the savepoints, never a client\n"
        "/// transaction, which would run the legacy's procedures in a mode they were not written for.</summary>\n"
        "public sealed class Db : IDisposable\n{\n"
        "    public Db(AseConnection connection)\n    {\n        Connection = connection;\n"
        "        Connection.InfoMessage += (_, e) =>\n        {\n"
        "            foreach (AseError message in e.Errors)\n            {\n"
        '                Messages.Add(message.MessageNumber + ": " + message.Message.TrimEnd());\n'
        "            }\n        };\n    }\n\n"
        "    public AseConnection Connection { get; }\n\n"
        "    /// <summary>Always null: in unchained mode the statements need no client transaction object.</summary>\n"
        "    public DbTransaction? Transaction => null;\n\n"
        "    /// <summary>The informational messages of the engine on this connection, oldest first.</summary>\n"
        "    public List<string> Messages { get; } = [];\n\n"
        "    public static Db Open(string connectionString)\n    {\n"
        "        var connection = new AseConnection(connectionString);\n        connection.Open();\n"
        "        return new Db(connection);\n    }\n\n"
        '    public void Begin() => Run("begin tran");\n\n'
        "    /// <summary>Confirms what is open; nothing when the use case already closed it on the engine.</summary>\n"
        '    public void Commit() => Run("if @@trancount > 0 commit tran");\n\n'
        "    /// <summary>Undoes what is open (the engine's rollback when a batch aborts); nothing when it is closed.</summary>\n"
        '    public void Rollback() => Run("if @@trancount > 0 rollback tran");\n\n'
        '    public void Savepoint(string name) => Run("save tran " + Label(name));\n\n'
        '    public void RollbackTo(string name) => Run("rollback tran " + Label(name));\n\n'
        "    /// <summary>A command on the connection (the engine's transaction, if one is open, covers it).</summary>\n"
        "    public AseCommand Command(string sql)\n    {\n        var command = Connection.CreateCommand();\n"
        "        command.CommandText = sql;\n        return command;\n    }\n\n"
        "    public void Run(string sql)\n    {\n        using var command = Command(sql);\n        command.ExecuteNonQuery();\n    }\n\n"
        "    static string Label(string name) =>\n"
        '        System.Text.RegularExpressions.Regex.IsMatch(name, "^[A-Za-z_][A-Za-z0-9_]*$")\n'
        '            ? name : throw new ArgumentException("savepoint name " + name);\n\n'
        "    public void Dispose() => Connection.Dispose();\n}\n"
    )


def unit_of_work_adapter(design: Design, port: Port, ns: str, adapter: str) -> str:
    """The UnitOfWork port on the session: the service begins, confirms, undoes and marks where the legacy does."""
    bodies = {
        "begin": "db.Begin()", "commit": 'db.Run("commit tran")', "rollback": 'db.Run("rollback tran")',
        "savepoint": "db.Savepoint(name)", "rollbackTo": "db.RollbackTo(name)",
    }  # fmt: skip
    methods = []
    for method in port.methods:
        params = ", ".join(f"string? {p.name}" for p in method.inputs)
        body = bodies.get(method.name)
        if body is None:
            body = f'throw new NotSupportedException("{method.name} is not a unit of work operation")'
        elif method.inputs and method.inputs[0].name != "name":
            body = body.replace("(name)", f"({method.inputs[0].name}!)")
        else:
            body = body.replace("(name)", "(name!)")
        name = method.name[:1].upper() + method.name[1:]
        methods.append(f"    public void {name}({params}) => {body};\n")
    return (
        f"using {ns}.Domain.Port;\nusing {ns}.Infrastructure;\n\n"
        f"namespace {ns}.Adapters.Out.Sql;\n\n"
        "/// <summary>Generated by the platform (ADR-0055): the unit of work of the legacy on the request's connection,\n"
        "/// as T-SQL in the engine's transaction mode (ADR-0056). One instance per request, so two requests never see\n"
        "/// each other's savepoints.</summary>\n"
        f"public sealed class {adapter}(Db db) : {port.name}\n{{\n" + "\n".join(methods) + "}\n"
    )


def _from_row(expression: str, cs: str) -> str:
    """A value of the result row as the C# type of the design (null stays null)."""
    plain = cs.rstrip("?")
    convert = {
        "decimal": "System.Convert.ToDecimal({v}, Inv)", "int": "System.Convert.ToInt32({v}, Inv)",
        "long": "System.Convert.ToInt64({v}, Inv)", "string": "System.Convert.ToString({v}, Inv)!.TrimEnd()",
        "bool": "({v} is bool b ? b : System.Convert.ToInt32({v}, Inv) != 0)",
        "DateTime": "System.Convert.ToDateTime({v}, Inv)", "DateTimeOffset": "new DateTimeOffset(System.Convert.ToDateTime({v}, Inv))",
        "DateOnly": "DateOnly.FromDateTime(System.Convert.ToDateTime({v}, Inv))", "byte[]": "(byte[]){v}",
    }.get(plain, "{v}")  # fmt: skip
    return f"({expression} is null ? null : {convert.format(v=expression)})"


def program_adapter(design: Design, port: Port, ns: str, adapter: str, cs_type: Callable[[str], str]) -> str:
    """The adapter of a port that replaces a called program (ADR-0055): one T-SQL batch per method with the mapped
    inputs as literals (the statement the legacy ran, ADR-0056), the return status captured and checked (a non-zero
    status throws, as the fakes of the golden master do, unless the method carries it as data) and the output
    parameters read back into the method's result. The messages the program raises are kept, never thrown."""
    entities = {e.name: e for e in design.entities}
    program = port.legacy_program or ""
    methods = []
    for method in port.methods:
        outputs: list[tuple[str, str, str]] = []  # (legacy parameter, column alias, neutral type)
        entity = entities.get(method.returns or "")
        carries_status = method.legacy_output == STATUS or STATUS in method.legacy_outputs.values()
        if method.legacy_outputs and entity is not None:
            by_name = {f.name: f for f in entity.fields}
            outputs = [(legacy, legacy.lstrip("@"), by_name[field].type)
                       for field, legacy in method.legacy_outputs.items()
                       if field in by_name and legacy != STATUS]  # fmt: skip
        elif method.legacy_output and method.legacy_output != STATUS:
            neutral = "boolean" if method.returns == "boolean" else "integer(32,signed)"
            outputs = [(method.legacy_output, method.legacy_output.lstrip("@"), neutral)]
        declares = ", ".join([f"@{SP_STATUS} int"] + [f"{p} {sybase_type(t)}" for p, _, t in outputs])
        pieces = [f'"{f.legacy} = " + Literal({_camel(f.name)})' for f in method.inputs if f.legacy]
        pieces += [f'"{p} = {p} output"' for p, _, _ in outputs]
        arguments = ' + ", " + '.join(pieces) if pieces else '""'
        selects = ", ".join([f"@{SP_STATUS} as {SP_STATUS}"] + [f"{p} as {alias}" for p, alias, _ in outputs])
        batch = (f'"declare {declares}\\n" + "exec @{SP_STATUS} = {program} " + {arguments} + "\\n" '
                 f'+ "select {selects}"')  # fmt: skip
        params = ", ".join(f"{cs_type(f.type)} {_camel(f.name)}" for f in method.inputs)
        if entity is not None:
            result = f"{ns}.Domain.Model.{entity.name}?"
            built = ", ".join(
                "status"
                if method.legacy_outputs.get(f.name) == STATUS and cs_type(f.type).rstrip("?") in ("int", "long")
                else _from_row("(object)status", cs_type(f.type))
                if method.legacy_outputs.get(f.name) == STATUS
                else _from_row(f'row["{legacy.lstrip("@")}"]', cs_type(f.type))
                if (legacy := method.legacy_outputs.get(f.name))
                else "null"
                for f in entity.fields
            )
            answer = f"return new {ns}.Domain.Model.{entity.name}({built});"
        elif method.returns in ("int", "long", "boolean") and (method.legacy_output == STATUS or not outputs):
            result = {"int": "int", "long": "long", "boolean": "bool"}[method.returns]
            answer = {"int": "return status;", "long": "return status;", "boolean": "return status == 0;"}[
                method.returns
            ]
        elif outputs:
            result = {"boolean": "bool", "int": "int", "long": "long"}[method.returns or "int"]
            fallback = {"bool": "false", "int": "0", "long": "0L"}[result]
            answer = (f'var value = row["{outputs[0][1]}"];\n'
                      f"        return value is null ? {fallback} : {_plain(result, 'value')};")  # fmt: skip
        else:
            result = "void"
            answer = ""
        carries_status = carries_status or (method.returns in ("int", "long", "boolean") and not outputs)
        failure = (
            ""
            if carries_status
            else (
                "        if (status != 0)\n        {\n"
                f'            throw new InvalidOperationException("{program} answered " + status);\n'
                "        }\n"
            )
        )
        name = method.name[:1].upper() + method.name[1:]
        methods.append(
            f"    public {result} {name}({params})\n    {{\n"
            f"        var row = Call({batch});\n"
            f'        var status = System.Convert.ToInt32(row["{SP_STATUS}"], Inv);\n'
            + failure
            + (f"        {answer}\n" if answer else "")
            + "    }\n"
        )
    return (
        "using System.Globalization;\nusing AdoNetCore.AseClient;\n"
        f"using {ns}.Domain.Port;\nusing {ns}.Infrastructure;\n\n"
        f"namespace {ns}.Adapters.Out.Sql;\n\n"
        f"/// <summary>Generated by the platform (ADR-0055, same database): {program} called where it lives, inside the\n"
        "/// unit of work of the request; its return status decides, its output parameters come back. The arguments are\n"
        "/// sent as literals, the statement the legacy ran (ADR-0056). The messages it raises are kept for the caller and\n"
        "/// never abort the call, as the engine does not abort the caller of a procedure that raises.</summary>\n"
        f"public sealed class {adapter}(Db db) : {port.name}\n{{\n"
        "    static readonly CultureInfo Inv = CultureInfo.InvariantCulture;\n"
        "    readonly List<string> raised = [];\n\n"
        "    /// <summary>The messages the last call raised (raiserror), oldest first.</summary>\n"
        "    public IReadOnlyList<string> Messages() => raised.ToList();\n\n" + "\n".join(methods) + CALL_HELPER + "}\n"
    )


def _plain(cs: str, expression: str) -> str:
    return {"bool": f"({expression} is bool b ? b : System.Convert.ToInt32({expression}, Inv) != 0)",
            "int": f"System.Convert.ToInt32({expression}, Inv)",
            "long": f"System.Convert.ToInt64({expression}, Inv)"}[cs]  # fmt: skip


def _camel(name: str) -> str:
    from nexti_pack_dotnet.generate import camel

    return camel(name)


# The batch of a called program may return result sets of its own before the final SELECT with the status: the row
# that carries the status is the answer. A message the program raises (raiserror) reaches the client as an error
# between results (ADR-0056): it is kept and the reading goes on to the status, as the legacy caller goes on; only a
# batch with no status at all fails the call.
CALL_HELPER = """
    /// <summary>Runs the batch and returns the row of its last SELECT (the status and the outputs); the program's own
    /// result sets are skipped and its raised messages are kept in <see cref="Messages"/>.</summary>
    Dictionary<string, object?> Call(string batch)
    {
        raised.Clear();
        var before = db.Messages.Count;
        Dictionary<string, object?>? found = null;
        using (var command = db.Command(batch))
        {
            try
            {
                using var reader = command.ExecuteReader();
                do
                {
                    if (reader.FieldCount > 0 && reader.Read())
                    {
                        var row = new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase);
                        for (var i = 0; i < reader.FieldCount; i++)
                        {
                            row[reader.GetName(i)] = reader.IsDBNull(i) ? null : reader.GetValue(i);
                        }
                        if (row.ContainsKey("nx_rc"))
                        {
                            found = row;
                        }
                    }
                } while (reader.NextResult());
            }
            catch (AseException e)
            {
                foreach (AseError error in e.Errors)
                {
                    raised.Add(error.MessageNumber + ": " + error.Message.TrimEnd());
                }
                found ??= Status(e);
            }
        }
        raised.InsertRange(0, db.Messages.Skip(before));
        return found ?? throw new InvalidOperationException("the program returned no status"
            + (raised.Count == 0 ? "" : ": " + string.Join("; ", raised)));
    }

    /// <summary>The status row an error left unread: AseClient raises after the whole answer, so the rows are in
    /// the exception's data when the driver keeps them; otherwise none.</summary>
    static Dictionary<string, object?>? Status(AseException e) =>
        e.Data["row"] as Dictionary<string, object?>;

    static string Literal(object? value) => value switch
    {
        null => "null",
        string s => "'" + s.Replace("'", "''") + "'",
        bool b => b ? "1" : "0",
        DateTime t => "'" + t.ToString("yyyy-MM-dd HH:mm:ss.fff", Inv) + "'",
        DateTimeOffset o => "'" + o.ToString("yyyy-MM-dd HH:mm:ss.fff", Inv) + "'",
        DateOnly d => "'" + d.ToString("yyyy-MM-dd", Inv) + "'",
        byte[] bytes => "0x" + System.Convert.ToHexString(bytes),
        IFormattable f => f.ToString(null, Inv),
        _ => "'" + value.ToString()!.Replace("'", "''") + "'",
    };
"""
