# ruff: noqa: E501 - the lines of generated Go are kept whole, so the code reads like the file it writes
"""Deterministic generators of the Go pack (spec 8.4, ADR-0029): everything that follows from the design without
judgement. The layout is the idiomatic one of a Go service, hexagonal inside (D-05), not a translation of the Java
pack:

    go.mod, go.sum                       the module and its exact libraries (the ones the sandbox image caches)
    cmd/server/main.go                   the wiring: the pool, one adapter per port, one service per use case
    internal/domain                      entities (structs with exact types), BusinessError, value helpers
    internal/ports                       ports to persistence and external programs (interfaces)
    internal/app                         request/response of each use case and its service  <- the service is
                                         written by the backend developer agent, its tests by the test engineer
    internal/adapters/httpapi            net/http handlers with encoding/json, one transaction per request
    internal/adapters/pg                 database/sql with the pgx driver: the shared DB and the adapters  <- agent
    db/schema.sql                        PostgreSQL schema (from the entities, as the Spring Boot pack writes it)

Neutral types map to Go types here (4.3). The values can be null in the legacy, so every field is a pointer
(`decimal(p,s)` -> *decimal.Decimal, `integer(32)` -> *int32, `text` -> *string, `timestamp` -> *time.Time...),
which database/sql scans and binds as NULL when nil; binary is a []byte (nil is NULL).
"""

from nexti_core.spec import neutral_types as nt
from nexti_core.spec.design import Design, Entity, FieldSpec, Port, PortMethod, UseCase
from nexti_core.spec.equivalence import snake
from nexti_pack_spring_boot.generate import schema_file as postgresql_schema
from nexti_pack_spring_boot.generate import sql_type

__all__ = ["sql_type"]

