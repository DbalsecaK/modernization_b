using Bancoficticio.Payments.Domain.Port;
using Bancoficticio.Payments.Infrastructure;

namespace Bancoficticio.Payments.Adapters.Out.Sql;

/// <summary>The debit program of the core banking system. Reference adapter of the fictitious application: in the
/// equivalence harness this port is replaced by what each golden case says the program answered.</summary>
public sealed class SqlDebitGateway(Db db) : DebitGateway
{
    public long Debit(string? account, string? type, decimal? amount, string? reference)
    {
        using var command = db.Command("EXEC core_debit @account, @type, @amount, @reference");
        command.Parameters.AddWithValue("@account", (object?)account ?? DBNull.Value);
        command.Parameters.AddWithValue("@type", (object?)type ?? DBNull.Value);
        command.Parameters.AddWithValue("@amount", (object?)amount ?? DBNull.Value);
        command.Parameters.AddWithValue("@reference", (object?)reference ?? DBNull.Value);
        return Convert.ToInt64(command.ExecuteScalar());
    }
}
