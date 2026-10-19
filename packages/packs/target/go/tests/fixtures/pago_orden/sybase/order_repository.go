package pg

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"

	"github.com/shopspring/decimal"

	"bancoficticio.com/payments/internal/domain"
)

// OrderRepository keeps the payment orders where the bank keeps them: db_pagos..pg_orden in Sybase ASE (ADR-0055,
// same database). Reference adapter of the fictitious application, written by hand.
type OrderRepository struct {
	db *DB
}

// NewOrderRepository is the adapter on the shared pool.
func NewOrderRepository(db *DB) *OrderRepository {
	return &OrderRepository{db: db}
}

// Find is the order, or nil when there is none.
func (r *OrderRepository) Find(ctx context.Context, orderNumber, company *int32) (*domain.PaymentOrder, error) {
	var order domain.PaymentOrder
	err := r.db.Q(ctx).QueryRowContext(ctx,
		"select ord_numero, ord_empresa, rtrim(ord_estado), ord_fecha_pago, convert(varchar(40), ord_comision) from db_pagos..pg_orden where ord_numero = ? and ord_empresa = ?",
		orderNumber, company,
	).Scan(&order.OrderNumber, &order.Company, &order.State, &order.PaymentDate, &order.Commission)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("find the order: %w", err)
	}
	return &order, nil
}

// MarkPaid returns the rows updated.
func (r *OrderRepository) MarkPaid(ctx context.Context, orderNumber, company *int32, paymentDate *time.Time, commission *decimal.Decimal) (int, error) {
	result, err := r.db.Q(ctx).ExecContext(ctx,
		"update db_pagos..pg_orden set ord_estado = 'A', ord_fecha_pago = ?, ord_comision = convert(numeric(19,4), ?) where ord_numero = ? and ord_empresa = ?",
		paymentDate, decimalArg(commission), orderNumber, company,
	)
	if err != nil {
		return 0, fmt.Errorf("mark the order paid: %w", err)
	}
	updated, err := result.RowsAffected()
	if err != nil {
		return 0, fmt.Errorf("mark the order paid: %w", err)
	}
	return int(updated), nil
}

// decimalArg is an amount as text for T-SQL's convert (nil is null): the driver binds no decimal type of its own.
func decimalArg(value *decimal.Decimal) any {
	if value == nil {
		return nil
	}
	return value.String()
}
