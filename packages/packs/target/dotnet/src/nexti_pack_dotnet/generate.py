# ruff: noqa: E501 - the lines of generated C# are kept whole, so the code reads like the file it writes
"""Deterministic generators of the .NET 10 pack (spec 8.4, ADR-0017): everything that follows from the design without
judgement. The project is hexagonal inside, like the Java pack (D-05):

    src/App/Domain/Model             entities (records with exact types)
    src/App/Domain/Port              ports to persistence (interfaces)
    src/App/Domain/Error             the business error with the legacy code
    src/App/Application              use case services  <- written by the backend developer agent
    src/App/Adapters/In/Rest         controllers, request/response records, transaction and error filters
    src/App/Adapters/Out/Sql         ADO.NET adapters of the ports  <- written by the agent
    src/App/Infrastructure/Db.cs     one connection and its transaction, shared by the adapters of a request
    src/App/Db/schema.sql            SQL Server schema (from the entities)
    tests/App.Tests                  xUnit tests  <- written by the test engineer agent

Neutral types map to C# and SQL Server types here (4.3): `decimal(p,s)` -> decimal / DECIMAL(p,s)...
Names the design uses as C# identifiers are escaped with @ when C# reserves them.
"""

from nexti_core.spec import neutral_types as nt
from nexti_core.spec.design import Design, Entity, FieldSpec, Port, UseCase
from nexti_core.spec.equivalence import snake

TARGET_FRAMEWORK = "net10.0"
# The exact versions restored in the sandbox image (infra/sandbox/dotnet/seed/Seed.csproj): keep both lists equal.
PACKAGES = {
    "Microsoft.Data.SqlClient": "6.1.7",
    "Microsoft.NET.Test.Sdk": "18.10.1",
    "xunit.v3": "3.2.2",
    "xunit.runner.visualstudio": "3.1.5",
    "JunitXml.TestLogger": "6.1.0",
}
APP = "src/App"
TESTS = "tests/App.Tests"
SCHEMA = f"{APP}/Db/schema.sql"
RESERVED = {
    "abstract", "as", "base", "bool", "break", "byte", "case", "catch", "char", "checked", "class", "const",
    "continue", "decimal", "default", "delegate", "do", "double", "else", "enum", "event", "explicit", "extern",
    "false", "finally", "fixed", "float", "for", "foreach", "goto", "if", "implicit", "in", "int", "interface",
    "internal", "is", "lock", "long", "namespace", "new", "null", "object", "operator", "out", "override", "params",
    "private", "protected", "public", "readonly", "ref", "return", "sbyte", "sealed", "short", "sizeof", "stackalloc",
    "static", "string", "struct", "switch", "this", "throw", "true", "try", "typeof", "uint", "ulong", "unchecked",
    "unsafe", "ushort", "using", "virtual", "void", "volatile", "while",
}  # fmt: skip


def ident(name: str) -> str:
    """A C# identifier: escaped with @ when C# reserves it."""
    return f"@{name}" if name in RESERVED else name


def pascal(name: str) -> str:
    return name[:1].upper() + name[1:]


def camel(name: str) -> str:
    return ident(name[:1].lower() + name[1:])


def namespace(design: Design) -> str:
    """The root namespace: the base package in PascalCase, without a leading reversed-domain prefix."""
    parts = design.base_package.split(".")
    if len(parts) > 1 and parts[0] in ("com", "org", "net", "io"):
        parts = parts[1:]
    return ".".join(pascal(p) for p in parts)


def cs_type(neutral: str) -> str:
    """Nullable, as the legacy values can be null (the Java pack uses boxed types for the same reason)."""
    value = nt.parse(neutral)
    if isinstance(value, nt.Decimal):
        return "decimal?"
    if isinstance(value, nt.Integer):
        return "long?" if value.bits == 64 or (value.bits == 32 and not value.signed) else "int?"
    if isinstance(value, nt.Text | nt.Enum):
        return "string?"
    if isinstance(value, nt.Date):
        return "DateOnly?"
    if isinstance(value, nt.Timestamp):
        return "DateTimeOffset?" if value.tz else "DateTime?"
    if isinstance(value, nt.Boolean):
        return "bool?"
    return "byte[]?"


def sql_type(neutral: str) -> str:
    value = nt.parse(neutral)
    if isinstance(value, nt.Decimal):
        return f"DECIMAL({value.precision},{value.scale})"
    if isinstance(value, nt.Integer):
        return {8: "SMALLINT", 16: "SMALLINT", 32: "INT" if value.signed else "BIGINT", 64: "BIGINT"}[value.bits]
    if isinstance(value, nt.Text):
        if value.length is None:
            return "NVARCHAR(MAX)"
        return f"{'NCHAR' if value.kind == 'fixed' else 'NVARCHAR'}({value.length})"
    if isinstance(value, nt.Enum):
        return f"NVARCHAR({max(len(v) for v in value.values)})"
    if isinstance(value, nt.Date):
        return "DATE"
    if isinstance(value, nt.Timestamp):
        return "DATETIMEOFFSET" if value.tz else "DATETIME2"
    if isinstance(value, nt.Boolean):
        return "BIT"
    return "VARBINARY(MAX)"


