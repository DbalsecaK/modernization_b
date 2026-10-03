using System.Data;
using Bancoficticio.Payments.Domain.Port;
using Bancoficticio.Payments.Infrastructure;
using Oracle.ManagedDataAccess.Client;

namespace Bancoficticio.Payments.Adapters.Out.Sql;

/// <summary>The debit program of the core banking system, a PL/SQL function in Oracle. Reference adapter of the
/// fictitious application: in the equivalence harness this port is replaced by what each golden case says the program
/// answered.</summary>
public sealed class SqlDebitGateway(Db db) : DebitGateway
{
    public long Debit(string? account, string? type, decimal? amount, string? reference)
    {
        using var command = db.Command("BEGIN :movement := core_debit(:account, :account_type, :amount, :reference); END;");
        var movement = new OracleParameter("movement", OracleDbType.Int64) { Direction = ParameterDirection.Output };
        command.Parameters.Add(movement);
        command.Parameters.Add(new OracleParameter("account", (object?)account ?? DBNull.Value));
        command.Parameters.Add(new OracleParameter("account_type", (object?)type ?? DBNull.Value));
        command.Parameters.Add(new OracleParameter("amount", (object?)amount ?? DBNull.Value));
        command.Parameters.Add(new OracleParameter("reference", (object?)reference ?? DBNull.Value));
        command.ExecuteNonQuery();
        return Convert.ToInt64(movement.Value?.ToString());
    }
}
