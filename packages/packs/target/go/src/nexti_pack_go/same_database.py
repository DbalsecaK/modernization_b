# ruff: noqa: E501 - the lines of generated Go are kept whole, so the code reads like the file it writes
"""`same_database` in the Go pack (ADR-0055, ADR-0056 phase H): the data and the programs the legacy calls stay on the
legacy's Sybase ASE. The project talks to it through github.com/thda/tds (a pure Go TDS driver for database/sql), the
unit of work is the legacy's own T-SQL on one connection bound to the request (`begin tran`, `commit tran`,
`rollback tran`, `save tran`, in the engine's unchained mode), and every port that replaces a called program gets an
adapter the platform writes itself: one T-SQL batch with the arguments as literals (the statement the legacy ran),
its return status read back and the messages it raises kept for the caller, never aborting the call (the driver's
error handler of that connection is told which messages are the program's).

The generators here are deterministic: everything follows from the design."""

from typing import Any

from nexti_core.spec import neutral_types as nt
from nexti_core.spec.design import Design, Port

TDS = "github.com/thda/tds"
UNIT_OF_WORK_PORT = "UnitOfWork"
UNIT_OF_WORK_METHODS = ("begin", "commit", "rollback")
SP_STATUS = "nx_rc"
STATUS = "return"  # the reserved legacy name of a called program's return status (ADR-0055, phase F)


def same_database(design: Design) -> bool:
    return design.data_strategy == "same_database"


def unit_of_work_port(design: Design) -> Port | None:
    return next((p for p in design.ports if p.name == UNIT_OF_WORK_PORT and not p.legacy_program), None)


def owns_transaction(port: Port | None) -> bool:
    """Whether the UnitOfWork port begins, commits and rolls back (phase F): the service then owns the transaction
    and the request only binds the connection and closes what the use case left open."""
    if port is None:
        return False
    declared = {m.name for m in port.methods}
    return all(m in declared for m in UNIT_OF_WORK_METHODS)


def sybase_type(neutral: str) -> str:
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