GO_VERSION = "1.26"
DECIMAL = "github.com/shopspring/decimal"
PGX_STDLIB = "github.com/jackc/pgx/v5/stdlib"
# The exact module versions cached in the sandbox image (infra/sandbox/go/seed/go.mod and go.sum): keep them equal.
REQUIRE = {"github.com/jackc/pgx/v5": "v5.11.0", DECIMAL: "v1.4.0"}
INDIRECT = {
    "github.com/jackc/pgpassfile": "v1.0.0",
    "github.com/jackc/pgservicefile": "v0.0.0-20240606120523-5a60cdf6a761",
    "github.com/jackc/puddle/v2": "v2.2.2",
    "golang.org/x/sync": "v0.17.0",
    "golang.org/x/text": "v0.29.0",
}
GO_SUM = """github.com/davecgh/go-spew v1.1.0/go.mod h1:J7Y8YcW2NihsgmVo/mv3lAwl/skON4iLHjSsI+c5H38=
github.com/davecgh/go-spew v1.1.1 h1:vj9j/u1bqnvCEfJOwUhtlOARqs3+rkHYY13jYWTU97c=
github.com/davecgh/go-spew v1.1.1/go.mod h1:J7Y8YcW2NihsgmVo/mv3lAwl/skON4iLHjSsI+c5H38=
github.com/jackc/pgpassfile v1.0.0 h1:/6Hmqy13Ss2zCq62VdNG8tM1wchn8zjSGOBJ6icpsIM=
github.com/jackc/pgpassfile v1.0.0/go.mod h1:CEx0iS5ambNFdcRtxPj5JhEz+xB6uRky5eyVu/W2HEg=
github.com/jackc/pgservicefile v0.0.0-20240606120523-5a60cdf6a761 h1:iCEnooe7UlwOQYpKFhBabPMi4aNAfoODPEFNiAnClxo=
github.com/jackc/pgservicefile v0.0.0-20240606120523-5a60cdf6a761/go.mod h1:5TJZWKEWniPve33vlWYSoGYefn3gLQRzjfDlhSJ9ZKM=
github.com/jackc/pgx/v5 v5.11.0 h1:IzBBtyK9AHqf98cctWFifYSci2hgQR/cd56wB4p+ogg=
github.com/jackc/pgx/v5 v5.11.0/go.mod h1:mal1tBGAFfLHvZzaYh77YS/eC6IX9OWbRV1QIIM0Jn4=
github.com/jackc/puddle/v2 v2.2.2 h1:PR8nw+E/1w0GLuRFSmiioY6UooMp6KJv0/61nB7icHo=
github.com/jackc/puddle/v2 v2.2.2/go.mod h1:vriiEXHvEE654aYKXXjOvZM39qJ0q+azkZFrfEOc3H4=
github.com/pmezard/go-difflib v1.0.0 h1:4DBwDE0NGyQoBHbLQYPwSUPoCMWR5BEzIk/f1lZbAQM=
github.com/pmezard/go-difflib v1.0.0/go.mod h1:iKH77koFhYxTK1pcRnkKkqfTogsbg7gZNVY4sRDYZ/4=
github.com/shopspring/decimal v1.4.0 h1:bxl37RwXBklmTi0C79JfXCEBD1cqqHt0bbgBAGFp81k=
github.com/shopspring/decimal v1.4.0/go.mod h1:gawqmDU56v4yIKSwfBSFip1HdCCXN8/+DMd9qYNcwME=
github.com/stretchr/objx v0.1.0/go.mod h1:HFkY916IF+rwdDfMAkV7OtwuqBVzrE8GR6GFx+wExME=
github.com/stretchr/testify v1.3.0/go.mod h1:M5WIy9Dh21IEIfnGCwXGc5bZfKNJtfHm1UVUgZn+9EI=
github.com/stretchr/testify v1.7.0/go.mod h1:6Fq8oRcR53rry900zMqJjRRixrwX3KX962/h/Wwjteg=
github.com/stretchr/testify v1.11.1 h1:7s2iGBzp5EwR7/aIZr8ao5+dra3wiQyKjjFuvgVKu7U=
github.com/stretchr/testify v1.11.1/go.mod h1:wZwfW3scLgRK+23gO65QZefKpKQRnfz6sD981Nm4B6U=
golang.org/x/sync v0.17.0 h1:l60nONMj9l5drqw6jlhIELNv9I0A4OFgRsG9k2oT9Ug=
golang.org/x/sync v0.17.0/go.mod h1:9KTHXmSnoGruLpwFjVSX0lNNA75CykiMECbovNTZqGI=
golang.org/x/text v0.29.0 h1:1neNs90w9YzJ9BocxfsQNHKuAT4pkghyXc4nhZ6sJvk=
golang.org/x/text v0.29.0/go.mod h1:7MhJOA9CD2qZyOKYazxdYMF85OwPdEr9jTtBpO7ydH4=
gopkg.in/check.v1 v0.0.0-20161208181325-20d25e280405/go.mod h1:Co6ibVJAznAaIkqp8huTwlJQCZ016jof/cbN4VW5Yz0=
gopkg.in/yaml.v3 v3.0.0-20200313102051-9f266ea9e77c/go.mod h1:K4uyk7z7BCEPqu6E+C64Yfv1cQ7kz7rIZviUmN+EgEM=
gopkg.in/yaml.v3 v3.0.1 h1:fxVm/GzAzEWqLHuvctI91KS9hhNmmWOoWu0XTYJS7CA=
gopkg.in/yaml.v3 v3.0.1/go.mod h1:K4uyk7z7BCEPqu6E+C64Yfv1cQ7kz7rIZviUmN+EgEM=
"""

SCHEMA = "db/schema.sql"
DOMAIN = "internal/domain"
PORTS = "internal/ports"
APP = "internal/app"
HTTP = "internal/adapters/httpapi"
PG = "internal/adapters/pg"
SERVER = "cmd/server/main.go"
PROBE = "internal/probe/probe.go"
KEYWORDS = {
    "break", "case", "chan", "const", "continue", "default", "defer", "else", "fallthrough", "for", "func", "go",
    "goto", "if", "import", "interface", "map", "package", "range", "return", "select", "struct", "switch", "type",
    "var",
}  # fmt: skip
# Names a parameter must not take in generated code: Go keywords, and the packages and variables the files use.
_TAKEN = KEYWORDS | {"ctx", "context", "decimal", "time", "domain", "ports", "app", "pg", "db", "err", "error"}
_SHORT = {"type": "typ", "func": "fn", "range": "rng", "map": "mapping", "package": "pkg", "interface": "iface"}


