"""Deterministic generators of the Java Spring Boot pack (spec 8.4): everything that follows from the design without
judgement. The project is hexagonal inside (D-05):

    <base>/domain/model        entities (records with exact types)
    <base>/domain/port         ports to persistence (interfaces)
    <base>/domain/error        the business error with the legacy code
    <base>/application         use case services  <- written by the backend developer agent
    <base>/adapters/in/rest    REST controllers and request/response records (from the contracts)
    <base>/adapters/out/jdbc   JDBC adapters of the ports  <- written by the agent
    src/main/resources/db      PostgreSQL schema (from the entities)

Neutral types map to Java and PostgreSQL types here (4.3): `decimal(p,s)` -> BigDecimal / NUMERIC(p,s)...
"""

from nexti_core.spec import neutral_types as nt
from nexti_pack_spring_boot.design import Design, Entity, FieldSpec, Port, UseCase

SPRING_BOOT_VERSION = "3.5.6"
# The versions the pack and its sandbox image support, by the catalog's version key (ADR-0037, ADR-0040).
SPRING_BOOT_VERSIONS = {"3.5": SPRING_BOOT_VERSION}


def java_type(neutral: str) -> str:
    value = nt.parse(neutral)
    if isinstance(value, nt.Decimal):
        return "java.math.BigDecimal"
    if isinstance(value, nt.Integer):
        return "Long" if value.bits == 64 or (value.bits == 32 and not value.signed) else "Integer"
    if isinstance(value, nt.Text | nt.Enum):
        return "String"
    if isinstance(value, nt.Date):
        return "java.time.LocalDate"
    if isinstance(value, nt.Timestamp):
        return "java.time.OffsetDateTime" if value.tz else "java.time.LocalDateTime"
    if isinstance(value, nt.Boolean):
        return "Boolean"
    return "byte[]"


def sql_type(neutral: str) -> str:
    value = nt.parse(neutral)
    if isinstance(value, nt.Decimal):
        return f"NUMERIC({value.precision},{value.scale})"
    if isinstance(value, nt.Integer):
        return {8: "SMALLINT", 16: "SMALLINT", 32: "INTEGER" if value.signed else "BIGINT", 64: "BIGINT"}[value.bits]
    if isinstance(value, nt.Text):
        if value.length is None:
            return "TEXT"
        return f"{'CHAR' if value.kind == 'fixed' else 'VARCHAR'}({value.length})"
    if isinstance(value, nt.Enum):
        return f"VARCHAR({max(len(v) for v in value.values)})"
    if isinstance(value, nt.Date):
        return "DATE"
    if isinstance(value, nt.Timestamp):
        return "TIMESTAMPTZ" if value.tz else "TIMESTAMP"
    if isinstance(value, nt.Boolean):
        return "BOOLEAN"
    return "BYTEA"


def _pascal(name: str) -> str:
    return name[:1].upper() + name[1:]


def _snake(name: str) -> str:
    out = ""
    for index, char in enumerate(name):
        if char.isupper() and index and not name[index - 1].isupper():
            out += "_"
        out += char.lower()
    return out


def _record(package: str, name: str, fields: list[FieldSpec], doc: str) -> str:
    params = ",\n        ".join(f"{java_type(f.type)} {f.name}" for f in fields) or ""
    return (
        f"package {package};\n\n/** {doc} */\npublic record {name}(\n        {params}\n) {{\n}}\n"
        if params
        else f"package {package};\n\n/** {doc} */\npublic record {name}() {{\n}}\n"
    )


def entity_file(design: Design, entity: Entity) -> tuple[str, str]:
    package = f"{design.base_package}.domain.model"
    doc = f"Entity {entity.name}" + (f" (legacy table {entity.legacy_table})" if entity.legacy_table else "") + "."
    return _path(package, entity.name), _record(package, entity.name, entity.fields, doc)


def _java_return(returns: str | None, design: Design) -> str:
    if returns is None:
        return "void"
    if returns in {e.name for e in design.entities}:
        return f"java.util.Optional<{design.base_package}.domain.model.{returns}>"
    return {"boolean": "boolean", "int": "int", "long": "long"}[returns]


def port_file(design: Design, port: Port) -> tuple[str, str]:
    package = f"{design.base_package}.domain.port"
    methods = []
    for method in port.methods:
        params = ", ".join(f"{java_type(p.type)} {p.name}" for p in method.inputs)
        doc = f"    /** {method.description} */\n" if method.description else ""
        methods.append(f"{doc}    {_java_return(method.returns, design)} {method.name}({params});")
    body = "\n\n".join(methods)
    return _path(package, port.name), (
        f"package {package};\n\n/** Port to persistence (hexagonal: the domain does not know the database). */\n"
        f"public interface {port.name} {{\n\n{body}\n}}\n"
    )