def _record(ns: str, name: str, fields: list[FieldSpec], doc: str) -> str:
    params = ",\n    ".join(f"{cs_type(f.type)} {pascal(f.name)}" for f in fields)
    body = f"(\n    {params})" if params else "()"
    return f"namespace {ns};\n\n/// <summary>{doc}</summary>\npublic sealed record {name}{body};\n"


def entity_file(design: Design, entity: Entity) -> tuple[str, str]:
    ns = f"{namespace(design)}.Domain.Model"
    doc = f"Entity {entity.name}" + (f" (legacy table {entity.legacy_table})" if entity.legacy_table else "") + "."
    return f"{APP}/Domain/Model/{entity.name}.cs", _record(ns, entity.name, entity.fields, doc)


def _cs_return(returns: str | None, design: Design) -> str:
    if returns is None:
        return "void"
    if returns in {e.name for e in design.entities}:
        return f"{namespace(design)}.Domain.Model.{returns}?"
    return {"boolean": "bool", "int": "int", "long": "long"}[returns]


def port_file(design: Design, port: Port) -> tuple[str, str]:
    ns = f"{namespace(design)}.Domain.Port"
    methods = []
    for method in port.methods:
        params = ", ".join(f"{cs_type(p.type)} {camel(p.name)}" for p in method.inputs)
        doc = f"    /// <summary>{method.description}</summary>\n" if method.description else ""
        methods.append(f"{doc}    {_cs_return(method.returns, design)} {pascal(method.name)}({params});")
    body = "\n\n".join(methods)
    return f"{APP}/Domain/Port/{port.name}.cs", (
        f"namespace {ns};\n\n/// <summary>Port to persistence (hexagonal: the domain does not know the database)."
        f"</summary>\npublic interface {port.name}\n{{\n{body}\n}}\n"
    )


def error_file(design: Design) -> tuple[str, str]:
    return f"{APP}/Domain/Error/BusinessError.cs", (
        f"namespace {namespace(design)}.Domain.Error;\n\n"
        "/// <summary>A business rejection with its stable code and the code the legacy returned.</summary>\n"
        "public sealed class BusinessError(string code, string? legacyCode, string message) : Exception(message)\n"
        "{\n    public string Code { get; } = code;\n\n    public string? LegacyCode { get; } = legacyCode;\n}\n"
    )


def db_file(design: Design) -> tuple[str, str]:
    return f"{APP}/Infrastructure/Db.cs", (
        f"using Microsoft.Data.SqlClient;\n\nnamespace {namespace(design)}.Infrastructure;\n\n"
        "/// <summary>One connection and its transaction: every adapter of a request (or of a golden case) works\n"
        "/// inside it, so a rejection undoes all its writes.</summary>\n"
        "public sealed class Db(SqlConnection connection) : IDisposable\n{\n"
        "    public SqlConnection Connection { get; } = connection;\n\n"
        "    public SqlTransaction? Transaction { get; private set; }\n\n"
        "    public static Db Open(string connectionString)\n    {\n"
        "        var connection = new SqlConnection(connectionString);\n        connection.Open();\n"
        "        return new Db(connection);\n    }\n\n"
        "    public void Begin() => Transaction = Connection.BeginTransaction();\n\n"
        "    public void Commit()\n    {\n        Transaction?.Commit();\n        Transaction = null;\n    }\n\n"
        "    public void Rollback()\n    {\n        Transaction?.Rollback();\n        Transaction = null;\n    }\n\n"
        "    /// <summary>A command on the connection, inside the current transaction if there is one.</summary>\n"
        "    public SqlCommand Command(string sql)\n    {\n        var command = Connection.CreateCommand();\n"
        "        command.CommandText = sql;\n        command.Transaction = Transaction;\n        return command;\n    }\n\n"
        "    public void Dispose()\n    {\n        Transaction?.Dispose();\n        Connection.Dispose();\n    }\n}\n"
    )


