// Runs the golden master cases on the generated service (NexTI verification, spec 11.3 check 3). Written by the
// platform, never by a model: the real PostgreSQL adapters, the external programs replaced by fakes that record their
// calls and answer what the case says, and the use case inside one transaction (a rejection undoes its writes and its
// external calls, as in the legacy). One JSON line per case, prefixed with "NXE ". This file is the part every
// design shares; glue.go, generated from the design, builds the service of the use case.
package main

import (
	"bufio"
	"context"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"reflect"
	"strconv"
	"time"

	"github.com/shopspring/decimal"
)

type plan struct {
	URL   string   `json:"url"`
	Reset []string `json:"reset"`
	Dump  []struct {
		Table string `json:"table"`
		SQL   string `json:"sql"`
	} `json:"dump"`
}

type answer struct {
	Returns *int `json:"returns"`
	Output  any  `json:"output"`
}

type testCase struct {
	Name    string              `json:"name"`
	Request map[string]*string  `json:"request"`
	Setup   []string            `json:"setup"`
	Stubs   map[string][]answer `json:"stubs"`
}

// store is the database session of the generated project (pg.DB).
type store interface {
	InTx(ctx context.Context, fn func(ctx context.Context) error) error
	Pool() *sql.DB
}

// execute runs the use case on a request in canonical text and answers its response in canonical text.
type execute func(ctx context.Context, request map[string]*string) (map[string]*string, error)

// recorder holds the calls of the fakes in one case and answers what the case says each program answered.
type recorder struct {
	stubs map[string][]answer
	seen  map[string]int
	calls []map[string]any
}

func (r *recorder) call(port, method string, arguments ...*string) (*string, error) {
	r.calls = append(r.calls, map[string]any{"port": port, "method": method, "arguments": arguments})
	answers := r.stubs[port]
	index := r.seen[port]
	r.seen[port]++
	if len(answers) == 0 {
		return nil, nil
	}
	found := answers[min(index, len(answers)-1)]
	if found.Returns != nil && *found.Returns != 0 {
		return nil, fmt.Errorf("%s answered %d", port, *found.Returns)
	}
	if found.Output == nil {
		return nil, nil
	}
	text := fmt.Sprint(found.Output)
	return &text, nil
}

func main() {
	var p plan
	var cases []testCase
	read(os.Args[1], &p)
	read(os.Args[2], &cases)
	db, err := open(p.URL)
	if err != nil {
		fmt.Println("NXE-FAILED", err)
		os.Exit(1)
	}
	out := bufio.NewWriter(os.Stdout)
	defer out.Flush()
	for _, c := range cases {
		line, _ := json.Marshal(run(context.Background(), db, p, c))
		fmt.Fprintf(out, "NXE %s\n", line)
	}
}

func read(path string, into any) {
	file, err := os.Open(path)
	if err != nil {
		panic(err)
	}
	defer file.Close()
	decoder := json.NewDecoder(file)
	decoder.UseNumber()
	if err := decoder.Decode(into); err != nil {
		panic(err)
	}
}

func run(ctx context.Context, db store, p plan, c testCase) (out map[string]any) {
	out = map[string]any{"name": c.Name}
	defer func() {
		if recovered := recover(); recovered != nil {
			out = map[string]any{"name": c.Name, "failure": fmt.Sprintf("panic: %v", recovered)}
		}
	}()
	for _, statement := range append(append([]string{}, p.Reset...), c.Setup...) {
		if _, err := db.Pool().ExecContext(ctx, statement); err != nil {
			out["failure"] = fmt.Sprintf("%s: %v", statement, err)
			return out
		}
	}
	rec := &recorder{stubs: c.Stubs, seen: map[string]int{}}
	service := build(db, rec)
	var response map[string]*string
	err := db.InTx(ctx, func(ctx context.Context) error {
		var err error
		response, err = service(ctx, c.Request)
		return err
	})
	if err != nil {
		found, ok := rejection(err)
		if !ok {
			out["failure"] = fmt.Sprintf("%T: %v", err, err)
			return out
		}
		rec.calls = nil // inside the rolled-back transaction: they had no effect
		out["error"] = found
	} else {
		out["response"] = response
	}
	tables := map[string]any{}
	for _, d := range p.Dump {
		rows, err := dump(ctx, db.Pool(), d.SQL)
		if err != nil {
			out["failure"] = fmt.Sprintf("%s: %v", d.SQL, err)
			return out
		}
		tables[d.Table] = rows
	}
	out["tables"] = tables
	calls := rec.calls
	if calls == nil {
		calls = []map[string]any{}
	}
	out["calls"] = calls
	return out
}

