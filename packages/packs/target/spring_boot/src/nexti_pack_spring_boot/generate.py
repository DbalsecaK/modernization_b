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
from nexti_core.spec.design import writes
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


def controller_file(design: Design, use_case: UseCase, transactional: bool = True) -> tuple[str, str]:
    """The REST adapter; with a unit of work in the design (ADR-0055) it runs the use case inside one transaction:
    a rejection (BusinessError) or any failure undoes every write and every call of the use case. A flavour whose
    persistence has its own transaction (MongoDB) passes `transactional=False`: no TransactionTemplate there."""
    package = f"{design.base_package}.adapters.in.rest"
    service = f"{design.base_package}.application.{use_case.name}Service"
    path = use_case.path or "/" + _snake(use_case.name).replace("_", "-")
    mapping = {"GET": "GetMapping", "POST": "PostMapping", "PUT": "PutMapping", "PATCH": "PatchMapping",
               "DELETE": "DeleteMapping"}[use_case.http_method]  # fmt: skip
    body = "@RequestBody " if use_case.http_method in ("POST", "PUT", "PATCH") else ""
    work = use_case.unit_of_work
    unit = unit_of_work_port(design)
    if work is not None and unit is not None and owns_transaction(unit) and unit.name in use_case.ports:
        return _path(package, f"{use_case.name}Controller"), _service_owned_controller(design, use_case, unit)
    # ADR-0055 (point 17): without a legacy to copy the unit of work from, a use case that writes makes the
    # request its transaction (a rejection undoes every write).
    own = work is None and use_case.legacy_program is None and writes(design, use_case)
    lines = ", ".join(f"rollback at {r.legacy_line}" for r in work.rollbacks) if work else ""
    doc = (f" The unit of work of the legacy (begin at {work.begins_at}, {lines}, commit at {work.commits_at}) is "
           "this transaction." if work else " The use case writes: the request is its transaction." if own
           else "")  # fmt: skip
    work = (work or own) if transactional else None  # type: ignore[assignment]
    doc = doc if transactional else ""
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
    contract = _contract(use_case)
    if contract is not None:
        parameter, building, helpers = contract
        parameter = f"@RequestBody(required = false) {parameter}"
        fields += "    private final ObjectMapper mapper;\n"
        imports += (
            "import com.fasterxml.jackson.databind.JsonNode;\nimport com.fasterxml.jackson.databind.ObjectMapper;\n"
        )
        constructor = (
            constructor.replace(
                " service, TransactionTemplate transaction) {",
                " service, TransactionTemplate transaction, ObjectMapper mapper) {",
            )
            if work
            else constructor.replace(" service) {", " service, ObjectMapper mapper) {")
        )
        constructor = constructor.replace(
            "        this.service = service;\n", "        this.service = service;\n        this.mapper = mapper;\n"
        )
        return _path(package, f"{use_case.name}Controller"), (
            f"package {package};\n\n{imports}\n"
            f"/** REST adapter of {use_case.name} (rules {', '.join(use_case.rules)}).{doc}{CONTRACT_DOC} */\n"
            f'@RestController\n@RequestMapping("/api/{design.context}")\n'
            f"public class {use_case.name}Controller {{\n\n{fields}\n{constructor}\n"
            f'    @{mapping}("{path}")\n'
            f"    public {use_case.name}Response handle({parameter}) {{\n"
            f"{building}"
            f"        return {call};\n    }}\n{helpers}}}\n"
        )
    return _path(package, f"{use_case.name}Controller"), (
        f"package {package};\n\n{imports}\n"
        f"/** REST adapter of {use_case.name} (rules {', '.join(use_case.rules)}).{doc} */\n"
        f'@RestController\n@RequestMapping("/api/{design.context}")\n'
        f"public class {use_case.name}Controller {{\n\n{fields}\n{constructor}\n"
        f'    @{mapping}("{path}")\n'
        f"    public {use_case.name}Response handle({body}{use_case.name}Request request) {{\n"
        f"        return {call};\n    }}\n}}\n"
    )