DB_FILE = """// Package pg holds the adapters of the ports on the legacy's Sybase ASE (same database, ADR-0055): database/sql
// with the tds driver. The package keeps its name so the wiring, the harness and the agents see the same layout as
// with PostgreSQL.
package pg

import (
	"context"
	"database/sql"
	"fmt"
	"sync"

	_ "github.com/thda/tds" // the "tds" driver of database/sql: Sybase ASE
)

// Querier runs SQL: the connection of the current request when there is one, otherwise the pool.
type Querier interface {
	ExecContext(ctx context.Context, query string, args ...any) (sql.Result, error)
	QueryContext(ctx context.Context, query string, args ...any) (*sql.Rows, error)
	QueryRowContext(ctx context.Context, query string, args ...any) *sql.Row
}

// DB is the pool the adapters share; the connection of a request travels in its context.
type DB struct {
	pool *sql.DB
}

// Open opens the pool on a Sybase ASE URL (tds://user:password@host:5000/database?charset=iso_1).
func Open(url string) (*DB, error) {
	pool, err := sql.Open("tds", url)
	if err != nil {
		return nil, fmt.Errorf("open the database: %w", err)
	}
	return &DB{pool: pool}, nil
}

// Pool is the underlying pool.
func (db *DB) Pool() *sql.DB {
	return db.pool
}

// Close closes the pool.
func (db *DB) Close() error {
	return db.pool.Close()
}

type connKey struct{}

// InTx runs fn inside one unit of work of the legacy: one connection bound to the request, `begin tran` on it, then
// `commit tran` when fn returns nil and `rollback tran` when it fails or panics (T-SQL in the engine's unchained
// mode, ADR-0056: a client transaction would run the legacy's procedures in a mode they were not written for).
func (db *DB) InTx(ctx context.Context, fn func(ctx context.Context) error) error {
	return db.bound(ctx, true, fn)
}

// InConn binds one connection to the request without beginning: the service owns the unit of work (its UnitOfWork
// port, phase F); what the use case leaves open is confirmed when fn succeeds and undone when it fails.
func (db *DB) InConn(ctx context.Context, fn func(ctx context.Context) error) error {
	return db.bound(ctx, false, fn)
}

func (db *DB) bound(ctx context.Context, begin bool, fn func(ctx context.Context) error) (err error) {
	conn, err := db.pool.Conn(ctx)
	if err != nil {
		return fmt.Errorf("open a connection: %w", err)
	}
	defer conn.Close()
	if begin {
		if _, err := conn.ExecContext(ctx, "begin tran"); err != nil {
			return fmt.Errorf("begin the transaction: %w", err)
		}
	}
	defer func() {
		if recovered := recover(); recovered != nil {
			_, _ = conn.ExecContext(context.Background(), "if @@trancount > 0 rollback tran")
			panic(recovered)
		}
	}()
	if err := fn(context.WithValue(ctx, connKey{}, conn)); err != nil {
		_, _ = conn.ExecContext(context.Background(), "if @@trancount > 0 rollback tran")
		return err
	}
	if _, err := conn.ExecContext(ctx, "if @@trancount > 0 commit tran"); err != nil {
		return fmt.Errorf("commit the transaction: %w", err)
	}
	return nil
}

// Q is what an adapter runs its SQL on: the connection ctx carries, or the pool outside a request.
func (db *DB) Q(ctx context.Context) Querier {
	if conn, ok := ctx.Value(connKey{}).(*sql.Conn); ok {
		return conn
	}
	return db.pool
}

// conn is the connection of the request, or one of the pool for a call made outside one (release returns it).
func (db *DB) conn(ctx context.Context) (conn *sql.Conn, release func(), err error) {
	if bound, ok := ctx.Value(connKey{}).(*sql.Conn); ok {
		return bound, func() {}, nil
	}
	conn, err = db.pool.Conn(ctx)
	if err != nil {
		return nil, nil, err
	}
	return conn, func() { _ = conn.Close() }, nil
}

type messagesKey struct{}

// Messages collects what the called programs raised during a request, in order (ADR-0056).
type Messages struct {
	mu   sync.Mutex
	kept []string
}

// WithMessages is ctx with a collector of the messages the called programs raise, and how to read them.
func WithMessages(ctx context.Context) (context.Context, func() []string) {
	found := &Messages{}
	return context.WithValue(ctx, messagesKey{}, found), func() []string {
		found.mu.Lock()
		defer found.mu.Unlock()
		return append([]string{}, found.kept...)
	}
}

func keep(ctx context.Context, messages []string) {
	if found, ok := ctx.Value(messagesKey{}).(*Messages); ok {
		found.mu.Lock()
		found.kept = append(found.kept, messages...)
		found.mu.Unlock()
	}
}
"""

