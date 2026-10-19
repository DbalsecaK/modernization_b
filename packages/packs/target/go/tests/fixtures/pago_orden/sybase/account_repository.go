package pg

import (
	"context"
	"database/sql"
	"errors"
	"fmt"

	"bancoficticio.com/payments/internal/domain"
)

// AccountRepository reads the accounts where the bank keeps them: db_cuentas..ct_cuenta in Sybase ASE (ADR-0055,
// same database). Reference adapter of the fictitious application, written by hand.
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
		"select rtrim(cta_numero), rtrim(cta_tipo), convert(varchar(40), cta_saldo) from db_cuentas..ct_cuenta where cta_numero = ? and cta_tipo = ?",
		number, typ,
	).Scan(&account.Number, &account.Type, &account.Balance)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("find the account: %w", err)
	}
	return &account, nil
}
