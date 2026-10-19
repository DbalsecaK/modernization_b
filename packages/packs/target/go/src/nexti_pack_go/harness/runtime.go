// Runs the golden master cases on the generated service (NexTI verification, spec 11.3 check 3). Written by the
// platform, never by a model: the real adapters (PostgreSQL, or the legacy's own Sybase ASE with same_database), the
// external programs replaced by fakes that record their calls and answer what the case says (or, on the legacy's
// engine, by its substitutes, whose calls the engine logs), and the use case inside one transaction (a rejection
// undoes its writes and its external calls, as in the legacy). One JSON line per case, prefixed with "NXE ". This file
// is the part every design shares; glue.go, generated from the design, builds the service of the use case.
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
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	"github.com/shopspring/decimal"
)

type plan struct {
	URL   string   `json:"url"`
	Reset []string `json:"reset"`
	Dump  []struct {
		Table string `json:"table"`
		SQL   string `json:"sql"`
	} `json:"dump"`
	// Calls reads the calls the legacy's engine logged (ADR-0055); empty against the sandbox's database.
	Calls string `json:"calls"`
	// Concurrency names the case run twice at the same time (ADR-0056, point 12); empty when there is none.
	Concurrency string `json:"concurrency"`
}

// effect is a row a transactional substitute leaves (ADR-0055): the update by the entity's key, and the insert
// that runs when the update changed nothing.
type effect struct {
	Update *string `json:"update"`
	Insert string  `json:"insert"`
}

type answer struct {
	Returns       *int     `json:"returns"`
	CarriesStatus bool     `json:"carries_status"`
	Output        any      `json:"output"`
	Effects       []effect `json:"effects"`
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
	// exec runs a statement of a substitute's effect inside the transaction ctx carries; nil without a database.
	exec func(ctx context.Context, query string) (int64, error)
}