LEGACY_FILE = """package pg

import (
	"context"
	"database/sql"
	"encoding/hex"
	"fmt"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/shopspring/decimal"
	"github.com/thda/tds"
)

// call runs the batch of a called program on the request's connection and returns the row of its last SELECT (the
// status and the outputs, ADR-0055): the program's own result sets are skipped. While it runs, the connection's error
// handler keeps the messages the program raises (raiserror, a number of the user range) instead of failing the call,
// as the engine goes on with the caller of a procedure that raises (ADR-0056); they reach the request's collector.
func (db *DB) call(ctx context.Context, batch string) (map[string]any, error) {
	conn, release, err := db.conn(ctx)
	if err != nil {
		return nil, err
	}
	defer release()
	var raised []string
	setHandler(conn, func(m tds.SybError) bool {
		if m.Severity > 10 && m.MsgNumber >= 17000 {
			raised = append(raised, fmt.Sprintf("%d: %s", m.MsgNumber, strings.TrimRight(m.Message, " \\n")))
			return false
		}
		return m.Severity > 10
	})
	defer setHandler(conn, func(m tds.SybError) bool { return m.Severity > 10 })
	rows, err := conn.QueryContext(ctx, batch)
	if err != nil {
		keep(ctx, raised)
		return nil, err
	}
	defer rows.Close()
	var found map[string]any
	for {
		columns, _ := rows.Columns()
		for rows.Next() {
			values := make([]any, len(columns))
			pointers := make([]any, len(columns))
			for i := range values {
				pointers[i] = &values[i]
			}
			if err := rows.Scan(pointers...); err != nil {
				return nil, err
			}
			row := map[string]any{}
			for i, column := range columns {
				row[strings.ToLower(column)] = values[i]
			}
			if _, ok := row["nx_rc"]; ok {
				found = row
			}
		}
		if !rows.NextResultSet() {
			break
		}
	}
	keep(ctx, raised)
	if err := rows.Err(); err != nil && found == nil {
		return nil, err
	}
	if found == nil {
		return nil, fmt.Errorf("the program returned no status%s", strings.Join(append([]string{""}, raised...), "; "))
	}
	return found, nil
}

func setHandler(conn *sql.Conn, handler func(tds.SybError) bool) {
	_ = conn.Raw(func(driverConn any) error {
		if h, ok := driverConn.(tds.ErrorHandler); ok {
			h.SetErrorhandler(handler)
		}
		return nil
	})
}

// literal is an argument as T-SQL writes it: the statement the legacy ran (nil is null).
func literal(value any) string {
	switch v := value.(type) {
	case nil:
		return "null"
	case *string:
		if v == nil {
			return "null"
		}
		return "'" + strings.ReplaceAll(*v, "'", "''") + "'"
	case *int32:
		if v == nil {
			return "null"
		}
		return strconv.FormatInt(int64(*v), 10)
	case *int64:
		if v == nil {
			return "null"
		}
		return strconv.FormatInt(*v, 10)
	case *decimal.Decimal:
		if v == nil {
			return "null"
		}
		return v.String()
	case *bool:
		if v == nil {
			return "null"
		}
		if *v {
			return "1"
		}
		return "0"
	case *time.Time:
		if v == nil {
			return "null"
		}
		return "'" + v.Format("2006-01-02 15:04:05.000") + "'"
	case []byte:
		if v == nil {
			return "null"
		}
		return "0x" + hex.EncodeToString(v)
	}
	return "'" + strings.ReplaceAll(fmt.Sprint(value), "'", "''") + "'"
}

// asText is a value of the result row as text (nil stays nil); fixed text keeps no trailing blanks.
func asText(value any) *string {
	switch v := value.(type) {
	case nil:
		return nil
	case []byte:
		if !utf8.Valid(v) {
			text := hex.EncodeToString(v)
			return &text
		}
		text := strings.TrimRight(string(v), " ")
		return &text
	case string:
		text := strings.TrimRight(v, " ")
		return &text
	case time.Time:
		text := v.Format("2006-01-02T15:04:05.000")
		return &text
	}
	text := fmt.Sprint(value)
	return &text
}

func asDecimal(value any) *decimal.Decimal {
	text := asText(value)
	if text == nil {
		return nil
	}
	found := decimal.RequireFromString(*text)
	return &found
}

func asInt64(value any) *int64 {
	text := asText(value)
	if text == nil {
		return nil
	}
	found := decimal.RequireFromString(*text).IntPart()
	return &found
}

func asInt32(value any) *int32 {
	found := asInt64(value)
	if found == nil {
		return nil
	}
	narrow := int32(*found)
	return &narrow
}

func asBool(value any) *bool {
	text := asText(value)
	if text == nil {
		return nil
	}
	found := *text == "1" || strings.EqualFold(*text, "true")
	return &found
}

func asTime(value any) *time.Time {
	if v, ok := value.(time.Time); ok {
		return &v
	}
	text := asText(value)
	if text == nil {
		return nil
	}
	for _, layout := range []string{"2006-01-02T15:04:05.000", "2006-01-02 15:04:05", time.RFC3339Nano, time.DateOnly} {
		if found, err := time.Parse(layout, *text); err == nil {
			return &found
		}
	}
	return nil
}

func asBytes(value any) []byte {
	if v, ok := value.([]byte); ok {
		return v
	}
	return nil
}

func status(row map[string]any) int {
	found := asInt64(row["nx_rc"])
	if found == nil {
		return 0
	}
	return int(*found)
}

var _ = sql.ErrNoRows
"""

