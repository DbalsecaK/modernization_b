package pg

import (
	"context"
	"database/sql"
	"errors"
	"fmt"

	"bancoficticio.com/payments/internal/domain"
)

// TariffRepository reads the company and general tariffs where the bank keeps them: db_admin..ad_tarifa_empresa and
// db_admin..ad_servicio in Sybase ASE (ADR-0055, same database). The legacy stores the separate flag as 'S'/'N'.
// Reference adapter of the fictitious application, written by hand.
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
		"select tar_empresa, rtrim(tar_servicio), convert(varchar(40), tar_valor), case when upper(tar_separada) = 'S' then 1 else 0 end from db_admin..ad_tarifa_empresa where tar_empresa = ? and tar_servicio = ?",
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
		"select rtrim(srv_codigo), convert(varchar(40), srv_tarifa) from db_admin..ad_servicio where srv_codigo = ?", service,
	).Scan(&tariff.Service, &tariff.Amount)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("find the service tariff: %w", err)
	}
	return &tariff, nil
}
