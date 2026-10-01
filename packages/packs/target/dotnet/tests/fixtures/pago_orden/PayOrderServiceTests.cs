using Bancoficticio.Payments.Adapters.In.Rest;
using Bancoficticio.Payments.Application;
using Bancoficticio.Payments.Domain.Error;
using Bancoficticio.Payments.Domain.Model;
using Bancoficticio.Payments.Domain.Port;
using Xunit;

namespace Bancoficticio.Payments.Tests;

/// <summary>Tests of the reference implementation with in-memory ports (one per rule scenario).</summary>
public sealed class PayOrderServiceTests
{
    static readonly DateTime Day = new(2026, 9, 29, 10, 0, 0);

    readonly List<decimal?> debited = [];
    string? state = "P";
    Tariff? tariff = new(7, "PAGOS", 1.25m, false);
    decimal balance = 500.00m;

    sealed class Orders(PayOrderServiceTests test) : OrderRepository
    {
        public PaymentOrder? Find(int? orderNumber, int? company) =>
            test.state is null ? null : new PaymentOrder(orderNumber, company, test.state, null, 0m);

        public int MarkPaid(int? orderNumber, int? company, DateTime? paymentDate, decimal? commission) => 1;
    }

    sealed class Tariffs(PayOrderServiceTests test) : TariffRepository
    {
        public Tariff? CompanyTariff(int? company, string? service) => test.tariff;

        public Tariff? ServiceTariff(string? service) => new(0, service, 2.00m, false);
    }

    sealed class Accounts(PayOrderServiceTests test) : AccountRepository
    {
        public Account? Find(string? number, string? type) => new(number, type, test.balance);
    }

    sealed class Debits(PayOrderServiceTests test) : DebitGateway
    {
        public long Debit(string? account, string? type, decimal? amount, string? reference)
        {
            test.debited.Add(amount);
            return 900L + test.debited.Count;
        }
    }

    PayOrderService Service() => new(new Orders(this), new Tariffs(this), new Accounts(this), new Debits(this));

    static PayOrderRequest Request(string accountType, string channel, string service, decimal amount) =>
        new(1, 7, service, accountType, "0012345678", amount, channel, Day);

    [Fact]
    public void ACreditCardAccountCannotBeDebited()
    {
        var error = Assert.Throws<BusinessError>(() => Service().Execute(Request("TCR", "WEB", "PAGOS", 10m)));
        Assert.Equal("50001", error.LegacyCode);
    }

    [Fact]
    public void AWebOrderPaysHalfTheTariffRounded()
    {
        var response = Service().Execute(Request("CTE", "WEB", "PAGOS", 100.00m));
        Assert.Equal([100.63m], debited);
        Assert.Equal(901L, response.Movement);
        Assert.Equal("PAGO REALIZADO", response.Message);
    }

    [Fact]
    public void PayrollPaysNoCommission()
    {
        Service().Execute(Request("AHO", "OFI", "NOMINA", 100.00m));
        Assert.Equal([100.00m], debited);
    }

    [Fact]
    public void WithoutACompanyTariffTheGeneralTariffApplies()
    {
        tariff = null;
        Service().Execute(Request("CTE", "OFI", "PAGOS", 100.00m));
        Assert.Equal([102.00m], debited);
    }

    [Fact]
    public void ASeparateCommissionIsASecondDebit()
    {
        tariff = new Tariff(7, "PAGOS", 3.00m, true);
        Service().Execute(Request("CTE", "OFI", "PAGOS", 100.00m));
        Assert.Equal([100.00m, 3.00m], debited);
    }

    [Fact]
    public void AVirtualAccountCannotOverdrawButOthersCanUpTo100()
    {
        balance = 50.00m;
        var error = Assert.Throws<BusinessError>(() => Service().Execute(Request("VIR", "OFI", "PAGOS", 49.00m)));
        Assert.Equal("50004", error.LegacyCode);
        Service().Execute(Request("CTE", "OFI", "PAGOS", 147.00m));
        Assert.Equal([148.25m], debited);
    }

    [Fact]
    public void AnOrderThatIsNotPendingIsRejected()
    {
        state = "A";
        var error = Assert.Throws<BusinessError>(() => Service().Execute(Request("CTE", "OFI", "PAGOS", 1m)));
        Assert.Equal("50003", error.LegacyCode);
    }
}