def pascal(name: str) -> str:
    return name[:1].upper() + name[1:]


def ident(name: str) -> str:
    """A Go parameter or variable: lower camel case, renamed when Go or the generated files reserve the name."""
    lowered = name[:1].lower() + name[1:]
    if lowered in _TAKEN:
        return _SHORT.get(lowered, lowered + "Value")
    return lowered


def module_path(design: Design) -> str:
    """The module path: the base package with its reversed domain put back (`com.bancoficticio.payments` is
    `bancoficticio.com/payments`); a base package without one is its parts joined by slashes."""
    parts = design.base_package.split(".")
    if len(parts) > 2 and parts[0] in ("com", "org", "net", "io"):
        return f"{parts[1]}.{parts[0]}/" + "/".join(parts[2:])
    return "/".join(parts)


def go_type(neutral: str) -> str:
    value = nt.parse(neutral)
    if isinstance(value, nt.Decimal):
        return "*decimal.Decimal"
    if isinstance(value, nt.Integer):
        return "*int64" if value.bits == 64 or (value.bits == 32 and not value.signed) else "*int32"
    if isinstance(value, nt.Text | nt.Enum):
        return "*string"
    if isinstance(value, nt.Date | nt.Timestamp):
        return "*time.Time"
    if isinstance(value, nt.Boolean):
        return "*bool"
    return "[]byte"


def zoned(neutral: str) -> bool:
    """Whether the value carries its offset (timestamp with time zone)."""
    value = nt.parse(neutral)
    return isinstance(value, nt.Timestamp) and value.tz


def _imports(std: list[str], external: list[str], local: list[str]) -> str:
    groups = [sorted(set(std)), sorted(set(external)), sorted(set(local))]
    lines = "\n\n".join("\n".join(f'\t"{i}"' for i in g) for g in groups if g)
    if not lines:
        return ""
    return f"import (\n{lines}\n)\n\n"


def _type_imports(types: list[str]) -> tuple[list[str], list[str]]:
    std = ["time"] if any("time.Time" in t for t in types) else []
    external = [DECIMAL] if any("decimal.Decimal" in t for t in types) else []
    return std, external


def _struct(name: str, fields: list[FieldSpec], doc: str, tags: bool) -> str:
    if not fields:
        return f"// {doc}\ntype {name} struct{{}}\n"
    width = max(len(pascal(f.name)) for f in fields)
    type_width = max(len(go_type(f.type)) for f in fields)
    lines = []
    for field in fields:
        line = f"\t{pascal(field.name).ljust(width)} {go_type(field.type)}"
        if tags:
            line = f'\t{pascal(field.name).ljust(width)} {go_type(field.type).ljust(type_width)} `json:"{field.name}"`'
        lines.append(line)
    body = "\n".join(lines)
    return f"// {doc}\ntype {name} struct {{\n{body}\n}}\n"


def entity_file(design: Design, entity: Entity) -> tuple[str, str]:
    std, external = _type_imports([go_type(f.type) for f in entity.fields])
    origin = f" (legacy table {entity.legacy_table})" if entity.legacy_table else ""
    doc = f"{entity.name} is the entity {entity.name}{origin}."
    return f"{DOMAIN}/{snake(entity.name)}.go", (
        f"package domain\n\n{_imports(std, external, [])}{_struct(entity.name, entity.fields, doc, tags=False)}"
    )


def domain_files(design: Design) -> list[tuple[str, str]]:
    return [
        (f"{DOMAIN}/doc.go",
         "// Package domain holds the entities of the design and the business error: no framework, no database.\n"
         "package domain\n"),
        (f"{DOMAIN}/errors.go",
         "package domain\n\n"
         "// BusinessError is a business rejection with its stable code and the code the legacy returned. The REST\n"
         "// adapter answers it as 422 with both codes; any other error is a failure of the service.\n"
         "type BusinessError struct {\n\tCode       string\n\tLegacyCode string\n\tMessage    string\n}\n\n"
         "// NewBusinessError is the rejection with the codes the design gives it.\n"
         "func NewBusinessError(code, legacyCode, message string) *BusinessError {\n"
         "\treturn &BusinessError{Code: code, LegacyCode: legacyCode, Message: message}\n}\n\n"
         "func (e *BusinessError) Error() string {\n\treturn e.Code + \": \" + e.Message\n}\n"),
        (f"{DOMAIN}/values.go",
         "package domain\n\n"
         "// Ptr is a pointer to v: the fields of the entities and contracts are pointers because a value can be null.\n"
         "func Ptr[T any](v T) *T {\n\treturn &v\n}\n\n"
         "// Deref is the value p points to, or the zero value of T when p is nil (null).\n"
         "func Deref[T any](p *T) T {\n\tif p == nil {\n\t\tvar zero T\n\t\treturn zero\n\t}\n\treturn *p\n}\n"),
    ]  # fmt: skip