def error_file(design: Design) -> tuple[str, str]:
    package = f"{design.base_package}.domain.error"
    return _path(package, "BusinessError"), (
        f"package {package};\n\n"
        "/** A business rejection with its stable code and the code the legacy returned. */\n"
        "public class BusinessError extends RuntimeException {\n\n"
        "    private final String code;\n    private final String legacyCode;\n\n"
        "    public BusinessError(String code, String legacyCode, String message) {\n"
        "        super(message);\n        this.code = code;\n        this.legacyCode = legacyCode;\n    }\n\n"
        "    public String code() {\n        return code;\n    }\n\n"
        "    public String legacyCode() {\n        return legacyCode;\n    }\n}\n"
    )


def contract_files(design: Design, use_case: UseCase) -> list[tuple[str, str]]:
    package = f"{design.base_package}.adapters.in.rest"
    request = _record(package, f"{use_case.name}Request", use_case.inputs, f"Request of {use_case.name}.")
    response = _record(package, f"{use_case.name}Response", use_case.outputs, f"Response of {use_case.name}.")
    return [
        (_path(package, f"{use_case.name}Request"), request),
        (_path(package, f"{use_case.name}Response"), response),
    ]


def placeholder_service(design: Design, use_case: UseCase) -> tuple[str, str]:
    """A service that compiles and does nothing, with the shape the prompts fix for the real one (one constructor
    with the ports in the order the use case lists them, `execute(request)`): the tests are compiled against it
    before the developer writes the service, so a test file that does not compile goes back to the test engineer
    instead of burning the developer's attempts (ADR-0042, P31)."""
    package = f"{design.base_package}.application"
    ports = [next(p for p in design.ports if p.name == name) for name in use_case.ports]
    params = ", ".join(f"{p.name} {p.name[:1].lower() + p.name[1:]}" for p in ports)
    imports = "".join(f"import {design.base_package}.domain.port.{p.name};\n" for p in ports)
    contracts = f"{design.base_package}.adapters.in.rest"
    body = (
        f"package {package};\n\n{imports}import {contracts}.{use_case.name}Request;\n"
        f"import {contracts}.{use_case.name}Response;\n\n"
        "/** Placeholder: the tests are compiled against it before the service exists. */\n"
        f"public class {use_case.name}Service {{\n\n    public {use_case.name}Service({params}) {{\n    }}\n\n"
        f"    public {use_case.name}Response execute({use_case.name}Request request) {{\n"
        '        throw new UnsupportedOperationException("placeholder");\n    }\n}\n'
    )
    return service_path(design, use_case), body


def controller_file(design: Design, use_case: UseCase) -> tuple[str, str]:
    """The REST adapter; with a unit of work in the design (ADR-0055) it runs the use case inside one transaction:
    a rejection (BusinessError) or any failure undoes every write and every call of the use case."""
    package = f"{design.base_package}.adapters.in.rest"
    service = f"{design.base_package}.application.{use_case.name}Service"
    path = use_case.path or "/" + _snake(use_case.name).replace("_", "-")
    mapping = {"GET": "GetMapping", "POST": "PostMapping", "PUT": "PutMapping", "PATCH": "PatchMapping",
               "DELETE": "DeleteMapping"}[use_case.http_method]  # fmt: skip
    body = "@RequestBody " if use_case.http_method in ("POST", "PUT", "PATCH") else ""
    work = use_case.unit_of_work
    lines = ", ".join(f"rollback at {r.legacy_line}" for r in work.rollbacks) if work else ""
    doc = (f" The unit of work of the legacy (begin at {work.begins_at}, {lines}, commit at {work.commits_at}) is "
           "this transaction." if work else "")  # fmt: skip
    imports = "import org.springframework.web.bind.annotation.*;\n" + (
        "import org.springframework.transaction.support.TransactionTemplate;\n" if work else ""
    )
    fields = f"    private final {service} service;\n" + (
        "    private final TransactionTemplate transaction;\n" if work else ""
    )
    constructor = (
        f"    public {use_case.name}Controller({service} service, TransactionTemplate transaction) {{\n"
        "        this.service = service;\n        this.transaction = transaction;\n    }\n"
        if work
        else f"    public {use_case.name}Controller({service} service) {{\n        this.service = service;\n    }}\n"
    )
    call = "transaction.execute(status -> service.execute(request))" if work else "service.execute(request)"
    return _path(package, f"{use_case.name}Controller"), (
        f"package {package};\n\n{imports}\n"
        f"/** REST adapter of {use_case.name} (rules {', '.join(use_case.rules)}).{doc} */\n"
        f'@RestController\n@RequestMapping("/api/{design.context}")\n'
        f"public class {use_case.name}Controller {{\n\n{fields}\n{constructor}\n"
        f'    @{mapping}("{path}")\n'
        f"    public {use_case.name}Response handle({body}{use_case.name}Request request) {{\n"
        f"        return {call};\n    }}\n}}\n"
    )