_AS = {"*string": "asText", "*int32": "asInt32", "*int64": "asInt64", "*decimal.Decimal": "asDecimal",
       "*bool": "asBool", "*time.Time": "asTime", "[]byte": "asBytes"}  # fmt: skip


def program_adapter(design: Design, port: Port, helpers: dict[str, Any]) -> str:
    """The adapter of a port that replaces a called program (ADR-0055): one T-SQL batch per method with the mapped
    inputs as literals (ADR-0056), the return status checked (a non-zero status fails, as the fakes of the golden
    master do, unless the method carries it as data) and the output parameters read back."""
    go_type, ident, pascal, method_signature, imports = (helpers[k] for k in
                                                         ("go_type", "ident", "pascal", "method_signature", "imports"))  # fmt: skip
    entities = {e.name: e for e in design.entities}
    program = port.legacy_program or ""
    name = port.name
    methods = []
    uses_domain = False
    needs_fmt = False
    for method in port.methods:
        outputs: list[tuple[str, str, str]] = []
        entity = entities.get(method.returns or "")
        carries_status = method.legacy_output == STATUS or STATUS in method.legacy_outputs.values()
        if method.legacy_outputs and entity is not None:
            by_name = {f.name: f for f in entity.fields}
            outputs = [(legacy, legacy.lstrip("@").lower(), by_name[field].type)
                       for field, legacy in method.legacy_outputs.items()
                       if field in by_name and legacy != STATUS]  # fmt: skip
        elif method.legacy_output and method.legacy_output != STATUS:
            neutral = "boolean" if method.returns == "boolean" else "integer(32,signed)"
            outputs = [(method.legacy_output, method.legacy_output.lstrip("@").lower(), neutral)]
        declares = ", ".join([f"@{SP_STATUS} int"] + [f"{p} {sybase_type(t)}" for p, _, t in outputs])
        pieces = [f'"{f.legacy} = "+literal({ident(f.name)})' for f in method.inputs if f.legacy]
        pieces += [f'"{p} = {p} output"' for p, _, _ in outputs]
        arguments = '+", "+'.join(pieces) if pieces else '""'
        selects = ", ".join([f"@{SP_STATUS} as {SP_STATUS}"] + [f"{p} as {alias}" for p, alias, _ in outputs])
        batch = f'"declare {declares}\\nexec @{SP_STATUS} = {program} "+{arguments}+"\\nselect {selects}"'
        if entity is not None:
            uses_domain = True
            zero = "nil"
            fields = []
            for f in entity.fields:
                legacy = method.legacy_outputs.get(f.name)
                if legacy == STATUS:
                    fields.append(f'\t\t{pascal(f.name)}: {_AS[go_type(f.type)]}(nxRow["{SP_STATUS}"]),')
                elif legacy:
                    fields.append(
                        f'\t\t{pascal(f.name)}: {_AS[go_type(f.type)]}(nxRow["{legacy.lstrip("@").lower()}"]),'
                    )
            answer = f"\treturn &domain.{entity.name}{{\n" + "\n".join(fields) + "\n\t}, nil\n"
        elif method.returns in ("int", "long", "boolean") and (method.legacy_output == STATUS or not outputs):
            zero = {"int": "0", "long": "0", "boolean": "false"}[method.returns]
            answer = {"int": "\treturn nxRC, nil\n", "long": "\treturn int64(nxRC), nil\n",
                      "boolean": "\treturn nxRC == 0, nil\n"}[method.returns]  # fmt: skip
        elif outputs:
            kind = {"boolean": "bool", "int": "int", "long": "int64"}[method.returns or "int"]
            zero = {"bool": "false", "int": "0", "int64": "0"}[kind]
            read = {"bool": f'asBool(nxRow["{outputs[0][1]}"])', "int": f'asInt64(nxRow["{outputs[0][1]}"])',
                    "int64": f'asInt64(nxRow["{outputs[0][1]}"])'}[kind]  # fmt: skip
            convert = {"bool": "*nxValue", "int": "int(*nxValue)", "int64": "*nxValue"}[kind]
            answer = (f"\tnxValue := {read}\n\tif nxValue == nil {{\n\t\treturn {zero}, nil\n\t}}\n"
                      f"\treturn {convert}, nil\n")  # fmt: skip
        else:
            zero = ""
            answer = "\treturn nil\n"
        carries_status = carries_status or (method.returns in ("int", "long", "boolean") and not outputs)
        fail = f"{zero}, " if zero else ""
        check = (
            ""
            if carries_status
            else f'\tif nxRC != 0 {{\n\t\treturn {fail}fmt.Errorf("{program} answered %d", nxRC)\n\t}}\n'
        )
        needs_fmt = needs_fmt or bool(check)
        uses_rc = "nxRC" in answer or bool(check)
        methods.append(
            f"// {pascal(method.name)} calls {program} (generated by the platform).\n"
            f"func (nxAdapter *{name}) {method_signature(method, design)} {{\n"
            f"\tnxRow, err := nxAdapter.db.call(ctx, {batch})\n"
            f"\tif err != nil {{\n\t\treturn {fail}err\n\t}}\n"
            + ("\tnxRC := status(nxRow)\n" if uses_rc else "")
            + ("" if uses_rc or "nxRow" in answer else "\t_ = nxRow\n")
            + check
            + answer
            + "}\n"
        )
    types = [go_type(p.type) for m in port.methods for p in m.inputs]
    std = ["context", *(["fmt"] if needs_fmt else []), *(["time"] if any("time.Time" in t for t in types) else [])]
    external = ["github.com/shopspring/decimal"] if any("decimal.Decimal" in t for t in types) else []
    local = [helpers["domain"]] if uses_domain else []
    return (
        f"package pg\n\n{imports(std, external, local)}"
        f"// {name} is {program} called where it lives (generated by the platform, ADR-0055 same database), inside the\n"
        "// unit of work of the request; its return status decides and its output parameters come back. The messages it\n"
        "// raises are kept for the caller (ADR-0056) and never fail the call.\n"
        f"type {name} struct {{\n\tdb *DB\n}}\n\n"
        f"// New{name} is the adapter on the shared pool.\n"
        f"func New{name}(db *DB) *{name} {{\n\treturn &{name}{{db: db}}\n}}\n\n" + "\n".join(methods)
    )