def _go_return(returns: str | None, design: Design) -> str:
    if returns is None:
        return "error"
    if returns in {e.name for e in design.entities}:
        return f"(*domain.{returns}, error)"
    return "(" + {"boolean": "bool", "int": "int", "long": "int64"}[returns] + ", error)"


def method_signature(method: PortMethod, design: Design) -> str:
    params = "".join(f", {ident(p.name)} {go_type(p.type)}" for p in method.inputs)
    return f"{pascal(method.name)}(ctx context.Context{params}) {_go_return(method.returns, design)}"


def port_file(design: Design, port: Port) -> tuple[str, str]:
    types = [go_type(p.type) for m in port.methods for p in m.inputs]
    std, external = _type_imports(types)
    entities = {e.name for e in design.entities}
    local = [f"{module_path(design)}/{DOMAIN}"] if any(m.returns in entities for m in port.methods) else []
    methods = []
    for method in port.methods:
        doc = f"\t// {pascal(method.name)}: {method.description}\n" if method.description else ""
        methods.append(f"{doc}\t{method_signature(method, design)}")
    kind = f"an external program ({port.legacy_program})" if port.legacy_program else "persistence"
    return f"{PORTS}/{snake(port.name)}.go", (
        f"package ports\n\n{_imports(['context', *std], external, local)}"
        f"// {port.name} is a port to {kind} (hexagonal: the domain does not know the adapter).\n"
        f"type {port.name} interface {{\n" + "\n".join(methods) + "\n}\n"
    )


def ports_doc() -> tuple[str, str]:
    return f"{PORTS}/doc.go", (
        "// Package ports holds the interfaces the use case services need: persistence and external programs. Every\n"
        "// method takes the context of the request, which carries its transaction to the adapters.\n"
        "package ports\n"
    )


def contract_file(design: Design, use_case: UseCase) -> tuple[str, str]:
    types = [go_type(f.type) for f in [*use_case.inputs, *use_case.outputs]]
    std, external = _type_imports(types)
    request = _struct(
        f"{use_case.name}Request",
        use_case.inputs,
        f"{use_case.name}Request is the request of {use_case.name}.",
        tags=True,
    )
    response = _struct(
        f"{use_case.name}Response",
        use_case.outputs,
        f"{use_case.name}Response is the response of {use_case.name}.",
        tags=True,
    )
    return (
        f"{APP}/{snake(use_case.name)}_contract.go",
        f"package app\n\n{_imports(std, external, [])}{request}\n{response}",
    )


def app_doc(design: Design) -> tuple[str, str]:
    return f"{APP}/doc.go", (
        "// Package app holds one service per use case, with its request and response: plain structs that take the\n"
        "// ports in their constructor and run the business rules. The wiring and the REST handlers are generated.\n"
        "package app\n"
    )