UNIT_OF_WORK_PORT = "UnitOfWork"
SP_STATUS = "nx_rc"


def unit_of_work_port(design: Design) -> Port | None:
    """The port the architect declares when the legacy has savepoints (ADR-0055): the platform implements it."""
    return next((p for p in design.ports if p.name == UNIT_OF_WORK_PORT and not p.legacy_program), None)


def unit_of_work_adapter_file(design: Design, port: Port) -> tuple[str, str]:
    """Savepoints on the connection of the current transaction: `savepoint(name)` marks, `rollbackTo(name)` undoes
    the work since the mark and the use case goes on, as the legacy's `rollback tran <savepoint>` does."""
    package = f"{design.base_package}.adapters.out.jdbc"
    return adapter_path(design, port), (
        f"package {package};\n\n"
        f"import {design.base_package}.domain.port.{port.name};\n"
        "import java.sql.Connection;\nimport java.sql.SQLException;\nimport java.sql.Savepoint;\n"
        "import java.util.HashMap;\nimport java.util.Map;\n"
        "import org.springframework.jdbc.core.JdbcTemplate;\n"
        "import org.springframework.jdbc.datasource.DataSourceUtils;\n"
        "import org.springframework.stereotype.Repository;\n\n"
        "/** Generated by the platform (ADR-0055): the savepoints of the legacy on the transaction of the use "
        "case. */\n"
        f"@Repository\npublic class Jdbc{port.name} implements {port.name} {{\n\n"
        "    private final JdbcTemplate jdbc;\n    private final Map<String, Savepoint> marks = new HashMap<>();\n\n"
        f"    public Jdbc{port.name}(JdbcTemplate jdbc) {{\n        this.jdbc = jdbc;\n    }}\n\n"
        "    @Override\n    public void savepoint(String name) {\n"
        "        try {\n            marks.put(name, connection().setSavepoint(name));\n"
        "        } catch (SQLException e) {\n"
        '            throw new IllegalStateException("savepoint " + name, e);\n        }\n    }\n\n'
        "    @Override\n    public void rollbackTo(String name) {\n"
        "        Savepoint mark = marks.get(name);\n"
        '        if (mark == null) {\n            throw new IllegalStateException("no savepoint " + name);\n        }\n'
        "        try {\n            connection().rollback(mark);\n"
        "        } catch (SQLException e) {\n"
        '            throw new IllegalStateException("rollback to " + name, e);\n        }\n    }\n\n'
        "    private Connection connection() {\n"
        "        return DataSourceUtils.getConnection(java.util.Objects.requireNonNull(jdbc.getDataSource()));\n"
        "    }\n}\n"
    )


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


def _bound(name: str, java: str) -> str:
    """A method argument as JDBC binds it to the legacy's driver (java.time has no mapping there)."""
    if java == "java.time.LocalDateTime":
        return f"{name} == null ? null : java.sql.Timestamp.valueOf({name})"
    if java == "java.time.LocalDate":
        return f"{name} == null ? null : java.sql.Date.valueOf({name})"
    return name


def _from_row(expression: str, java: str) -> str:
    """A value of the result row as the Java type of the design."""
    if java == "java.math.BigDecimal":
        return f"new java.math.BigDecimal(String.valueOf({expression}))"
    if java in ("Long", "long"):
        return f"((Number) {expression}).longValue()"
    if java in ("Integer", "int"):
        return f"((Number) {expression}).intValue()"
    if java in ("Boolean", "boolean"):
        return f"({expression} instanceof Boolean b ? b : ((Number) {expression}).intValue() != 0)"
    if java == "java.time.LocalDateTime":
        return f"((java.sql.Timestamp) {expression}).toLocalDateTime()"
    if java == "java.time.LocalDate":
        return f"((java.sql.Date) {expression}).toLocalDate()"
    if java == "String":
        return f"String.valueOf({expression})"
    return f"(byte[]) {expression}"