# ADR-0056 (phase D): the contract of a use case that replaces a legacy program comes from the program's signature.
CONTRACT_DOC = (
    " The request is read as the legacy reads its arguments (ADR-0056): a field absent from the body takes the "
    "parameter's default, an explicit null stays null, text longer than the parameter is cut to its length and a "
    "decimal is brought to the parameter's scale."
)

_CONTRACT_HELPERS = (
    "\n    /** The field as the legacy takes the argument: absent takes the default, null stays null. */\n"
    "    private <T> T read(JsonNode body, String field, Class<T> type, T whenAbsent) {\n"
    "        if (body == null || !body.has(field)) {\n            return whenAbsent;\n        }\n"
    "        JsonNode node = body.get(field);\n"
    "        return node.isNull() ? null : mapper.convertValue(node, type);\n    }\n\n"
    "    private static String fit(String value, int length) {\n"
    "        return value != null && value.length() > length ? value.substring(0, length) : value;\n    }\n\n"
    "    private static java.math.BigDecimal scale(java.math.BigDecimal value, int digits) {\n"
    "        return value == null ? null : value.setScale(digits, java.math.RoundingMode.HALF_UP);\n    }\n"
)


def _java_literal(value: object, java: str) -> str:
    """A default of the legacy as a Java expression of the field's type."""
    if value is None:
        return "null"
    if java == "String":
        text = str(value).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{text}"'
    if java == "java.math.BigDecimal":
        return f'new java.math.BigDecimal("{value}")'
    if java in ("Long", "long"):
        return f"Long.valueOf({int(float(str(value)))}L)"
    if java in ("Integer", "int"):
        return f"Integer.valueOf({int(float(str(value)))})"
    if java in ("Boolean", "boolean"):
        return "Boolean.TRUE" if value in (True, 1, "1", "true", "True") else "Boolean.FALSE"
    if java == "java.time.LocalDate":
        return f'java.time.LocalDate.parse("{str(value)[:10]}")'
    if java == "java.time.LocalDateTime":
        return f'java.time.LocalDateTime.parse("{str(value).replace(" ", "T")}")'
    return "null"


def _contract(use_case: UseCase) -> tuple[str, str, str] | None:
    """(handler parameter, lines that build the request, helper methods) when the use case replaces a legacy program
    and takes a body: the request is built field by field from the JSON, with the semantics of the legacy's
    signature (ADR-0056). None for the other use cases (the record binds as before)."""
    if not use_case.legacy_program or use_case.http_method not in ("POST", "PUT", "PATCH"):
        return None
    arguments = []
    for field in use_case.inputs:
        java = java_type(field.type)
        value = nt.parse(field.type)
        absent = _java_literal(field.default, java) if field.defaulted else "null"
        read = f'read(body, "{field.name}", {java}.class, {absent})'
        if isinstance(value, nt.Text) and value.length:
            read = f"fit({read}, {value.length})"
        elif isinstance(value, nt.Decimal):
            read = f"scale({read}, {value.scale})"
        arguments.append(f"                {read}")
    built = ",\n".join(arguments)
    building = (
        f"        {use_case.name}Request request = new {use_case.name}Request(\n{built});\n"
        if arguments
        else f"        {use_case.name}Request request = new {use_case.name}Request();\n"
    )
    return "JsonNode body", building, _CONTRACT_HELPERS