def db_file(design: Design) -> tuple[str, str]:
    return f"{PG}/db.go", (
        "// Package pg holds the PostgreSQL adapters of the ports: database/sql with the pgx driver.\n"
        "package pg\n\n"
        f'import (\n\t"context"\n\t"database/sql"\n\t"fmt"\n\n\t_ "{PGX_STDLIB}" // the "pgx" driver of database/sql\n)\n\n'
        "// Querier runs SQL: the transaction of the current request when there is one, otherwise the pool.\n"
        "type Querier interface {\n"
        "\tExecContext(ctx context.Context, query string, args ...any) (sql.Result, error)\n"
        "\tQueryContext(ctx context.Context, query string, args ...any) (*sql.Rows, error)\n"
        "\tQueryRowContext(ctx context.Context, query string, args ...any) *sql.Row\n}\n\n"
        "// DB is the pool the adapters share; the transaction of a request travels in its context.\n"
        "type DB struct {\n\tpool *sql.DB\n}\n\n"
        "// Open opens the pool on a PostgreSQL URL (postgres://user@host:5432/database).\n"
        "func Open(url string) (*DB, error) {\n"
        '\tpool, err := sql.Open("pgx", url)\n\tif err != nil {\n\t\treturn nil, fmt.Errorf("open the database: %w", err)\n\t}\n'
        "\treturn &DB{pool: pool}, nil\n}\n\n"
        "// Pool is the underlying pool.\nfunc (db *DB) Pool() *sql.DB {\n\treturn db.pool\n}\n\n"
        "// Close closes the pool.\nfunc (db *DB) Close() error {\n\treturn db.pool.Close()\n}\n\n"
        "type txKey struct{}\n\n"
        "// InTx runs fn inside one transaction: committed when fn returns nil, rolled back when it returns an error or\n"
        "// panics, so a rejection undoes every write of the use case.\n"
        "func (db *DB) InTx(ctx context.Context, fn func(ctx context.Context) error) error {\n"
        "\ttx, err := db.pool.BeginTx(ctx, nil)\n"
        '\tif err != nil {\n\t\treturn fmt.Errorf("begin the transaction: %w", err)\n\t}\n'
        "\tdefer func() {\n\t\tif recovered := recover(); recovered != nil {\n\t\t\t_ = tx.Rollback()\n\t\t\tpanic(recovered)\n\t\t}\n\t}()\n"
        "\tif err := fn(context.WithValue(ctx, txKey{}, tx)); err != nil {\n\t\t_ = tx.Rollback()\n\t\treturn err\n\t}\n"
        '\tif err := tx.Commit(); err != nil {\n\t\treturn fmt.Errorf("commit the transaction: %w", err)\n\t}\n'
        "\treturn nil\n}\n\n"
        "// Q is what an adapter runs its SQL on: the transaction ctx carries, or the pool outside one.\n"
        "func (db *DB) Q(ctx context.Context) Querier {\n"
        "\tif tx, ok := ctx.Value(txKey{}).(*sql.Tx); ok {\n\t\treturn tx\n\t}\n\treturn db.pool\n}\n"
    )


