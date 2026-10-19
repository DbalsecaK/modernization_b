using Bancoficticio.Payments.Domain.Model;
using Bancoficticio.Payments.Domain.Port;
using Bancoficticio.Payments.Infrastructure;

namespace Bancoficticio.Payments.Adapters.Out.Sql;

/// <summary>Company and general tariffs where the bank keeps them: db_admin..ad_tarifa_empresa and db_admin..ad_servicio
/// in Sybase ASE (ADR-0055, same database). The legacy stores the separate flag as 'S'/'N'. Reference adapter of the
/// fictitious application, written by hand.</summary>
public sealed class SqlTariffRepository(Db db) : TariffRepository
{
    public Tariff? CompanyTariff(int? company, string? service)
    {
        using var command = db.Command(
            "select tar_empresa, tar_servicio, tar_valor, tar_separada from db_admin..ad_tarifa_empresa "
            + "where tar_empresa = @company and tar_servicio = @service");
        command.Parameters.AddWithValue("@company", (object?)company ?? DBNull.Value);
        command.Parameters.AddWithValue("@service", (object?)service ?? DBNull.Value);
        using var reader = command.ExecuteReader();
        if (!reader.Read())
        {
            return null;
        }
        var separate = reader.IsDBNull(3) ? "" : reader.GetString(3).Trim();
        return new Tariff(reader.GetInt32(0), reader.GetString(1).TrimEnd(), reader.IsDBNull(2) ? null : reader.GetDecimal(2),
            string.Equals(separate, "S", StringComparison.OrdinalIgnoreCase));
    }

    public Tariff? ServiceTariff(string? service)
    {
        using var command = db.Command("select srv_codigo, srv_tarifa from db_admin..ad_servicio where srv_codigo = @service");
        command.Parameters.AddWithValue("@service", (object?)service ?? DBNull.Value);
        using var reader = command.ExecuteReader();
        if (!reader.Read())
        {
            return null;
        }
        return new Tariff(null, reader.GetString(0).TrimEnd(), reader.IsDBNull(1) ? null : reader.GetDecimal(1), false);
    }
}
