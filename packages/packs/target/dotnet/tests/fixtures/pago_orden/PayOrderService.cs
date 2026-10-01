using Bancoficticio.Payments.Adapters.In.Rest;
using Bancoficticio.Payments.Domain.Error;
using Bancoficticio.Payments.Domain.Model;
using Bancoficticio.Payments.Domain.Port;

namespace Bancoficticio.Payments.Application;

/// <summary>Pays one order (RULE-001..RULE-009). Reference implementation of the fictitious application, written by
/// hand.</summary>
public sealed class PayOrderService(
    OrderRepository orders, TariffRepository tariffs, AccountRepository accounts, DebitGateway debits)
{
    static readonly HashSet<string> Debitable = ["CTE", "AHO", "VIR"];
    const decimal Overdraft = 100.00m;

    public PayOrderResponse Execute(PayOrderRequest request)
    {
        if (request.AccountType is null || !Debitable.Contains(request.AccountType))
        {
            throw new BusinessError("ACCOUNT_TYPE_NOT_ALLOWED", "50001", "TIPO DE CUENTA NO PERMITIDO");
        }
        var order = orders.Find(request.OrderNumber, request.Company)
            ?? throw new BusinessError("ORDER_NOT_FOUND", "50002", "ORDEN NO EXISTE");
        if (order.State != "P")
        {
            throw new BusinessError("ORDER_NOT_PENDING", "50003", "ORDEN NO ESTA PENDIENTE");
        }
        var tariff = tariffs.CompanyTariff(request.Company, request.Service)
            ?? tariffs.ServiceTariff(request.Service)
            ?? new Tariff(request.Company, request.Service, 0m, false);
        var amount = tariff.Amount ?? 0m;
        var commission = request.Channel == "WEB" ? Math.Round(amount / 2, 2, MidpointRounding.AwayFromZero) : amount;
        if (request.Service == "NOMINA")
        {
            commission = 0m;
        }
        var separate = tariff.Separate == true;
        var requested = request.Amount ?? 0m;
        var total = separate ? requested : requested + commission;
        var balance = accounts.Find(request.Account, request.AccountType)?.Balance ?? 0m;
        var isVirtual = request.AccountType == "VIR";
        if ((isVirtual && balance < total) || (!isVirtual && balance + Overdraft < total))
        {
            throw new BusinessError("INSUFFICIENT_FUNDS", "50004", "FONDOS INSUFICIENTES");
        }
        long movement;
        try
        {
            movement = debits.Debit(request.Account, request.AccountType, total, "PAGO ORDEN");
        }
        catch (Exception e) when (e is not BusinessError)
        {
            throw new BusinessError("DEBIT_FAILED", "50005", "ERROR EN DEBITO");
        }
        if (separate && commission > 0)
        {
            try
            {
                debits.Debit(request.Account, request.AccountType, commission, "COMISION PAGO");
            }
            catch (Exception e) when (e is not BusinessError)
            {
                throw new BusinessError("COMMISSION_FAILED", "50006", "ERROR EN COMISION");
            }
        }
        if (orders.MarkPaid(request.OrderNumber, request.Company, request.ProcessingDate, commission) == 0)
        {
            throw new BusinessError("ORDER_NOT_UPDATED", "50007", "ERROR ACTUALIZANDO ORDEN");
        }
        return new PayOrderResponse(movement, "PAGO REALIZADO");
    }
}
