package pg

import (
	"context"
	"fmt"

	"github.com/shopspring/decimal"
)

// DebitGateway calls the debit program of the core banking system. Reference adapter of the fictitious application:
// in the equivalence harness this port is replaced by what each golden case says the program answered.
type DebitGateway struct {
	db *DB
}

// NewDebitGateway is the adapter on the shared pool.
func NewDebitGateway(db *DB) *DebitGateway {
	return &DebitGateway{db: db}
}

// Debit debits the account and returns the movement number; it fails when the program does.
func (g *DebitGateway) Debit(ctx context.Context, account, typ *string, amount *decimal.Decimal, reference *string) (int64, error) {
	var movement int64
	err := g.db.Q(ctx).QueryRowContext(ctx, "SELECT core_debit($1, $2, $3, $4)", account, typ, amount, reference).Scan(&movement)
	if err != nil {
		return 0, fmt.Errorf("debit: %w", err)
	}
	return movement, nil
}