def unit_of_work_adapter(design: Design, port: Port, helpers: dict[str, Any]) -> str:
    """The UnitOfWork port on the request's connection: the service begins, confirms, undoes and marks where the
    legacy does (T-SQL in the engine's transaction mode)."""
    method_signature, ident = helpers["method_signature"], helpers["ident"]
    statements = {"begin": '"begin tran"', "commit": '"commit tran"', "rollback": '"rollback tran"'}
    methods = []
    for method in port.methods:
        if method.name in statements:
            sql = statements[method.name]
        elif method.name in ("savepoint", "rollbackTo") and method.inputs:
            label = ident(method.inputs[0].name)
            verb = "save tran " if method.name == "savepoint" else "rollback tran "
            sql = f'"{verb}"+savepointLabel({label})'
        else:  # not a unit of work operation: nothing to send
            sql = '"select 1"'
        methods.append(
            f"func (u *{port.name}) {method_signature(method, design)} {{\n"
            f"\t_, err := u.db.Q(ctx).ExecContext(ctx, {sql})\n\treturn err\n}}\n"
        )
    return (
        'package pg\n\nimport (\n\t"context"\n\t"regexp"\n)\n\n'
        f"// {port.name} is the unit of work of the legacy on the request's connection (generated by the platform,\n"
        "// ADR-0055): T-SQL in the engine's transaction mode (ADR-0056).\n"
        f"type {port.name} struct {{\n\tdb *DB\n}}\n\n"
        f"// New{port.name} is the adapter on the shared pool.\n"
        f"func New{port.name}(db *DB) *{port.name} {{\n\treturn &{port.name}{{db: db}}\n}}\n\n"
        + "\n".join(methods)
        + "\nvar savepointName = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*$`)\n\n"
        "func savepointLabel(name *string) string {\n"
        '\tif name == nil || !savepointName.MatchString(*name) {\n\t\tpanic("savepoint name")\n\t}\n\treturn *name\n}\n'
    )