def _service_owned_controller(design: Design, use_case: UseCase, unit: Port) -> str:
    """The REST adapter when the service owns the transaction (phase F): the legacy begins it after some work,
    commits or rolls back and still returns its status and outputs, so nothing wraps `execute`. The adapter only
    guards what the legacy's engine would: a failure that escapes undoes an open transaction, and a transaction
    still open when the use case returns is confirmed (as the caller's commit would)."""
    package = f"{design.base_package}.adapters.in.rest"
    service = f"{design.base_package}.application.{use_case.name}Service"
    adapter = f"{design.base_package}.adapters.out.jdbc.Jdbc{unit.name}"
    path = use_case.path or "/" + _snake(use_case.name).replace("_", "-")
    mapping = {"GET": "GetMapping", "POST": "PostMapping", "PUT": "PutMapping", "PATCH": "PatchMapping",
               "DELETE": "DeleteMapping"}[use_case.http_method]  # fmt: skip
    body = "@RequestBody " if use_case.http_method in ("POST", "PUT", "PATCH") else ""
    work = use_case.unit_of_work
    lines = ", ".join(f"rollback at {r.legacy_line}" for r in work.rollbacks) if work else ""
    doc = (f" The service owns the unit of work of the legacy (begin at {work.begins_at}, {lines}, commit at "
           f"{work.commits_at}) through the UnitOfWork port." if work else "")  # fmt: skip
    contract = _contract(use_case)
    parameter = f"{body}{use_case.name}Request request"
    building = helpers = imports = mapper_field = mapper_parameter = mapper_init = ""
    if contract is not None:
        parameter, building, helpers = contract
        parameter = f"@RequestBody(required = false) {parameter}"
        doc += CONTRACT_DOC
        imports = (
            "import com.fasterxml.jackson.databind.JsonNode;\nimport com.fasterxml.jackson.databind.ObjectMapper;\n"
        )
        mapper_field, mapper_parameter = "    private final ObjectMapper mapper;\n", ", ObjectMapper mapper"
        mapper_init = "        this.mapper = mapper;\n"
    return (
        f"package {package};\n\n{imports}import org.springframework.web.bind.annotation.*;\n\n"
        f"/** REST adapter of {use_case.name} (rules {', '.join(use_case.rules)}).{doc} */\n"
        f'@RestController\n@RequestMapping("/api/{design.context}")\n'
        f"public class {use_case.name}Controller {{\n\n"
        f"    private final {service} service;\n    private final {adapter} unitOfWork;\n{mapper_field}\n"
        f"    public {use_case.name}Controller({service} service, {adapter} unitOfWork{mapper_parameter}) {{\n"
        f"        this.service = service;\n        this.unitOfWork = unitOfWork;\n{mapper_init}    }}\n\n"
        f'    @{mapping}("{path}")\n'
        f"    public {use_case.name}Response handle({parameter}) {{\n"
        f"{building}"
        "        try {\n"
        f"            {use_case.name}Response response = service.execute(request);\n"
        "            unitOfWork.commitIfActive();\n            return response;\n"
        "        } catch (RuntimeException e) {\n"
        "            unitOfWork.rollbackIfActive();\n            throw e;\n        }\n    }\n"
        f"{helpers}}}\n"
    )


UNIT_OF_WORK_PORT = "UnitOfWork"
UNIT_OF_WORK_METHODS = ("begin", "commit", "rollback")
SP_STATUS = "nx_rc"
STATUS = "return"  # the reserved legacy name of a called program's return status (ADR-0055, phase F)


def unit_of_work_port(design: Design) -> Port | None:
    """The port the architect declares when the legacy has savepoints (ADR-0055): the platform implements it."""
    return next((p for p in design.ports if p.name == UNIT_OF_WORK_PORT and not p.legacy_program), None)


def owns_transaction(port: Port) -> bool:
    """Whether the UnitOfWork port begins, commits and rolls back (phase F): then the service owns the transaction
    and calls them where the legacy does; with savepoints only, the REST adapter wraps the use case."""
    declared = {m.name for m in port.methods}
    return all(m in declared for m in UNIT_OF_WORK_METHODS)


