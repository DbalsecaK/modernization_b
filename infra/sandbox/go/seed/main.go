// The seed of the Go pack sandbox image: it imports every library a generated project may use, so building it
// fills the module cache the sandbox works from without network (ADR-0029). Keep go.mod equal to the pack's
// (packages/packs/target/go/src/nexti_pack_go/generate.py, REQUIRE).
package main

import (
	"database/sql"
	"fmt"

	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/shopspring/decimal"
)

func main() {
	fmt.Println(decimal.RequireFromString("1.25").Round(2), sql.Drivers())
}