func (r *recorder) call(ctx context.Context, port, method string, arguments ...*string) (*string, error) {
	r.calls = append(r.calls, map[string]any{"port": port, "method": method, "arguments": arguments})
	answers := r.stubs[port]
	index := r.seen[port]
	r.seen[port]++
	if len(answers) == 0 {
		return nil, nil
	}
	found := answers[min(index, len(answers)-1)]
	// A transactional substitute (ADR-0055): the rows the program leaves, inside the use case's transaction.
	for _, e := range found.Effects {
		if r.exec == nil {
			return nil, fmt.Errorf("%s: the effects of a substitute need a database", port)
		}
		changed := int64(0)
		if e.Update != nil {
			n, err := r.exec(ctx, *e.Update)
			if err != nil {
				return nil, err
			}
			changed = n
		}
		if changed == 0 {
			if _, err := r.exec(ctx, e.Insert); err != nil {
				return nil, err
			}
		}
	}
	if found.Returns != nil && *found.Returns != 0 && !found.CarriesStatus {
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
	if p.URL == "" { // the delivered plan carries no credentials: the customer's test engine comes from the environment
		p.URL = os.Getenv("NEXTI_LEGACY_URL")
		if p.URL == "" {
			fmt.Println("set NEXTI_LEGACY_URL to the test engine's URL")
			os.Exit(2)
		}
	}
	db, err := open(p.URL)
	if err != nil {
		fmt.Println("NXE-FAILED", err)
		os.Exit(1)
	}
	var results []map[string]any
	for _, c := range cases {
		results = append(results, run(context.Background(), db, p, c, true))
	}
	if p.Concurrency != "" {
		results = append(results, concurrency(context.Background(), db, p, cases))
	}
	out := bufio.NewWriter(os.Stdout)
	for _, result := range results {
		line, _ := json.Marshal(result)
		fmt.Fprintf(out, "NXE %s\n", line)
	}
	// Delivered with the project (ADR-0056, phase E): with a third argument, expected.json, every result is compared
	// with what the platform observed when the verdict was signed, and any difference fails the run.
	if len(os.Args) > 3 {
		var expected map[string]any
		read(os.Args[3], &expected)
		differing := 0
		for _, result := range results {
			name, _ := result["name"].(string)
			want, ok := expected[name]
			if !ok {
				continue
			}
			actual := map[string]any{}
			for key, value := range result {
				if key != "name" && key != "sequential" && key != "concurrent" {
					actual[key] = value
				}
			}
			// Both sides as the JSON the harness prints, so numbers and nulls compare as text.
			left, _ := json.Marshal(want)
			right, _ := json.Marshal(actual)
			var a, b any
			_ = json.Unmarshal(left, &a)
			_ = json.Unmarshal(right, &b)
			if !reflect.DeepEqual(a, b) {
				differing++
				fmt.Fprintf(out, "DIFF %s: expected %s but was %s\n", name, left, right)
			}
		}
		if differing == 0 {
			fmt.Fprintln(out, "GOLDEN MASTER REPRODUCED")
		} else {
			fmt.Fprintf(out, "%d case(s) no longer reproduce the proven behaviour\n", differing)
		}
		out.Flush()
		if differing > 0 {
			os.Exit(1)
		}
	}
	out.Flush()
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

func prepare(ctx context.Context, db store, p plan, c testCase) error {
	for _, statement := range append(append([]string{}, p.Reset...), c.Setup...) {
		if _, err := db.Pool().ExecContext(ctx, statement); err != nil {
			return fmt.Errorf("%s: %w", statement, err)
		}
	}
	return nil
}

func run(ctx context.Context, db store, p plan, c testCase, fresh bool) (out map[string]any) {
	out = map[string]any{"name": c.Name}
	defer func() {
		if recovered := recover(); recovered != nil {
			out = map[string]any{"name": c.Name, "failure": fmt.Sprintf("panic: %v", recovered)}
		}
	}()
	if fresh {
		if err := prepare(ctx, db, p, c); err != nil {
			out["failure"] = err.Error()
			return out
		}
	}
	rec := &recorder{stubs: c.Stubs, seen: map[string]int{}}
	service := build(db, rec)
	// The messages the called programs raise through the generated adapters (ADR-0056).
	ctx, raised := collect(ctx)
	var response map[string]*string
	err := transact(db)(ctx, func(ctx context.Context) error {
		var err error
		response, err = service(ctx, c.Request)
		return err
	})
	calls := rec.calls
	var undone []map[string]any
	if err != nil {
		found, ok := rejection(err)
		if !ok {
			out["failure"] = fmt.Sprintf("%T: %v", err, err)
			return out
		}
		// The rollback undoes the tables and the effects of the calls made inside the transaction: they are
		// reported apart, as "undone", like the legacy calls its rollback erased (ADR-0055).
		out["error"] = found
		undone, calls = calls, nil
	} else {
		out["response"] = response
	}
	tables, err := dumpAll(ctx, db, p)
	if err != nil {
		out["failure"] = err.Error()
		return out
	}
	out["tables"] = tables
	if calls == nil {
		calls = []map[string]any{}
	}
	if undone == nil {
		undone = []map[string]any{}
	}
	out["calls"] = calls
	out["undone"] = undone
	messages := raised()
	if messages == nil {
		messages = []string{}
	}
	out["messages"] = messages
	if p.Calls != "" {
		// The legacy's engine logged the calls that survived the use case's transaction (ADR-0055).
		logged, err := dump(ctx, db.Pool(), p.Calls)
		if err != nil {
			out["failure"] = fmt.Sprintf("%s: %v", p.Calls, err)
			return out
		}
		out["legacy_calls"] = logged
	}
	return out
}

func dumpAll(ctx context.Context, db store, p plan) (map[string]any, error) {
	tables := map[string]any{}
	for _, d := range p.Dump {
		rows, err := dump(ctx, db.Pool(), d.SQL)
		if err != nil {
			return nil, fmt.Errorf("%s: %w", d.SQL, err)
		}
		tables[d.Table] = rows
	}
	return tables, nil
}

// concurrency runs the named case twice at the same time, each run on its own connection, on the same rows
// (ADR-0056, point 12): the final state must be the one of running it twice one after the other (serializable), and
// neither run may fail with a lock or a deadlock the sequential runs do not have.
func concurrency(ctx context.Context, db store, p plan, cases []testCase) map[string]any {
	out := map[string]any{"name": "__concurrency__", "case": p.Concurrency}
	var chosen *testCase
	for i := range cases {
		if cases[i].Name == p.Concurrency {
			chosen = &cases[i]
		}
	}
	if chosen == nil {
		out["failure"] = "the plan names a case that is not in the suite: " + p.Concurrency
		return out
	}
	run(ctx, db, p, *chosen, true)
	sequential := run(ctx, db, p, *chosen, false)["tables"]
	if err := prepare(ctx, db, p, *chosen); err != nil {
		out["failure"] = err.Error()
		return out
	}
	var failures []string
	var mu sync.Mutex
	var wg sync.WaitGroup
	start := make(chan struct{})
	for i := 0; i < 2; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			defer func() {
				if recovered := recover(); recovered != nil {
					mu.Lock()
					failures = append(failures, fmt.Sprintf("panic: %v", recovered))
					mu.Unlock()
				}
			}()
			rec := &recorder{stubs: chosen.Stubs, seen: map[string]int{}}
			service := build(db, rec)
			<-start
			own, _ := collect(ctx)
			err := transact(db)(own, func(ctx context.Context) error {
				_, err := service(ctx, chosen.Request)
				return err
			})
			if _, rejected := rejection(err); err != nil && !rejected {
				mu.Lock()
				failures = append(failures, fmt.Sprintf("%T: %v", err, err))
				mu.Unlock()
			}
		}()
	}
	close(start)
	done := make(chan struct{})
	go func() { wg.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(120 * time.Second):
		failures = append(failures, "a run did not finish in 120 s (a lock the sequential runs do not have)")
	}
	concurrent, err := dumpAll(ctx, db, p)
	if err != nil {
		failures = append(failures, err.Error())
	}
	if failures == nil {
		failures = []string{}
	}
	left, _ := json.Marshal(sequential)
	right, _ := json.Marshal(concurrent)
	out["failures"] = failures
	out["sequential"] = sequential
	out["concurrent"] = concurrent
	out["serializable"] = len(failures) == 0 && string(left) == string(right)
	return out
}

// dump reads a table as text (the PostgreSQL plan's SELECT already casts every column; the legacy's engine answers
// its own types, read here into their canonical text).
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
		values := make([]any, len(columns))
		pointers := make([]any, len(columns))
		for i := range values {
			pointers[i] = &values[i]
		}
		if err := rows.Scan(pointers...); err != nil {
			return nil, err
		}
		row := map[string]*string{}
		for i, column := range columns {
			row[column] = cell(values[i])
		}
		found = append(found, row)
	}
	return found, rows.Err()
}

// cell is a value a driver scanned, as text: bytes are text when they are valid text (hex otherwise), times in the
// canonical local layout, everything else as text() writes it.
func cell(value any) *string {
	switch v := value.(type) {
	case nil:
		return nil
	case []byte:
		if utf8.Valid(v) {
			s := string(v)
			return &s
		}
		s := hex.EncodeToString(v)
		return &s
	case string:
		return &v
	}
	return text(value)
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
		s = strings.TrimSpace(fmt.Sprint(x))
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