# ADR-0056 (phase B): the unit of work runs in the legacy's own transaction mode. `begin tran`, `commit tran` and
# `rollback tran` are sent as T-SQL on one connection of the request's thread, with autocommit on (Sybase's
# unchained mode, the mode the legacy's procedures and the ones they call were written for), instead of a JDBC
# transaction (chained mode, which the legacy never ran in and which a called procedure may refuse). The connection
# is bound to the thread so every JdbcTemplate call of the request, and every called program, runs on it.
_TRANSACTION_METHODS = (
    "    @Override\n    public void begin() {\n"
    "        if (open.get() != null) {\n"
    '            throw new IllegalStateException("the transaction is already open");\n        }\n'
    "        DataSource dataSource = java.util.Objects.requireNonNull(jdbc.getDataSource());\n"
    "        boolean bound = TransactionSynchronizationManager.hasResource(dataSource);\n"
    "        Connection connection = DataSourceUtils.getConnection(dataSource);\n"
    "        if (!bound) {\n"
    "            ConnectionHolder holder = new ConnectionHolder(connection);\n"
    "            holder.setSynchronizedWithTransaction(true);\n"
    "            TransactionSynchronizationManager.bindResource(dataSource, holder);\n"
    "        }\n"
    "        open.set(connection);\n        ownsBinding.set(!bound);\n        marks.remove();\n"
    '        run(connection, "begin tran");\n'
    "    }\n\n"
    "    @Override\n    public void commit() {\n"
    "        Connection connection = open.get();\n"
    "        if (connection == null) {\n"
    '            throw new IllegalStateException("no transaction to commit");\n        }\n'
    '        try {\n            run(connection, "commit tran");\n        } finally {\n'
    "            release(connection);\n        }\n    }\n\n"
    "    @Override\n    public void rollback() {\n"
    "        Connection connection = open.get();\n"
    "        if (connection == null) {\n"
    '            throw new IllegalStateException("no transaction to roll back");\n        }\n'
    '        try {\n            run(connection, "rollback tran");\n        } finally {\n'
    "            release(connection);\n        }\n    }\n\n"
    "    /** Confirms a transaction the use case left open (the caller's commit, in the legacy); nothing when the "
    "use case already closed it on the engine. */\n"
    "    public void commitIfActive() {\n"
    "        Connection connection = open.get();\n"
    "        if (connection != null) {\n"
    '            try {\n                run(connection, "if @@trancount > 0 commit tran");\n'
    "            } finally {\n                release(connection);\n            }\n        }\n    }\n\n"
    "    /** Undoes a transaction a failure left open (the engine's rollback when a batch aborts). */\n"
    "    public void rollbackIfActive() {\n"
    "        Connection connection = open.get();\n"
    "        if (connection != null) {\n"
    '            try {\n                run(connection, "if @@trancount > 0 rollback tran");\n'
    "            } finally {\n                release(connection);\n            }\n        }\n    }\n\n"
    "    private void release(Connection connection) {\n"
    "        DataSource dataSource = java.util.Objects.requireNonNull(jdbc.getDataSource());\n"
    "        boolean owned = Boolean.TRUE.equals(ownsBinding.get());\n"
    "        open.remove();\n        ownsBinding.remove();\n        marks.remove();\n"
    "        if (owned) {\n"
    "            TransactionSynchronizationManager.unbindResource(dataSource);\n"
    "            DataSourceUtils.releaseConnection(connection, dataSource);\n"
    "        }\n    }\n\n"
    "    private static void run(Connection connection, String sql) {\n"
    "        try (java.sql.Statement statement = connection.createStatement()) {\n"
    "            statement.execute(sql);\n"
    "        } catch (SQLException e) {\n"
    '            throw new IllegalStateException(sql + ": " + e.getMessage(), e);\n'
    "        }\n    }\n\n"
)


