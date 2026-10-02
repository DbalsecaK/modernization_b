package pg

import (
	"context"
	"database/sql"
	"errors"
	"fmt"

	"bancoficticio.com/payments/internal/domain"
)

// TariffRepository keeps the company and general tariffs in PostgreSQL. Reference adapter of the fictitious
// application, written by hand.
type TariffRepository struct {
	db *DB
}

// NewTariffRepository is the adapter on the shared pool.
func NewTariffRepository(db *DB) *TariffRepository {
	return &TariffRepository{db: db}
}

// CompanyTariff is the tariff of the company for the service, or nil.
func (r *TariffRepository) CompanyTariff(ctx context.Context, company *int32, service *string) (*domain.Tariff, error) {
	var tariff domain.Tariff
	err := r.db.Q(ctx).QueryRowContext(ctx,
		"SELECT company, service, amount, separate FROM company_tariff WHERE company = $1 AND service = $2",
		company, service,
	).Scan(&tariff.Company, &tariff.Service, &tariff.Amount, &tariff.Separate)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("find the company tariff: %w", err)
	}
	return &tariff, nil
}

// ServiceTariff is the general tariff of the service, never separate, or nil.
func (r *TariffRepository) ServiceTariff(ctx context.Context, service *string) (*domain.Tariff, error) {
	tariff := domain.Tariff{Separate: domain.Ptr(false)}
	err := r.db.Q(ctx).QueryRowContext(ctx,
		"SELECT service, amount FROM service_tariff WHERE service = $1", service,
	).Scan(&tariff.Service, &tariff.Amount)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("find the service tariff: %w", err)
	}
	return &tariff, nil
}