def program_adapter_file(design: Design, port: Port) -> tuple[str, str]:
    """The adapter of a port that replaces a legacy program when the data strategy keeps the database (ADR-0055):
    generated by the platform, never by a model. One T-SQL batch per method: the inputs bound by name, the return
    status captured and checked (a non-zero status throws, as the fakes of the golden master do), the output
    parameters read back into the method's result."""
    package = f"{design.base_package}.adapters.out.jdbc"
    entities = {e.name: e for e in design.entities}
    program = port.legacy_program or ""
    methods = []
    for method in port.methods:
        outputs: list[tuple[str, str, str]] = []  # (legacy parameter, column alias, neutral type)
        entity = entities.get(method.returns or "")
        if method.legacy_outputs and entity is not None:
            by_name = {f.name: f for f in entity.fields}
            outputs = [(legacy, legacy.lstrip("@"), by_name[field].type)
                       for field, legacy in method.legacy_outputs.items() if field in by_name]  # fmt: skip
        elif method.legacy_output:
            # A scalar output of a legacy program is a Sybase int (32 bits) even when the port returns a long.
            neutral = "boolean" if method.returns == "boolean" else "integer(32,signed)"
            outputs = [(method.legacy_output, method.legacy_output.lstrip("@"), neutral)]
        declares = ", ".join([f"@{SP_STATUS} int"] + [f"{p} {sybase_type(t)}" for p, _, t in outputs])
        arguments = [f"{f.legacy} = ?" for f in method.inputs if f.legacy]
        arguments += [f"{p} = {p} output" for p, _, _ in outputs]
        selects = ", ".join([f"@{SP_STATUS} as {SP_STATUS}"] + [f"{p} as {alias}" for p, alias, _ in outputs])
        batch = f"declare {declares}\\nexec @{SP_STATUS} = {program} {', '.join(arguments)}\\nselect {selects}"
        params = ", ".join(f"{java_type(f.type)} {f.name}" for f in method.inputs)
        binds = "".join(f", {_bound(f.name, java_type(f.type))}" for f in method.inputs if f.legacy)
        if entity is not None:
            result = f"java.util.Optional<{entity.name}>"
            built = ", ".join(
                f'nullable(row.get("{legacy.lstrip("@")}"), v -> {_from_row("v", java_type(f.type))})'
                if (legacy := method.legacy_outputs.get(f.name))
                else "null"
                for f in entity.fields
            )
            answer = f"return java.util.Optional.of(new {entity.name}({built}));"
        elif outputs:
            java = {"boolean": "boolean", "int": "int", "long": "long"}[method.returns or "int"]
            result = java
            fallback = {"boolean": "false", "int": "0", "long": "0L"}[java]
            answer = (f"Object value = row.get(\"{outputs[0][1]}\");\n"
                      f"        return value == null ? {fallback} : {_from_row('value', java)};")  # fmt: skip
        else:
            result = "void"
            answer = ""
        methods.append(
            f"    @Override\n    public {result} {method.name}({params}) {{\n"
            f'        java.util.Map<String, Object> row = jdbc.queryForMap(\n            "{batch}"{binds});\n'
            f'        int status = ((Number) row.get("{SP_STATUS}")).intValue();\n'
            f"        if (status != 0) {{\n"
            f'            throw new IllegalStateException("{program} answered " + status);\n        }}\n'
            + (f"        {answer}\n" if answer else "")
            + "    }\n"
        )
    imports = "".join(
        f"import {design.base_package}.domain.model.{e};\n"
        for e in sorted({m.returns for m in port.methods if m.returns in entities})
    )
    return adapter_path(design, port), (
        f"package {package};\n\n"
        f"import {design.base_package}.domain.port.{port.name};\n{imports}"
        "import org.springframework.jdbc.core.JdbcTemplate;\nimport org.springframework.stereotype.Repository;\n\n"
        f"/** Generated by the platform (ADR-0055, same database): {program} called where it lives, inside the "
        "transaction of the use case; its return status decides, its output parameters come back. */\n"
        f"@Repository\npublic class Jdbc{port.name} implements {port.name} {{\n\n"
        "    private final JdbcTemplate jdbc;\n\n"
        f"    public Jdbc{port.name}(JdbcTemplate jdbc) {{\n        this.jdbc = jdbc;\n    }}\n\n"
        + "\n".join(methods)
        + "\n    private static <T> T nullable(Object value, java.util.function.Function<Object, T> convert) {\n"
        "        return value == null ? null : convert.apply(value);\n    }\n}\n"
    )


