using Bancoficticio.Payments.Domain.Model;
using Bancoficticio.Payments.Domain.Port;
using Bancoficticio.Payments.Infrastructure;

namespace Bancoficticio.Payments.Adapters.Out.Sql;

/// <summary>Accounts in SQL Server. Reference adapter of the fictitious application, written by hand.</summary>
public sealed class SqlAccountRepository(Db db) : AccountRepository
{
    public Account? Find(string? number, string? type)
    {
        using var command = db.Command("SELECT number, type, balance FROM account WHERE number = @number AND type = @type");
        command.Parameters.AddWithValue("@number", (object?)number ?? DBNull.Value);
        command.Parameters.AddWithValue("@type", (object?)type ?? DBNull.Value);
        using var reader = command.ExecuteReader();
        if (!reader.Read())
        {
            return null;
        }
        return new Account(reader.GetString(0), reader.GetString(1), reader.IsDBNull(2) ? null : reader.GetDecimal(2));
    }
}
