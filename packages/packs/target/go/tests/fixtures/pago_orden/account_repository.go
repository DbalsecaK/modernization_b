package pg

import (
	"context"
	"database/sql"
	"errors"
	"fmt"

	"bancoficticio.com/payments/internal/domain"
)

// AccountRepository keeps the accounts in PostgreSQL. Reference adapter of the fictitious application, written by
// hand.
type AccountRepository struct {
	db *DB
}

// NewAccountRepository is the adapter on the shared pool.
func NewAccountRepository(db *DB) *AccountRepository {
	return &AccountRepository{db: db}
}

// Find is the account, or nil when there is none.
func (r *AccountRepository) Find(ctx context.Context, number, typ *string) (*domain.Account, error) {
	var account domain.Account
	err := r.db.Q(ctx).QueryRowContext(ctx,
		"SELECT number, type, balance FROM account WHERE number = $1 AND type = $2", number, typ,
	).Scan(&account.Number, &account.Type, &account.Balance)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("find the account: %w", err)
	}
	return &account, nil
}