def http_file(design: Design) -> tuple[str, str]:
    """What every handler shares: the transaction, the JSON answers, the error mapping and the query parameters."""
    local = [f"{module_path(design)}/{DOMAIN}"]
    std = ["context", "encoding/hex", "encoding/json", "errors", "net/http", "net/url", "strconv", "time"]
    return f"{HTTP}/http.go", (
        "// Package httpapi holds the REST adapters: net/http handlers that decode the request, run the use case in\n"
        "// one transaction and encode the response with encoding/json.\n"
        f"package httpapi\n\n{_imports(std, [DECIMAL], local)}"
        "// Transactor runs a use case inside one transaction (pg.DB is one).\n"
        "type Transactor interface {\n\tInTx(ctx context.Context, fn func(ctx context.Context) error) error\n}\n\n"
        "type badRequest struct {\n\terr error\n}\n\n"
        "func (b badRequest) Error() string {\n\treturn b.err.Error()\n}\n\n"
        "func writeJSON(w http.ResponseWriter, status int, body any) {\n"
        '\tw.Header().Set("Content-Type", "application/json")\n\tw.WriteHeader(status)\n\t_ = json.NewEncoder(w).Encode(body)\n}\n\n'
        "// writeError answers a business rejection as 422 with its codes (the contract's BusinessError), a malformed\n"
        "// request as 400 and anything else as 500, without its detail.\n"
        "func writeError(w http.ResponseWriter, err error) {\n"
        "\tvar rejection *domain.BusinessError\n\tvar malformed badRequest\n\tswitch {\n"
        "\tcase errors.As(err, &rejection):\n"
        '\t\twriteJSON(w, http.StatusUnprocessableEntity, map[string]string{\n\t\t\t"code": rejection.Code, "legacyCode": rejection.LegacyCode, "message": rejection.Message,\n\t\t})\n'
        "\tcase errors.As(err, &malformed):\n"
        '\t\twriteJSON(w, http.StatusBadRequest, map[string]string{"code": "BAD_REQUEST", "message": malformed.Error()})\n'
        "\tdefault:\n"
        '\t\twriteJSON(w, http.StatusInternalServerError, map[string]string{"code": "INTERNAL", "message": "internal error"})\n'
        "\t}\n}\n\n"
        'func query(q url.Values, name string) (string, bool) {\n\tif !q.Has(name) {\n\t\treturn "", false\n\t}\n\treturn q.Get(name), true\n}\n\n'
        "func queryString(q url.Values, name string) (*string, error) {\n"
        "\tif text, ok := query(q, name); ok {\n\t\treturn &text, nil\n\t}\n\treturn nil, nil\n}\n\n"
        "func queryInt32(q url.Values, name string) (*int32, error) {\n"
        "\ttext, ok := query(q, name)\n\tif !ok {\n\t\treturn nil, nil\n\t}\n"
        "\tvalue, err := strconv.ParseInt(text, 10, 32)\n\tif err != nil {\n\t\treturn nil, badRequest{err}\n\t}\n"
        "\tnarrow := int32(value)\n\treturn &narrow, nil\n}\n\n"
        "func queryInt64(q url.Values, name string) (*int64, error) {\n"
        "\ttext, ok := query(q, name)\n\tif !ok {\n\t\treturn nil, nil\n\t}\n"
        "\tvalue, err := strconv.ParseInt(text, 10, 64)\n\tif err != nil {\n\t\treturn nil, badRequest{err}\n\t}\n\treturn &value, nil\n}\n\n"
        "func queryDecimal(q url.Values, name string) (*decimal.Decimal, error) {\n"
        "\ttext, ok := query(q, name)\n\tif !ok {\n\t\treturn nil, nil\n\t}\n"
        "\tvalue, err := decimal.NewFromString(text)\n\tif err != nil {\n\t\treturn nil, badRequest{err}\n\t}\n\treturn &value, nil\n}\n\n"
        "func queryBool(q url.Values, name string) (*bool, error) {\n"
        "\ttext, ok := query(q, name)\n\tif !ok {\n\t\treturn nil, nil\n\t}\n"
        "\tvalue, err := strconv.ParseBool(text)\n\tif err != nil {\n\t\treturn nil, badRequest{err}\n\t}\n\treturn &value, nil\n}\n\n"
        "// queryTime takes RFC 3339, a local date and time (2006-01-02T15:04:05) or a date.\n"
        "func queryTime(q url.Values, name string) (*time.Time, error) {\n"
        "\ttext, ok := query(q, name)\n\tif !ok {\n\t\treturn nil, nil\n\t}\n"
        '\tfor _, layout := range []string{time.RFC3339Nano, "2006-01-02T15:04:05.999999999", time.DateOnly} {\n'
        "\t\tif value, err := time.Parse(layout, text); err == nil {\n\t\t\treturn &value, nil\n\t\t}\n\t}\n"
        '\treturn nil, badRequest{errors.New(name + ": not a date or time")}\n}\n\n'
        "func queryBytes(q url.Values, name string) ([]byte, error) {\n"
        "\ttext, ok := query(q, name)\n\tif !ok {\n\t\treturn nil, nil\n\t}\n"
        "\tvalue, err := hex.DecodeString(text)\n\tif err != nil {\n\t\treturn nil, badRequest{err}\n\t}\n\treturn value, nil\n}\n"
    )


_QUERY = {"*string": "queryString", "*int32": "queryInt32", "*int64": "queryInt64", "*decimal.Decimal": "queryDecimal",
          "*bool": "queryBool", "*time.Time": "queryTime", "[]byte": "queryBytes"}  # fmt: skip
_BODY_METHODS = ("POST", "PUT", "PATCH")


def route(design: Design, use_case: UseCase) -> str:
    path = use_case.path or "/" + snake(use_case.name).replace("_", "-")
    return f"{use_case.http_method} /api/{design.context}/{path.lstrip('/')}"


