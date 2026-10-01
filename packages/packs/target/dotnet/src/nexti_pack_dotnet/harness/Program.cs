// Runs the golden master cases on the generated service (NexTI verification, spec 11.3 check 3). Written by the
// platform, never by a model: the real ADO.NET adapters against SQL Server, the external programs replaced by fakes
// that record their calls and answer what the case says, and the use case inside one transaction (a rejection
// undoes its writes and its external calls, as in the legacy). One JSON line per case, prefixed with "NXE ".
using System.Globalization;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Data.SqlClient;

var plan = JsonDocument.Parse(File.ReadAllText(args[0])).RootElement;
var cases = JsonDocument.Parse(File.ReadAllText(args[1])).RootElement;
using var connection = new SqlConnection(plan.GetProperty("connection").GetString());
connection.Open();
var db = Activator.CreateInstance(Harness.Find(plan, "db"), connection)!;
foreach (var testCase in cases.EnumerateArray())
{
    Console.WriteLine("NXE " + Harness.Run(plan, testCase, connection, db).ToJsonString());
}

public static class Harness
{
    public static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

    public static Type Find(JsonElement plan, string key) =>
        Type.GetType(plan.GetProperty(key).GetString()!, throwOnError: true)!;

    public static JsonObject Run(JsonElement plan, JsonElement testCase, SqlConnection connection, object db)
    {
        var output = new JsonObject { ["name"] = testCase.GetProperty("name").GetString() };
        var calls = new List<JsonObject>();
        try
        {
            foreach (var sql in plan.GetProperty("reset").EnumerateArray()) Execute(connection, sql.GetString()!);
            foreach (var sql in testCase.GetProperty("setup").EnumerateArray()) Execute(connection, sql.GetString()!);
            var service = Service(plan, testCase, db, calls);
            var requestType = Find(plan, "request");
            var request = Record(requestType, testCase.GetProperty("request"));
            var execute = service.GetType().GetMethod("Execute", [requestType])
                ?? throw new InvalidOperationException($"{service.GetType().Name} has no Execute({requestType.Name})");
            Invoke(db, "Begin");
            try
            {
                var response = execute.Invoke(service, [request]);
                Invoke(db, "Commit");
                output["response"] = Fields(response);
            }
            catch (TargetInvocationException e) when (e.InnerException is not null)
            {
                Invoke(db, "Rollback");
                calls.Clear(); // inside the rolled-back transaction: they had no effect
                var cause = e.InnerException;
                if (cause.GetType().Name != "BusinessError") throw cause;
                output["error"] = new JsonObject
                {
                    ["code"] = Text(Property(cause, "Code")),
                    ["legacy_code"] = Text(Property(cause, "LegacyCode")),
                    ["message"] = cause.Message,
                };
            }
            var tables = new JsonObject();
            foreach (var dump in plan.GetProperty("dump").EnumerateObject())
            {
                tables[dump.Name] = Rows(connection, dump.Value.GetString()!);
            }
            output["tables"] = tables;
            output["calls"] = new JsonArray(calls.Select(c => (JsonNode)c).ToArray());
        }
        catch (Exception e)
        {
            var cause = e is TargetInvocationException { InnerException: not null } t ? t.InnerException! : e;
            output["failure"] = $"{cause.GetType().FullName}: {cause.Message}";
        }
        return output;
    }

    static void Execute(SqlConnection connection, string sql)
    {
        using var command = connection.CreateCommand();
        command.CommandText = sql;
        command.ExecuteNonQuery();
    }

    static JsonArray Rows(SqlConnection connection, string sql)
    {
        var rows = new JsonArray();
        using var command = connection.CreateCommand();
        command.CommandText = sql;
        using var reader = command.ExecuteReader();
        while (reader.Read())
        {
            var row = new JsonObject();
            for (var i = 0; i < reader.FieldCount; i++)
            {
                row[reader.GetName(i)] = Text(reader.IsDBNull(i) ? null : reader.GetValue(i));
            }
            rows.Add(row);
        }
        return rows;
    }

    static object? Invoke(object target, string method) => target.GetType().GetMethod(method)!.Invoke(target, null);

    static object? Property(object target, string name) => target.GetType().GetProperty(name)?.GetValue(target);

    static object Service(JsonElement plan, JsonElement testCase, object db, List<JsonObject> calls)
    {
        var ports = new List<object>();
        foreach (var port in plan.GetProperty("ports").EnumerateArray())
        {
            var type = Type.GetType(port.GetProperty("interface").GetString()!, throwOnError: true)!;
            var adapter = port.GetProperty("adapter");
            if (adapter.ValueKind == JsonValueKind.String)
            {
                ports.Add(Activator.CreateInstance(Type.GetType(adapter.GetString()!, throwOnError: true)!, db)!);
                continue;
            }
            var fake = (FakePort)DispatchProxy.Create(type, typeof(FakePort));
            fake.Name = type.Name;
            fake.Calls = calls;
            fake.Answers = testCase.GetProperty("stubs").TryGetProperty(type.Name, out var answers) ? answers : default;
            ports.Add(fake);
        }
        var serviceType = Find(plan, "service");
        foreach (var constructor in serviceType.GetConstructors())
        {
            var parameters = constructor.GetParameters();
            var arguments = parameters.Select(p => ports.FirstOrDefault(p.ParameterType.IsInstanceOfType)).ToArray();
            if (arguments.All(a => a is not null)) return constructor.Invoke(arguments);
        }
        throw new InvalidOperationException($"{serviceType.Name} has no constructor taking its {ports.Count} ports");
    }

