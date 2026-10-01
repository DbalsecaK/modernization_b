using Bancoficticio.Payments.Domain.Model;
using Bancoficticio.Payments.Domain.Port;
using Bancoficticio.Payments.Infrastructure;

namespace Bancoficticio.Payments.Adapters.Out.Sql;

/// <summary>Payment orders in SQL Server. Reference adapter of the fictitious application, written by hand.</summary>
public sealed class SqlOrderRepository(Db db) : OrderRepository
{
    public PaymentOrder? Find(int? orderNumber, int? company)
    {
        using var command = db.Command(
            "SELECT order_number, company, state, payment_date, commission FROM payment_order "
            + "WHERE order_number = @order AND company = @company");
        command.Parameters.AddWithValue("@order", (object?)orderNumber ?? DBNull.Value);
        command.Parameters.AddWithValue("@company", (object?)company ?? DBNull.Value);
        using var reader = command.ExecuteReader();
        if (!reader.Read())
        {
            return null;
        }
        return new PaymentOrder(
            reader.GetInt32(0), reader.GetInt32(1), reader.IsDBNull(2) ? null : reader.GetString(2),
            reader.IsDBNull(3) ? null : reader.GetDateTime(3), reader.IsDBNull(4) ? null : reader.GetDecimal(4));
    }

    public int MarkPaid(int? orderNumber, int? company, DateTime? paymentDate, decimal? commission)
    {
        using var command = db.Command(
            "UPDATE payment_order SET state = 'A', payment_date = @date, commission = @commission "
            + "WHERE order_number = @order AND company = @company");
        command.Parameters.AddWithValue("@date", (object?)paymentDate ?? DBNull.Value);
        command.Parameters.AddWithValue("@commission", (object?)commission ?? DBNull.Value);
        command.Parameters.AddWithValue("@order", (object?)orderNumber ?? DBNull.Value);
        command.Parameters.AddWithValue("@company", (object?)company ?? DBNull.Value);
        return command.ExecuteNonQuery();
    }
}