def handler_file(design: Design, use_case: UseCase) -> tuple[str, str]:
    name = use_case.name
    body = use_case.http_method in _BODY_METHODS
    std = ["context", "net/http", *(["encoding/json"] if body else [])]
    local = [f"{module_path(design)}/{APP}"]
    if body:
        decode = (
            f"\t\tvar request app.{name}Request\n"
            "\t\tif err := json.NewDecoder(r.Body).Decode(&request); err != nil {\n"
            "\t\t\twriteError(w, badRequest{err})\n\t\t\treturn\n\t\t}\n"
        )
    else:
        decode = f"\t\tvar request app.{name}Request\n"
        if use_case.inputs:
            decode += "\t\tq := r.URL.Query()\n\t\tvar err error\n"
        for field in use_case.inputs:
            decode += (
                f'\t\tif request.{pascal(field.name)}, err = {_QUERY[go_type(field.type)]}(q, "{field.name}"); err != nil {{\n'
                "\t\t\twriteError(w, err)\n\t\t\treturn\n\t\t}\n"
            )
    rules = ", ".join(use_case.rules)
    return f"{HTTP}/{snake(name)}_handler.go", (
        f"package httpapi\n\n{_imports(std, [], local)}"
        f"// {name} is the REST adapter of {name} (rules {rules}): {route(design, use_case)}.\n"
        f"func {name}(tx Transactor, service *app.{name}Service) http.HandlerFunc {{\n"
        "\treturn func(w http.ResponseWriter, r *http.Request) {\n"
        f"{decode}"
        f"\t\tvar response app.{name}Response\n"
        "\t\terr := tx.InTx(r.Context(), func(ctx context.Context) error {\n"
        "\t\t\tvar err error\n\t\t\tresponse, err = service.Execute(ctx, request)\n\t\t\treturn err\n\t\t})\n"
        "\t\tif err != nil {\n\t\t\twriteError(w, err)\n\t\t\treturn\n\t\t}\n"
        "\t\twriteJSON(w, http.StatusOK, response)\n\t}\n}\n"
    )


def adapter_name(port: str) -> str:
    """The adapter of a port is the type of the same name in the package pg (pg.OrderRepository)."""
    return port


def constructor(name: str) -> str:
    return f"New{name}"


def used_ports(design: Design) -> list[Port]:
    """The ports some use case needs: Go does not allow an adapter the wiring creates and never uses."""
    needed = {p for u in design.use_cases for p in u.ports}
    return [p for p in design.ports if p.name in needed]


def server_file(design: Design) -> tuple[str, str]:
    """The orchestration layer: the pool, one adapter per port, one service per use case and their routes."""
    mod = module_path(design)
    lines = [f"\t{ident(p.name)} := pg.{constructor(adapter_name(p.name))}(db)" for p in used_ports(design)]
    for use_case in design.use_cases:
        ports = ", ".join(ident(p) for p in use_case.ports)
        lines.append(f"\t{ident(use_case.name)}Service := app.New{use_case.name}Service({ports})")
    lines.append("\tmux := http.NewServeMux()")
    lines += [
        f'\tmux.Handle("{route(design, u)}", httpapi.{u.name}(db, {ident(u.name)}Service))' for u in design.use_cases
    ]
    body = "\n".join(lines)
    local = [f"{mod}/internal/adapters/httpapi", f"{mod}/{PG}", *([f"{mod}/{APP}"] if design.use_cases else [])]
    return SERVER, (
        f"// Command server runs the {design.context} service: the PostgreSQL pool, one adapter per port, one service per\n"
        "// use case and their REST handlers. This is the only place that knows them all (the wiring).\n"
        f"package main\n\n{_imports(['errors', 'log', 'net/http', 'os', 'time'], [DECIMAL], local)}"
        "func main() {\n\tif err := run(); err != nil {\n\t\tlog.Fatal(err)\n\t}\n}\n\n"
        "func run() error {\n"
        "\tdecimal.MarshalJSONWithoutQuotes = true // amounts travel as JSON numbers, as the contract says\n"
        '\turl := os.Getenv("DATABASE_URL")\n'
        '\tif url == "" {\n\t\treturn errors.New("DATABASE_URL is not set")\n\t}\n'
        "\tdb, err := pg.Open(url)\n\tif err != nil {\n\t\treturn err\n\t}\n\tdefer db.Close()\n"
        f"{body}\n"
        '\taddr := os.Getenv("ADDR")\n\tif addr == "" {\n\t\taddr = ":8080"\n\t}\n'
        "\tserver := &http.Server{Addr: addr, Handler: mux, ReadHeaderTimeout: 10 * time.Second}\n"
        '\tlog.Printf("listening on %s", addr)\n'
        "\treturn server.ListenAndServe()\n}\n"
    )


