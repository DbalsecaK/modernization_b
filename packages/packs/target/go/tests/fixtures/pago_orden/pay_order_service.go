package app

import (
	"context"

	"github.com/shopspring/decimal"

	"bancoficticio.com/payments/internal/domain"
	"bancoficticio.com/payments/internal/ports"
)

var (
	payOrderDebitable = map[string]bool{"CTE": true, "AHO": true, "VIR": true}
	payOrderOverdraft = decimal.RequireFromString("100.00")
)

// PayOrderService pays one order (RULE-001..RULE-009). Reference implementation of the fictitious application,
// written by hand.
type PayOrderService struct {
	orders   ports.OrderRepository
	tariffs  ports.TariffRepository
	accounts ports.AccountRepository
	debits   ports.DebitGateway
}

// NewPayOrderService takes the ports of the use case in the order the design lists them.
func NewPayOrderService(orders ports.OrderRepository, tariffs ports.TariffRepository, accounts ports.AccountRepository, debits ports.DebitGateway) *PayOrderService {
	return &PayOrderService{orders: orders, tariffs: tariffs, accounts: accounts, debits: debits}
}

// Execute pays the order of the request or rejects it with a BusinessError.
func (s *PayOrderService) Execute(ctx context.Context, req PayOrderRequest) (PayOrderResponse, error) {
	accountType := domain.Deref(req.AccountType)
	if !payOrderDebitable[accountType] {
		return PayOrderResponse{}, domain.NewBusinessError("ACCOUNT_TYPE_NOT_ALLOWED", "50001", "TIPO DE CUENTA NO PERMITIDO")
	}
	order, err := s.orders.Find(ctx, req.OrderNumber, req.Company)
	if err != nil {
		return PayOrderResponse{}, err
	}
	if order == nil {
		return PayOrderResponse{}, domain.NewBusinessError("ORDER_NOT_FOUND", "50002", "ORDEN NO EXISTE")
	}
	if domain.Deref(order.State) != "P" {
		return PayOrderResponse{}, domain.NewBusinessError("ORDER_NOT_PENDING", "50003", "ORDEN NO ESTA PENDIENTE")
	}
	tariff, err := s.tariffs.CompanyTariff(ctx, req.Company, req.Service)
	if err != nil {
		return PayOrderResponse{}, err
	}
	if tariff == nil {
		if tariff, err = s.tariffs.ServiceTariff(ctx, req.Service); err != nil {
			return PayOrderResponse{}, err
		}
	}
	if tariff == nil {
		tariff = &domain.Tariff{Company: req.Company, Service: req.Service, Amount: domain.Ptr(decimal.Zero), Separate: domain.Ptr(false)}
	}
	amount := domain.Deref(tariff.Amount)
	commission := amount
	if domain.Deref(req.Channel) == "WEB" {
		commission = amount.DivRound(decimal.NewFromInt(2), 2)
	}
	if domain.Deref(req.Service) == "NOMINA" {
		commission = decimal.Zero
	}
	separate := domain.Deref(tariff.Separate)
	total := domain.Deref(req.Amount)
	if !separate {
		total = total.Add(commission)
	}
	balance := decimal.Zero
	account, err := s.accounts.Find(ctx, req.Account, req.AccountType)
	if err != nil {
		return PayOrderResponse{}, err
	}
	if account != nil {
		balance = domain.Deref(account.Balance)
	}
	virtual := accountType == "VIR"
	if (virtual && balance.LessThan(total)) || (!virtual && balance.Add(payOrderOverdraft).LessThan(total)) {
		return PayOrderResponse{}, domain.NewBusinessError("INSUFFICIENT_FUNDS", "50004", "FONDOS INSUFICIENTES")
	}
	movement, err := s.debits.Debit(ctx, req.Account, req.AccountType, &total, domain.Ptr("PAGO ORDEN"))
	if err != nil {
		return PayOrderResponse{}, domain.NewBusinessError("DEBIT_FAILED", "50005", "ERROR EN DEBITO")
	}
	if separate && commission.IsPositive() {
		if _, err := s.debits.Debit(ctx, req.Account, req.AccountType, &commission, domain.Ptr("COMISION PAGO")); err != nil {
			return PayOrderResponse{}, domain.NewBusinessError("COMMISSION_FAILED", "50006", "ERROR EN COMISION")
		}
	}
	updated, err := s.orders.MarkPaid(ctx, req.OrderNumber, req.Company, req.ProcessingDate, &commission)
	if err != nil {
		return PayOrderResponse{}, err
	}
	if updated == 0 {
		return PayOrderResponse{}, domain.NewBusinessError("ORDER_NOT_UPDATED", "50007", "ERROR ACTUALIZANDO ORDEN")
	}
	return PayOrderResponse{Movement: &movement, Message: domain.Ptr("PAGO REALIZADO")}, nil
}