def filters_file(design: Design) -> tuple[str, str]:
    ns = namespace(design)
    return f"{APP}/Adapters/In/Rest/Filters.cs", (
        "using Microsoft.AspNetCore.Mvc;\nusing Microsoft.AspNetCore.Mvc.Filters;\n"
        f"using {ns}.Domain.Error;\nusing {ns}.Infrastructure;\n\n"
        f"namespace {ns}.Adapters.In.Rest;\n\n"
        "/// <summary>Each request in one transaction: committed when it succeeds, undone when it fails.</summary>\n"
        "public sealed class TransactionFilter(Db db) : IAsyncActionFilter\n{\n"
        "    public async Task OnActionExecutionAsync(ActionExecutingContext context, ActionExecutionDelegate next)\n"
        "    {\n        db.Begin();\n        var executed = await next();\n"
        "        if (executed.Exception is null)\n"
        "        {\n            db.Commit();\n        }\n        else\n        {\n            db.Rollback();\n        }\n"
        "    }\n}\n\n"
        "/// <summary>A business rejection as 422 with its codes (the contract's BusinessError).</summary>\n"
        "public sealed class BusinessErrorFilter : IExceptionFilter\n{\n"
        "    public void OnException(ExceptionContext context)\n    {\n"
        "        if (context.Exception is not BusinessError error)\n        {\n            return;\n        }\n"
        "        context.Result = new UnprocessableEntityObjectResult(\n"
        "            new { code = error.Code, legacyCode = error.LegacyCode, message = error.Message });\n"
        "        context.ExceptionHandled = true;\n    }\n}\n"
    )


def contract_files(design: Design, use_case: UseCase) -> list[tuple[str, str]]:
    ns = f"{namespace(design)}.Adapters.In.Rest"
    return [
        (f"{APP}/Adapters/In/Rest/{use_case.name}Request.cs",
         _record(ns, f"{use_case.name}Request", use_case.inputs, f"Request of {use_case.name}.")),
        (f"{APP}/Adapters/In/Rest/{use_case.name}Response.cs",
         _record(ns, f"{use_case.name}Response", use_case.outputs, f"Response of {use_case.name}.")),
    ]  # fmt: skip


def controller_file(design: Design, use_case: UseCase) -> tuple[str, str]:
    ns = namespace(design)
    path = use_case.path or "/" + snake(use_case.name).replace("_", "-")
    verb = {"GET": "HttpGet", "POST": "HttpPost", "PUT": "HttpPut", "PATCH": "HttpPatch",
            "DELETE": "HttpDelete"}[use_case.http_method]  # fmt: skip
    source = "[FromBody] " if use_case.http_method in ("POST", "PUT", "PATCH") else "[FromQuery] "
    return f"{APP}/Adapters/In/Rest/{use_case.name}Controller.cs", (
        f"using Microsoft.AspNetCore.Mvc;\nusing {ns}.Application;\n\n"
        f"namespace {ns}.Adapters.In.Rest;\n\n"
        f"/// <summary>REST adapter of {use_case.name} (rules {', '.join(use_case.rules)}).</summary>\n"
        f'[ApiController]\n[Route("api/{design.context}")]\n'
        f"public sealed class {use_case.name}Controller({use_case.name}Service service) : ControllerBase\n{{\n"
        f'    [{verb}("{path.lstrip("/")}")]\n'
        f"    public {use_case.name}Response Handle({source}{use_case.name}Request request) => service.Execute(request);\n"
        "}\n"
    )


def wiring_file(design: Design) -> tuple[str, str]:
    """The orchestration layer: the database session, one adapter per port and one service per use case."""
    ns = namespace(design)
    lines = ["        services.AddScoped(_ => Db.Open(connectionString));"]
    lines += [f"        services.AddScoped<{p.name}, {adapter_name(p.name)}>();" for p in design.ports]
    lines += [f"        services.AddScoped<{u.name}Service>();" for u in design.use_cases]
    body = "\n".join(lines)
    return f"{APP}/Wiring.cs", (
        f"using {ns}.Adapters.Out.Sql;\nusing {ns}.Application;\nusing {ns}.Domain.Port;\n"
        f"using {ns}.Infrastructure;\n\nnamespace {ns};\n\n"
        "/// <summary>The application services and adapters in the container (the domain classes know no framework)."
        "</summary>\npublic static class Wiring\n{\n"
        "    public static IServiceCollection AddApplication(this IServiceCollection services, string connectionString)\n"
        f"    {{\n{body}\n        return services;\n    }}\n}}\n"
    )


def program_file(design: Design) -> tuple[str, str]:
    ns = namespace(design)
    return f"{APP}/Program.cs", (
        f"using {ns};\nusing {ns}.Adapters.In.Rest;\n\n"
        "var builder = WebApplication.CreateBuilder(args);\n"
        "builder.Services.AddControllers(options =>\n{\n"
        "    options.Filters.Add<TransactionFilter>();\n    options.Filters.Add<BusinessErrorFilter>();\n});\n"
        'builder.Services.AddApplication(builder.Configuration.GetConnectionString("Main") ?? "");\n'
        "var app = builder.Build();\napp.MapControllers();\napp.Run();\n\n"
        "/// <summary>Visible to integration tests.</summary>\npublic partial class Program;\n"
    )


