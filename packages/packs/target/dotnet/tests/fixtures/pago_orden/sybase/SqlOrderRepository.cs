using Bancoficticio.Payments.Domain.Model;
using Bancoficticio.Payments.Domain.Port;
using Bancoficticio.Payments.Infrastructure;

namespace Bancoficticio.Payments.Adapters.Out.Sql;

/// <summary>Payment orders where the bank keeps them: db_pagos..pg_orden in Sybase ASE (ADR-0055, same database).
/// Reference adapter of the fictitious application, written by hand.</summary>
public sealed class SqlOrderRepository(Db db) : OrderRepository
{
    public PaymentOrder? Find(int? orderNumber, int? company)
    {
        using var command = db.Command(
            "select ord_numero, ord_empresa, ord_estado, ord_fecha_pago, ord_comision from db_pagos..pg_orden "
            + "where ord_numero = @order and ord_empresa = @company");
        command.Parameters.AddWithValue("@order", (object?)orderNumber ?? DBNull.Value);
        command.Parameters.AddWithValue("@company", (object?)company ?? DBNull.Value);
        using var reader = command.ExecuteReader();
        if (!reader.Read())
        {
            return null;
        }
        return new PaymentOrder(
            reader.GetInt32(0), reader.GetInt32(1), reader.IsDBNull(2) ? null : reader.GetString(2).TrimEnd(),
            reader.IsDBNull(3) ? null : reader.GetDateTime(3), reader.IsDBNull(4) ? null : reader.GetDecimal(4));
    }

    public int MarkPaid(int? orderNumber, int? company, DateTime? paymentDate, decimal? commission)
    {
        using var command = db.Command(
            "update db_pagos..pg_orden set ord_estado = 'A', ord_fecha_pago = @date, ord_comision = @commission "
            + "where ord_numero = @order and ord_empresa = @company");
        command.Parameters.AddWithValue("@date", (object?)paymentDate ?? DBNull.Value);
        command.Parameters.AddWithValue("@commission", (object?)commission ?? DBNull.Value);
        command.Parameters.AddWithValue("@order", (object?)orderNumber ?? DBNull.Value);
        command.Parameters.AddWithValue("@company", (object?)company ?? DBNull.Value);
        return command.ExecuteNonQuery();
    }
}
