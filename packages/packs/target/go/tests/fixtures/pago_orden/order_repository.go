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

// OrderRepository keeps the payment orders in PostgreSQL. Reference adapter of the fictitious application, written
// by hand.
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
		"SELECT order_number, company, state, payment_date, commission FROM payment_order WHERE order_number = $1 AND company = $2",
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
		"UPDATE payment_order SET state = 'A', payment_date = $1, commission = $2 WHERE order_number = $3 AND company = $4",
		paymentDate, commission, orderNumber, company,
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