def generated_adapters(design: Design) -> dict[str, str]:
    """The adapters the platform writes itself (ADR-0055): the unit of work with savepoints, and with
    `same_database` every port that replaces a legacy program."""
    files: dict[str, str] = {}
    unit = unit_of_work_port(design)
    if unit is not None:
        files.update([unit_of_work_adapter_file(design, unit)])
    if design.data_strategy == "same_database":
        for port in design.ports:
            if port.legacy_program:
                files.update([program_adapter_file(design, port)])
    return files


def application_file(design: Design) -> tuple[str, str]:
    package = design.base_package
    name = _pascal(design.context) + "Application"
    return _path(package, name), (
        f"package {package};\n\n"
        "import org.springframework.boot.SpringApplication;\n"
        "import org.springframework.boot.autoconfigure.SpringBootApplication;\n\n"
        f"@SpringBootApplication\npublic class {name} {{\n\n"
        "    public static void main(String[] args) {\n"
        f"        SpringApplication.run({name}.class, args);\n    }}\n}}\n"
    )


def schema_file(design: Design) -> tuple[str, str]:
    statements = []
    for entity in design.entities:
        if not entity.table:
            continue
        columns = [f"    {f.column or _snake(f.name)} {sql_type(f.type)}" for f in entity.fields]
        if entity.key:
            by_name = {f.name: f for f in entity.fields}
            keys = ", ".join(by_name[k].column or _snake(k) for k in entity.key)
            columns.append(f"    PRIMARY KEY ({keys})")
        origin = f" -- legacy {entity.legacy_table}" if entity.legacy_table else ""
        statements.append(f"CREATE TABLE {entity.table} ({origin}\n" + ",\n".join(columns) + "\n);")
    return "src/main/resources/db/schema.sql", "\n\n".join(statements) + "\n"


JTDS = (
    "<dependency><groupId>net.sourceforge.jtds</groupId><artifactId>jtds</artifactId><version>1.3.1</version>"
    "<scope>runtime</scope></dependency>"
)
POSTGRESQL = (
    "<dependency><groupId>org.postgresql</groupId><artifactId>postgresql</artifactId>"
    "<scope>runtime</scope></dependency>"
)


def pom_file(design: Design, spring_boot_version: str = SPRING_BOOT_VERSION) -> tuple[str, str]:
    """The build; with `same_database` the driver is the legacy's (Sybase ASE through jTDS), not PostgreSQL's."""
    artifact = design.context.replace("_", "-")
    driver = JTDS if design.data_strategy == "same_database" else POSTGRESQL
    return (
        "pom.xml",
        f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>{spring_boot_version}</version>
  </parent>
  <groupId>{design.base_package.rsplit(".", 1)[0]}</groupId>
  <artifactId>{artifact}</artifactId>
  <version>0.1.0</version>
  <properties><java.version>21</java.version></properties>
  <dependencies>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId></dependency>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-jdbc</artifactId></dependency>
    {driver}
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-test</artifactId><scope>test</scope></dependency>
  </dependencies>
</project>
""",
    )


def _path(package: str, name: str, test: bool = False) -> str:
    return f"src/{'test' if test else 'main'}/java/{package.replace('.', '/')}/{name}.java"


def service_path(design: Design, use_case: UseCase) -> str:
    return _path(f"{design.base_package}.application", f"{use_case.name}Service")


def junit_path(design: Design, use_case: UseCase) -> str:
    return _path(f"{design.base_package}.application", f"{use_case.name}ServiceTest", test=True)


def adapter_path(design: Design, port: Port) -> str:
    return _path(f"{design.base_package}.adapters.out.jdbc", f"Jdbc{port.name}")


def skeleton(design: Design, spring_boot_version: str = SPRING_BOOT_VERSION) -> dict[str, str]:
    """The deterministic files by layer: contracts, domain (model, ports, error), adapters (REST), orchestration."""
    files: dict[str, str] = dict(
        [pom_file(design, spring_boot_version), application_file(design), error_file(design), schema_file(design)]
    )
    for entity in design.entities:
        files.update([entity_file(design, entity)])
    for port in design.ports:
        files.update([port_file(design, port)])
    for use_case in design.use_cases:
        files.update(contract_files(design, use_case))
        files.update([controller_file(design, use_case)])
    files.update(generated_adapters(design))
    return files


LAYERS = ("contracts", "domain", "adapters", "orchestration")


def layer_of(path: str, design: Design) -> str:
    base = design.base_package.replace(".", "/")
    if path.startswith("src/test/"):
        return "tests"
    if "/adapters/in/rest/" in path and (path.endswith("Request.java") or path.endswith("Response.java")):
        return "contracts"
    if f"/{base}/domain/" in path or "/application/" in path:
        return "domain"
    if "/adapters/" in path or path.endswith(".sql"):
        return "adapters"
    return "orchestration"