def unit_of_work_adapter_file(design: Design, port: Port) -> tuple[str, str]:
    """Savepoints on the connection of the current transaction: `savepoint(name)` marks, `rollbackTo(name)` undoes
    the work since the mark and the use case goes on, as the legacy's `rollback tran <savepoint>` does. When the
    port also declares `begin`, `commit` and `rollback` (phase F) the adapter owns the transaction as T-SQL on a
    connection bound to the request's thread, in the legacy's transaction mode (ADR-0056, phase B), so the service
    begins and ends it exactly where and how the legacy does."""
    package = f"{design.base_package}.adapters.out.jdbc"
    owns = owns_transaction(port)
    transaction_imports = (
        "import javax.sql.DataSource;\n"
        "import org.springframework.jdbc.datasource.ConnectionHolder;\n"
        "import org.springframework.transaction.support.TransactionSynchronizationManager;\n"
        if owns
        else ""
    )
    transaction_fields = (
        "    private final ThreadLocal<Connection> open = new ThreadLocal<>();\n"
        "    private final ThreadLocal<Boolean> ownsBinding = new ThreadLocal<>();\n"
        if owns
        else ""
    )
    transaction_init = ""
    doc = ("the unit of work of the legacy (begin, commit, rollback and its savepoints), owned by the service and "
           "run as T-SQL in the legacy's transaction mode"
           if owns else "the savepoints of the legacy on the transaction of the use case")  # fmt: skip
    return adapter_path(design, port), (
        f"package {package};\n\n"
        f"import {design.base_package}.domain.port.{port.name};\n"
        "import java.sql.Connection;\nimport java.sql.SQLException;\n"
        "import java.util.HashSet;\nimport java.util.Set;\n"
        "import org.springframework.jdbc.core.JdbcTemplate;\n"
        "import org.springframework.jdbc.datasource.DataSourceUtils;\n"
        f"{transaction_imports}"
        "import org.springframework.stereotype.Repository;\n\n"
        f"/** Generated by the platform (ADR-0055): {doc}. The marks and the transaction belong to the request's "
        "thread (ADR-0056): two concurrent requests never see each other's savepoints. */\n"
        f"@Repository\npublic class Jdbc{port.name} implements {port.name} {{\n\n"
        "    private final JdbcTemplate jdbc;\n"
        "    private final ThreadLocal<Set<String>> marks = ThreadLocal.withInitial(HashSet::new);\n"
        f"{transaction_fields}\n"
        f"    public Jdbc{port.name}(JdbcTemplate jdbc) {{\n        this.jdbc = jdbc;\n{transaction_init}    }}\n\n"
        f"{_TRANSACTION_METHODS if owns else ''}"
        "    @Override\n    public void savepoint(String name) {\n"
        '        try {\n            jdbc.execute("save tran " + label(name));\n            marks.get().add(name);\n'
        "        } catch (org.springframework.dao.DataAccessException e) {\n"
        '            throw new IllegalStateException("savepoint " + name + ": " + e.getMessage(), e);\n'
        "        }\n    }\n\n"
        "    @Override\n    public void rollbackTo(String name) {\n"
        "        if (!marks.get().contains(name)) {\n"
        '            throw new IllegalStateException("no savepoint " + name);\n        }\n'
        '        try {\n            jdbc.execute("rollback tran " + label(name));\n'
        "        } catch (org.springframework.dao.DataAccessException e) {\n"
        '            throw new IllegalStateException("rollback to " + name + ": " + e.getMessage(), e);\n'
        "        }\n    }\n\n"
        "    private Connection connection() {\n"
        "        return DataSourceUtils.getConnection(java.util.Objects.requireNonNull(jdbc.getDataSource()));\n"
        "    }\n\n"
        "    private static String label(String name) {\n"
        '        if (!name.matches("[A-Za-z_][A-Za-z0-9_]*")) {\n'
        '            throw new IllegalArgumentException("savepoint name " + name);\n        }\n'
        "        return name;\n"
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
        carries_status = method.legacy_output == STATUS or STATUS in method.legacy_outputs.values()
        if method.legacy_outputs and entity is not None:
            by_name = {f.name: f for f in entity.fields}
            outputs = [(legacy, legacy.lstrip("@"), by_name[field].type)
                       for field, legacy in method.legacy_outputs.items()
                       if field in by_name and legacy != STATUS]  # fmt: skip
        elif method.legacy_output and method.legacy_output != STATUS:
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
                f"{_from_row('(Object) status', java_type(f.type))}"
                if method.legacy_outputs.get(f.name) == STATUS
                else f'nullable(row.get("{legacy.lstrip("@")}"), v -> {_from_row("v", java_type(f.type))})'
                if (legacy := method.legacy_outputs.get(f.name))
                else "null"
                for f in entity.fields
            )
            answer = f"return java.util.Optional.of(new {entity.name}({built}));"
        elif method.legacy_output == STATUS and method.returns in ("int", "long", "boolean"):
            result = method.returns
            answer = {"int": "return status;", "long": "return (long) status;", "boolean": "return status == 0;"}[
                method.returns
            ]
        elif outputs:
            java = {"boolean": "boolean", "int": "int", "long": "long"}[method.returns or "int"]
            result = java
            fallback = {"boolean": "false", "int": "0", "long": "0L"}[java]
            answer = (f"Object value = row.get(\"{outputs[0][1]}\");\n"
                      f"        return value == null ? {fallback} : {_from_row('value', java)};")  # fmt: skip
        elif method.returns in ("int", "long", "boolean"):
            # No output parameter: the method returns the program's return status (ADR-0055, phase F).
            result = method.returns
            answer = {"int": "return status;", "long": "return (long) status;", "boolean": "return status == 0;"}[
                method.returns
            ]
        else:
            result = "void"
            answer = ""
        carries_status = carries_status or (method.returns in ("int", "long", "boolean") and not outputs)
        # A method that carries the status returns it as data, as the legacy reads it; one that cannot carry it
        # fails on a non-zero status (ADR-0055, phase F).
        failure = (
            ""
            if carries_status
            else (
                f"        if (status != 0) {{\n"
                f'            throw new IllegalStateException("{program} answered " + status);\n'
                "        }\n"
            )
        )
        methods.append(
            f"    @Override\n    public {result} {method.name}({params}) {{\n"
            f'        java.util.Map<String, Object> row = call(\n            "{batch}"{binds});\n'
            f'        int status = ((Number) row.get("{SP_STATUS}")).intValue();\n'
            + failure
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
        "transaction of the use case; its return status decides, its output parameters come back. The messages it "
        "raises (ADR-0056) are kept for the caller and never abort the call, as the legacy engine does not abort "
        "the caller of a procedure that raises. */\n"
        f"@Repository\npublic class Jdbc{port.name} implements {port.name} {{\n\n"
        "    private final JdbcTemplate jdbc;\n"
        "    private final ThreadLocal<java.util.List<String>> raised = "
        "ThreadLocal.withInitial(java.util.ArrayList::new);\n\n"
        f"    public Jdbc{port.name}(JdbcTemplate jdbc) {{\n        this.jdbc = jdbc;\n    }}\n\n"
        "    /** The messages the last call of this thread raised (raiserror), oldest first. */\n"
        "    public java.util.List<String> messages() {\n"
        "        return java.util.List.copyOf(raised.get());\n    }\n\n"
        + "\n".join(methods)
        + CALL_HELPER
        + "\n    private static <T> T nullable(Object value, java.util.function.Function<Object, T> convert) {\n"
        "        return value == null ? null : convert.apply(value);\n    }\n}\n"
    )