def go_mod(design: Design) -> tuple[str, str]:
    direct = "\n".join(f"\t{m} {v}" for m, v in sorted(REQUIRE.items()))
    indirect = "\n".join(f"\t{m} {v} // indirect" for m, v in sorted(INDIRECT.items()))
    return (
        "go.mod",
        f"module {module_path(design)}\n\ngo {GO_VERSION}\n\nrequire (\n{direct}\n)\n\nrequire (\n{indirect}\n)\n",
    )


def schema_file(design: Design) -> tuple[str, str]:
    """The PostgreSQL schema, the same DDL the Spring Boot pack writes (one source for both)."""
    return SCHEMA, postgresql_schema(design)[1]


def service_path(design: Design, use_case: UseCase) -> str:
    return f"{APP}/{snake(use_case.name)}_service.go"


def test_path(design: Design, use_case: UseCase) -> str:
    return f"{APP}/{snake(use_case.name)}_service_test.go"


def adapter_path(design: Design, port: Port) -> str:
    return f"{PG}/{snake(port.name)}.go"


def skeleton(design: Design) -> dict[str, str]:
    """The deterministic files by layer: contracts, domain (entities, ports, error), adapters (REST, the database
    session), orchestration (module and wiring)."""
    files: dict[str, str] = dict([
        go_mod(design), ("go.sum", GO_SUM), schema_file(design), ports_doc(), app_doc(design), db_file(design),
        http_file(design), server_file(design), *domain_files(design),
    ])  # fmt: skip
    for entity in design.entities:
        files.update([entity_file(design, entity)])
    for port in design.ports:
        files.update([port_file(design, port)])
    for use_case in design.use_cases:
        files.update([contract_file(design, use_case), handler_file(design, use_case)])
    return files


def probe_file(design: Design, path: str) -> dict[str, str]:
    """A package that names a service or an adapter exactly as the wiring and the harness do (package, type,
    constructor and signatures), so a wrong name is a compiler error the agent sees."""
    mod = module_path(design)
    lines: list[str] = []
    local: list[str] = []
    std: list[str] = []
    for use_case in design.use_cases:
        if service_path(design, use_case) != path:
            continue
        name = use_case.name
        params = ", ".join(f"ports.{p}" for p in use_case.ports)
        std = ["context"]
        local = [f"{mod}/{APP}", *([f"{mod}/{PORTS}"] if use_case.ports else [])]
        lines = [
            f"var _ func({params}) *app.{name}Service = app.New{name}Service",
            f"var _ func(*app.{name}Service, context.Context, app.{name}Request) (app.{name}Response, error) = (*app.{name}Service).Execute",
        ]
    for port in design.ports:
        if adapter_path(design, port) != path:
            continue
        name = adapter_name(port.name)
        local = [f"{mod}/{PG}", f"{mod}/{PORTS}"]
        lines = [
            f"var _ func(*pg.DB) *pg.{name} = pg.{constructor(name)}",
            f"var _ ports.{port.name} = (*pg.{name})(nil)",
        ]
    if not lines:
        return {}
    return {PROBE: (
        "// Package probe names the piece under verification as the rest of the project will.\n"
        f"package probe\n\n{_imports(std, [], local)}" + "\n".join(lines) + "\n"
    )}  # fmt: skip


def layer_of(path: str, design: Design) -> str:
    if path.endswith("_test.go"):
        return "tests"
    if path.startswith(f"{APP}/") and path.endswith("_contract.go"):
        return "contracts"
    if path.startswith((f"{DOMAIN}/", f"{PORTS}/", f"{APP}/")):
        return "domain"
    if path.startswith("internal/adapters/") or path.endswith(".sql"):
        return "adapters"
    return "orchestration"
