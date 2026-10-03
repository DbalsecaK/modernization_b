using Bancoficticio.Payments.Domain.Model;
using Bancoficticio.Payments.Domain.Port;
using Bancoficticio.Payments.Infrastructure;
using Oracle.ManagedDataAccess.Client;

namespace Bancoficticio.Payments.Adapters.Out.Sql;

/// <summary>Accounts in Oracle (the column NUMBER is a reserved word: quoted). Reference adapter of the fictitious
/// application, written by hand.</summary>
public sealed class SqlAccountRepository(Db db) : AccountRepository
{
    public Account? Find(string? number, string? type)
    {
        using var command = db.Command(
            "SELECT \"NUMBER\", type, balance FROM account WHERE \"NUMBER\" = :account_number AND type = :account_type");
        command.Parameters.Add(new OracleParameter("account_number", OracleDbType.Char) { Value = (object?)number ?? DBNull.Value });
        command.Parameters.Add(new OracleParameter("account_type", OracleDbType.Char) { Value = (object?)type ?? DBNull.Value });
        using var reader = command.ExecuteReader();
        if (!reader.Read())
        {
            return null;
        }
        return new Account(reader.GetString(0), reader.GetString(1), reader.IsDBNull(2) ? null : reader.GetDecimal(2));
    }
}