# The batch of a legacy program may return result sets of its own (a substitute prints the call it received, a real
# procedure may select rows) before the final SELECT with the status: the row that carries the status is the answer.
# An error the program raises (raiserror) reaches the driver as an SQLException between results (ADR-0056): it is
# kept as a message and the reading goes on to the status, as the legacy caller goes on; only a lost connection
# (SQLState 08xxx) or a batch with no status at all fails the call.
CALL_HELPER = (
    "\n    /** Runs the batch and returns the row of its last SELECT (the status and the outputs); the program's own"
    " result sets are skipped and its raised messages are kept in {@link #messages()}. */\n"
    "    private java.util.Map<String, Object> call(String batch, Object... arguments) {\n"
    "        raised.get().clear();\n"
    "        java.util.Map<String, Object> found = jdbc.execute("
    "(org.springframework.jdbc.core.ConnectionCallback<java.util.Map<String, Object>>) connection -> {\n"
    "            try (java.sql.PreparedStatement statement = connection.prepareStatement(batch)) {\n"
    "                for (int i = 0; i < arguments.length; i++) {\n"
    "                    statement.setObject(i + 1, arguments[i]);\n                }\n"
    "                java.util.Map<String, Object> last = null;\n"
    "                boolean results;\n"
    "                try {\n                    results = statement.execute();\n"
    "                } catch (java.sql.SQLException e) {\n"
    "                    keep(e);\n                    results = statement.getMoreResults();\n                }\n"
    "                while (true) {\n"
    "                    try {\n"
    "                        if (results) {\n"
    "                            try (java.sql.ResultSet rs = statement.getResultSet()) {\n"
    "                                java.sql.ResultSetMetaData meta = rs.getMetaData();\n"
    "                                if (rs.next()) {\n"
    "                                    java.util.Map<String, Object> row = new java.util.LinkedHashMap<>();\n"
    "                                    for (int c = 1; c <= meta.getColumnCount(); c++) {\n"
    "                                        row.put(meta.getColumnLabel(c), rs.getObject(c));\n"
    "                                    }\n"
    f'                                    if (row.containsKey("{SP_STATUS}")) {{\n'
    "                                        last = row;\n"
    "                                    }\n                                }\n                            }\n"
    "                        } else if (statement.getUpdateCount() == -1) {\n"
    "                            break;\n                        }\n"
    "                        results = statement.getMoreResults();\n"
    "                    } catch (java.sql.SQLException e) {\n"
    "                        keep(e);\n                        results = statement.getMoreResults();\n"
    "                    }\n                }\n"
    "                return last;\n            }\n        });\n"
    "        if (found == null) {\n"
    '            throw new IllegalStateException("the program returned no status"\n'
    '                    + (raised.get().isEmpty() ? "" : ": " + String.join("; ", raised.get())));\n        }\n'
    "        return found;\n    }\n\n"
    "    /** A message the program raised is kept; a connection failure is not a message of the program. */\n"
    "    private void keep(java.sql.SQLException e) throws java.sql.SQLException {\n"
    '        if (e.getSQLState() != null && e.getSQLState().startsWith("08")) {\n'
    "            throw e;\n        }\n"
    "        for (java.sql.SQLException next = e; next != null; next = next.getNextException()) {\n"
    '            raised.get().add(next.getErrorCode() + ": " + next.getMessage());\n        }\n    }\n'
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


def skeleton(
    design: Design, spring_boot_version: str = SPRING_BOOT_VERSION, transactional: bool = True
) -> dict[str, str]:
    """The deterministic files by layer: contracts, domain (model, ports, error), adapters (REST), orchestration.
    `transactional`: the REST adapter opens the unit of work (False for a persistence with its own transaction)."""
    files: dict[str, str] = dict(
        [pom_file(design, spring_boot_version), application_file(design), error_file(design), schema_file(design)]
    )
    for entity in design.entities:
        files.update([entity_file(design, entity)])
    for port in design.ports:
        files.update([port_file(design, port)])
    for use_case in design.use_cases:
        files.update(contract_files(design, use_case))
        files.update([controller_file(design, use_case, transactional)])
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