// dump reads a table with every column already in text (the plan's SELECT casts them).
func dump(ctx context.Context, pool *sql.DB, query string) ([]map[string]*string, error) {
	rows, err := pool.QueryContext(ctx, query)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	columns, err := rows.Columns()
	if err != nil {
		return nil, err
	}
	found := []map[string]*string{}
	for rows.Next() {
		values := make([]sql.NullString, len(columns))
		pointers := make([]any, len(columns))
		for i := range values {
			pointers[i] = &values[i]
		}
		if err := rows.Scan(pointers...); err != nil {
			return nil, err
		}
		row := map[string]*string{}
		for i, column := range columns {
			if values[i].Valid {
				text := values[i].String
				row[column] = &text
			} else {
				row[column] = nil
			}
		}
		found = append(found, row)
	}
	return found, rows.Err()
}

// text is a value in the canonical text of its type; nil (null) stays nil. Times without their offset.
func text(value any) *string {
	return format(value, "2006-01-02T15:04:05.000")
}

// zoned is a time with its offset (timestamp with time zone).
func zoned(value any) *string {
	return format(value, "2006-01-02T15:04:05.000-07:00")
}

func format(value any, layout string) *string {
	if value == nil {
		return nil
	}
	v := reflect.ValueOf(value)
	for v.Kind() == reflect.Pointer {
		if v.IsNil() {
			return nil
		}
		v = v.Elem()
	}
	var s string
	switch x := v.Interface().(type) {
	case decimal.Decimal:
		s = x.String()
	case time.Time:
		s = x.Format(layout)
	case bool:
		s = strconv.FormatBool(x)
	case []byte:
		if x == nil {
			return nil
		}
		s = hex.EncodeToString(x)
	case string:
		s = x
	default:
		s = fmt.Sprint(x)
	}
	return &s
}

func asString(s *string) *string {
	return s
}

func asInt32(s *string) *int32 {
	if s == nil {
		return nil
	}
	value, err := strconv.ParseInt(*s, 10, 32)
	if err != nil {
		panic(err)
	}
	narrow := int32(value)
	return &narrow
}

func asInt64(s *string) *int64 {
	if s == nil {
		return nil
	}
	value, err := strconv.ParseInt(*s, 10, 64)
	if err != nil {
		panic(err)
	}
	return &value
}

func asDecimal(s *string) *decimal.Decimal {
	if s == nil {
		return nil
	}
	value := decimal.RequireFromString(*s)
	return &value
}

func asBool(s *string) *bool {
	if s == nil {
		return nil
	}
	value, err := strconv.ParseBool(*s)
	if err != nil {
		panic(err)
	}
	return &value
}

func asTime(s *string) *time.Time {
	if s == nil {
		return nil
	}
	for _, layout := range []string{"2006-01-02T15:04:05.999999999", time.RFC3339Nano, time.DateOnly} {
		if value, err := time.Parse(layout, *s); err == nil {
			return &value
		}
	}
	panic("not a date or time: " + *s)
}

func asBytes(s *string) []byte {
	if s == nil {
		return nil
	}
	value, err := hex.DecodeString(*s)
	if err != nil {
		panic(err)
	}
	return value
}

// The answers of a fake, in the type its port method returns (zero when the case says nothing).
func answerInt(s *string) int {
	if s == nil {
		return 0
	}
	return int(decimal.RequireFromString(*s).IntPart())
}

func answerInt64(s *string) int64 {
	if s == nil {
		return 0
	}
	return decimal.RequireFromString(*s).IntPart()
}

func answerBool(s *string) bool {
	return s != nil && (*s == "1" || *s == "true" || *s == "TRUE" || *s == "True")
}
