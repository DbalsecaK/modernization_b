using Bancoficticio.Payments.Domain.Model;
using Bancoficticio.Payments.Domain.Port;
using Bancoficticio.Payments.Infrastructure;

namespace Bancoficticio.Payments.Adapters.Out.Sql;

/// <summary>Accounts where the bank keeps them: db_cuentas..ct_cuenta in Sybase ASE (ADR-0055, same database).
/// Reference adapter of the fictitious application, written by hand.</summary>
public sealed class SqlAccountRepository(Db db) : AccountRepository
{
    public Account? Find(string? number, string? type)
    {
        using var command = db.Command(
            "select cta_numero, cta_tipo, cta_saldo from db_cuentas..ct_cuenta where cta_numero = @number and cta_tipo = @type");
        command.Parameters.AddWithValue("@number", (object?)number ?? DBNull.Value);
        command.Parameters.AddWithValue("@type", (object?)type ?? DBNull.Value);
        using var reader = command.ExecuteReader();
        if (!reader.Read())
        {
            return null;
        }
        return new Account(reader.GetString(0).TrimEnd(), reader.GetString(1).TrimEnd(),
            reader.IsDBNull(2) ? null : reader.GetDecimal(2));
    }
}
