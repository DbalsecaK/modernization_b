package app_test

import (
	"context"
	"errors"
	"slices"
	"testing"
	"time"

	"github.com/shopspring/decimal"

	"bancoficticio.com/payments/internal/app"
	"bancoficticio.com/payments/internal/domain"
)

// Tests of the reference implementation with in-memory ports (one per rule scenario).

var day = time.Date(2026, 9, 29, 10, 0, 0, 0, time.UTC)

func dec(text string) decimal.Decimal {
	return decimal.RequireFromString(text)
}

// world is the state the fake ports read and what they recorded.
type world struct {
	state   *string
	tariff  *domain.Tariff
	balance decimal.Decimal
	debited []decimal.Decimal
}

func newWorld() *world {
	return &world{
		state:   domain.Ptr("P"),
		tariff:  &domain.Tariff{Company: domain.Ptr(int32(7)), Service: domain.Ptr("PAGOS"), Amount: domain.Ptr(dec("1.25")), Separate: domain.Ptr(false)},
		balance: dec("500.00"),
	}
}

type orders struct{ w *world }

func (o orders) Find(_ context.Context, orderNumber, company *int32) (*domain.PaymentOrder, error) {
	if o.w.state == nil {
		return nil, nil
	}
	return &domain.PaymentOrder{OrderNumber: orderNumber, Company: company, State: o.w.state, Commission: domain.Ptr(decimal.Zero)}, nil
}

func (orders) MarkPaid(context.Context, *int32, *int32, *time.Time, *decimal.Decimal) (int, error) {
	return 1, nil
}

type tariffs struct{ w *world }

func (t tariffs) CompanyTariff(context.Context, *int32, *string) (*domain.Tariff, error) {
	return t.w.tariff, nil
}

func (tariffs) ServiceTariff(_ context.Context, service *string) (*domain.Tariff, error) {
	return &domain.Tariff{Company: domain.Ptr(int32(0)), Service: service, Amount: domain.Ptr(dec("2.00")), Separate: domain.Ptr(false)}, nil
}

type accounts struct{ w *world }

func (a accounts) Find(_ context.Context, number, typ *string) (*domain.Account, error) {
	return &domain.Account{Number: number, Type: typ, Balance: domain.Ptr(a.w.balance)}, nil
}

type debits struct{ w *world }

func (d debits) Debit(_ context.Context, _, _ *string, amount *decimal.Decimal, _ *string) (int64, error) {
	d.w.debited = append(d.w.debited, *amount)
	return 900 + int64(len(d.w.debited)), nil
}

func (w *world) pay(accountType, channel, service, amount string) (app.PayOrderResponse, error) {
	payOrder := app.NewPayOrderService(orders{w}, tariffs{w}, accounts{w}, debits{w})
	return payOrder.Execute(context.Background(), app.PayOrderRequest{
		OrderNumber: domain.Ptr(int32(1)), Company: domain.Ptr(int32(7)), Service: domain.Ptr(service),
		AccountType: domain.Ptr(accountType), Account: domain.Ptr("0012345678"), Amount: domain.Ptr(dec(amount)),
		Channel: domain.Ptr(channel), ProcessingDate: &day,
	})
}

func legacyCode(t *testing.T, err error) string {
	t.Helper()
	var rejection *domain.BusinessError
	if !errors.As(err, &rejection) {
		t.Fatalf("expected a BusinessError, got %v", err)
	}
	return rejection.LegacyCode
}

func assertDebited(t *testing.T, w *world, want ...string) {
	t.Helper()
	got := make([]string, len(w.debited))
	for i, amount := range w.debited {
		got[i] = amount.StringFixed(2)
	}
	if !slices.Equal(got, want) {
		t.Fatalf("debited %v, want %v", got, want)
	}
}

func TestACreditCardAccountCannotBeDebited(t *testing.T) {
	_, err := newWorld().pay("TCR", "WEB", "PAGOS", "10")
	if code := legacyCode(t, err); code != "50001" {
		t.Fatalf("legacy code %s, want 50001", code)
	}
}

func TestAWebOrderPaysHalfTheTariffRounded(t *testing.T) {
	w := newWorld()
	response, err := w.pay("CTE", "WEB", "PAGOS", "100.00")
	if err != nil {
		t.Fatal(err)
	}
	assertDebited(t, w, "100.63")
	if *response.Movement != 901 || *response.Message != "PAGO REALIZADO" {
		t.Fatalf("response %d %q", *response.Movement, *response.Message)
	}
}

func TestPayrollPaysNoCommission(t *testing.T) {
	w := newWorld()
	if _, err := w.pay("AHO", "OFI", "NOMINA", "100.00"); err != nil {
		t.Fatal(err)
	}
	assertDebited(t, w, "100.00")
}

func TestWithoutACompanyTariffTheGeneralTariffApplies(t *testing.T) {
	w := newWorld()
	w.tariff = nil
	if _, err := w.pay("CTE", "OFI", "PAGOS", "100.00"); err != nil {
		t.Fatal(err)
	}
	assertDebited(t, w, "102.00")
}

func TestASeparateCommissionIsASecondDebit(t *testing.T) {
	w := newWorld()
	w.tariff = &domain.Tariff{Company: domain.Ptr(int32(7)), Service: domain.Ptr("PAGOS"), Amount: domain.Ptr(dec("3.00")), Separate: domain.Ptr(true)}
	if _, err := w.pay("CTE", "OFI", "PAGOS", "100.00"); err != nil {
		t.Fatal(err)
	}
	assertDebited(t, w, "100.00", "3.00")
}

func TestAVirtualAccountCannotOverdrawButOthersCanUpTo100(t *testing.T) {
	w := newWorld()
	w.balance = dec("50.00")
	_, err := w.pay("VIR", "OFI", "PAGOS", "49.00")
	if code := legacyCode(t, err); code != "50004" {
		t.Fatalf("legacy code %s, want 50004", code)
	}
	if _, err := w.pay("CTE", "OFI", "PAGOS", "147.00"); err != nil {
		t.Fatal(err)
	}
	assertDebited(t, w, "148.25")
}

func TestAnOrderThatIsNotPendingIsRejected(t *testing.T) {
	w := newWorld()
	w.state = domain.Ptr("A")
	_, err := w.pay("CTE", "OFI", "PAGOS", "1")
	if code := legacyCode(t, err); code != "50003" {
		t.Fatalf("legacy code %s, want 50003", code)
	}
}