    static object Record(Type type, JsonElement values)
    {
        var constructor = type.GetConstructors().OrderByDescending(c => c.GetParameters().Length).First();
        var arguments = constructor.GetParameters().Select(p =>
        {
            var found = values.EnumerateObject()
                .FirstOrDefault(v => string.Equals(v.Name, p.Name, StringComparison.OrdinalIgnoreCase));
            var text = found.Value.ValueKind switch
            {
                JsonValueKind.String => found.Value.GetString(),
                JsonValueKind.Undefined or JsonValueKind.Null => null,
                _ => found.Value.GetRawText(),
            };
            return Convert(text, p.ParameterType);
        }).ToArray();
        return constructor.Invoke(arguments);
    }

    static JsonObject Fields(object? value)
    {
        var output = new JsonObject();
        if (value is null) return output;
        foreach (var property in value.GetType().GetProperties(BindingFlags.Public | BindingFlags.Instance))
        {
            if (property.Name == "EqualityContract") continue;
            output[char.ToLowerInvariant(property.Name[0]) + property.Name[1..]] = Text(property.GetValue(value));
        }
        return output;
    }

    public static string? Text(object? value) => value switch
    {
        null or DBNull => null,
        decimal d => d.ToString(Inv),
        bool b => b ? "true" : "false",
        DateOnly d => d.ToString("yyyy-MM-dd", Inv),
        DateTime t => t.ToString("yyyy-MM-ddTHH:mm:ss.fff", Inv),
        DateTimeOffset o => o.ToString("yyyy-MM-ddTHH:mm:ss.fffzzz", Inv),
        byte[] bytes => System.Convert.ToHexString(bytes).ToLowerInvariant(),
        IFormattable f => f.ToString(null, Inv),
        _ => value.ToString(),
    };

    public static object? Convert(string? text, Type type)
    {
        var target = Nullable.GetUnderlyingType(type) ?? type;
        if (text is null)
        {
            return type.IsValueType && Nullable.GetUnderlyingType(type) is null ? Activator.CreateInstance(type) : null;
        }
        if (target == typeof(int)) return decimal.ToInt32(decimal.Parse(text, Inv));
        if (target == typeof(long)) return decimal.ToInt64(decimal.Parse(text, Inv));
        if (target == typeof(short)) return decimal.ToInt16(decimal.Parse(text, Inv));
        if (target == typeof(decimal)) return decimal.Parse(text, NumberStyles.Float, Inv);
        if (target == typeof(bool)) return text is "1" or "true" or "True" or "TRUE";
        if (target == typeof(DateOnly)) return DateOnly.Parse(text[..10], Inv);
        if (target == typeof(DateTime)) return DateTime.Parse(text.Replace(' ', 'T'), Inv);
        if (target == typeof(DateTimeOffset)) return DateTimeOffset.Parse(text, Inv);
        if (target == typeof(byte[])) return System.Convert.FromHexString(text.Replace("0x", ""));
        return text;
    }
}

/// <summary>An external program replaced by what the case says it answered; every call is recorded.</summary>
public class FakePort : DispatchProxy
{
    public string Name { get; set; } = "";
    public List<JsonObject> Calls { get; set; } = [];
    public JsonElement Answers { get; set; }
    int index;

    protected override object? Invoke(MethodInfo? method, object?[]? args)
    {
        var call = new JsonObject
        {
            ["port"] = Name,
            ["method"] = char.ToLowerInvariant(method!.Name[0]) + method.Name[1..],
            ["arguments"] = new JsonArray((args ?? []).Select(a => (JsonNode?)JsonValue.Create(Harness.Text(a))).ToArray()),
        };
        Calls.Add(call);
        var has = Answers.ValueKind == JsonValueKind.Array && Answers.GetArrayLength() > 0;
        var answer = has ? Answers[Math.Min(index, Answers.GetArrayLength() - 1)] : default;
        index++;
        if (has && answer.TryGetProperty("returns", out var returns) && returns.ValueKind == JsonValueKind.Number
            && returns.GetInt32() != 0)
        {
            throw new InvalidOperationException($"{Name} answered {returns.GetInt32()}");
        }
        if (method.ReturnType == typeof(void)) return null;
        string? output = null;
        if (has && answer.TryGetProperty("output", out var value) && value.ValueKind != JsonValueKind.Null)
        {
            output = value.ValueKind == JsonValueKind.String ? value.GetString() : value.GetRawText();
        }
        return Harness.Convert(output, method.ReturnType);
    }
}