def schema_file(design: Design) -> tuple[str, str]:
    statements = []
    for entity in design.entities:
        if not entity.table:
            continue
        columns = [f"    {f.column or snake(f.name)} {sql_type(f.type)}" for f in entity.fields]
        if entity.key:
            by_name = {f.name: f for f in entity.fields}
            keys = ", ".join(by_name[k].column or snake(k) for k in entity.key)
            columns.append(f"    PRIMARY KEY ({keys})")
        origin = f" -- legacy {entity.legacy_table}" if entity.legacy_table else ""
        statements.append(f"CREATE TABLE {entity.table} ({origin}\n" + ",\n".join(columns) + "\n);")
    return SCHEMA, "\n\n".join(statements) + "\n"


def _package(name: str) -> str:
    return f'    <PackageReference Include="{name}" Version="{PACKAGES[name]}" />'


def app_project(design: Design) -> tuple[str, str]:
    return f"{APP}/App.csproj", (
        '<Project Sdk="Microsoft.NET.Sdk.Web">\n  <PropertyGroup>\n'
        f"    <TargetFramework>{TARGET_FRAMEWORK}</TargetFramework>\n    <RootNamespace>{namespace(design)}</RootNamespace>\n"
        "    <AssemblyName>App</AssemblyName>\n    <Nullable>enable</Nullable>\n    <ImplicitUsings>enable</ImplicitUsings>\n"
        "  </PropertyGroup>\n"
        f"  <ItemGroup>\n{_package('Microsoft.Data.SqlClient')}\n  </ItemGroup>\n"
        '  <ItemGroup>\n    <None Include="Db/schema.sql" CopyToOutputDirectory="PreserveNewest" />\n  </ItemGroup>\n'
        "</Project>\n"
    )


def test_project(design: Design) -> tuple[str, str]:
    packages = "\n".join(_package(p) for p in ("Microsoft.NET.Test.Sdk", "xunit.v3", "xunit.runner.visualstudio",
                                               "JunitXml.TestLogger"))  # fmt: skip
    return f"{TESTS}/App.Tests.csproj", (
        '<Project Sdk="Microsoft.NET.Sdk">\n  <PropertyGroup>\n'
        f"    <TargetFramework>{TARGET_FRAMEWORK}</TargetFramework>\n    <RootNamespace>{namespace(design)}.Tests</RootNamespace>\n"
        "    <Nullable>enable</Nullable>\n    <ImplicitUsings>enable</ImplicitUsings>\n    <OutputType>Exe</OutputType>\n"
        "    <IsPackable>false</IsPackable>\n  </PropertyGroup>\n"
        f"  <ItemGroup>\n{packages}\n  </ItemGroup>\n"
        '  <ItemGroup>\n    <FrameworkReference Include="Microsoft.AspNetCore.App" />\n'
        '    <ProjectReference Include="../../src/App/App.csproj" />\n  </ItemGroup>\n</Project>\n'
    )


def adapter_name(port: str) -> str:
    return f"Sql{port}"


def service_path(design: Design, use_case: UseCase) -> str:
    return f"{APP}/Application/{use_case.name}Service.cs"


def test_path(design: Design, use_case: UseCase) -> str:
    return f"{TESTS}/{use_case.name}ServiceTests.cs"


def adapter_path(design: Design, port: Port) -> str:
    return f"{APP}/Adapters/Out/Sql/{adapter_name(port.name)}.cs"


def skeleton(design: Design) -> dict[str, str]:
    """The deterministic files by layer: contracts, domain (model, ports, error), adapters (REST), orchestration."""
    files: dict[str, str] = dict([
        app_project(design), test_project(design), error_file(design), db_file(design), filters_file(design),
        schema_file(design), wiring_file(design), program_file(design),
    ])  # fmt: skip
    for entity in design.entities:
        files.update([entity_file(design, entity)])
    for port in design.ports:
        files.update([port_file(design, port)])
    for use_case in design.use_cases:
        files.update(contract_files(design, use_case))
        files.update([controller_file(design, use_case)])
    return files


def layer_of(path: str, design: Design) -> str:
    if path.startswith(f"{TESTS}/"):
        return "tests"
    if "/Adapters/In/Rest/" in path and path.endswith(("Request.cs", "Response.cs")):
        return "contracts"
    if "/Domain/" in path or "/Application/" in path:
        return "domain"
    if "/Adapters/" in path or "/Infrastructure/" in path or path.endswith(".sql"):
        return "adapters"
    return "orchestration"
