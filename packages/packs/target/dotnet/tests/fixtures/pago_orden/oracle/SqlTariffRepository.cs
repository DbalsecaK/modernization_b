using Bancoficticio.Payments.Domain.Model;
using Bancoficticio.Payments.Domain.Port;
using Bancoficticio.Payments.Infrastructure;
using Oracle.ManagedDataAccess.Client;

namespace Bancoficticio.Payments.Adapters.Out.Sql;

/// <summary>Company and general tariffs in Oracle. Reference adapter of the fictitious application, written by
/// hand.</summary>
public sealed class SqlTariffRepository(Db db) : TariffRepository
{
    public Tariff? CompanyTariff(int? company, string? service)
    {
        using var command = db.Command(
            "SELECT company, service, amount, separate FROM company_tariff WHERE company = :company AND service = :service");
        command.Parameters.Add(new OracleParameter("company", (object?)company ?? DBNull.Value));
        command.Parameters.Add(new OracleParameter("service", (object?)service ?? DBNull.Value));
        using var reader = command.ExecuteReader();
        if (!reader.Read())
        {
            return null;
        }
        return new Tariff(reader.GetInt32(0), reader.GetString(1), reader.IsDBNull(2) ? null : reader.GetDecimal(2),
            !reader.IsDBNull(3) && reader.GetBoolean(3));
    }

    public Tariff? ServiceTariff(string? service)
    {
        using var command = db.Command("SELECT service, amount FROM service_tariff WHERE service = :service");
        command.Parameters.Add(new OracleParameter("service", (object?)service ?? DBNull.Value));
        using var reader = command.ExecuteReader();
        if (!reader.Read())
        {
            return null;
        }
        return new Tariff(null, reader.GetString(0), reader.IsDBNull(1) ? null : reader.GetDecimal(1), false);
    }
}
