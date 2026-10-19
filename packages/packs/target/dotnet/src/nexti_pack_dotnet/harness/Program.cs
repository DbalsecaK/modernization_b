// Runs the golden master cases on the generated service (NexTI verification, spec 11.3 check 3). Written by the
// platform, never by a model: the real ADO.NET adapters against the database (SQL Server or Oracle, or the legacy's
// own Sybase ASE with same_database: the plan names the provider's connection class and the session settings), the
// external programs replaced by fakes that record their calls and answer what the case says (or, on the legacy's
// engine, by its substitutes, whose calls the engine logs), and the use case inside one transaction (a rejection
// undoes its writes and its external calls, as in the legacy). One JSON line per case, prefixed with "NXE ".
using System.Data.Common;
using System.Globalization;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Nodes;

var plan = JsonDocument.Parse(File.ReadAllText(args[0])).RootElement;
var cases = JsonDocument.Parse(File.ReadAllText(args[1])).RootElement;
// Delivered with the project (ADR-0056, phase E): with a third argument, expected.json, every result is compared with
// what the platform observed when the verdict was signed, and any difference fails the run.
var expected = args.Length > 2 ? JsonNode.Parse(File.ReadAllText(args[2]))!.AsObject() : null;
var results = new List<JsonObject>();
using var connection = Harness.Connect(plan);
var db = Activator.CreateInstance(Harness.Find(plan, "db"), connection)!;
foreach (var testCase in cases.EnumerateArray())
{
    results.Add(Harness.Run(plan, testCase, connection, db));
}
if (plan.TryGetProperty("concurrency", out var wanted) && wanted.ValueKind == JsonValueKind.String)
{
    results.Add(Harness.Concurrency(plan, cases, wanted.GetString()!, connection, db));
}
foreach (var result in results)
{
    Console.WriteLine("NXE " + result.ToJsonString());
}
if (expected is not null)
{
    var differing = 0;
    foreach (var result in results)
    {
        var name = result["name"]!.GetValue<string>();
        if (!expected.TryGetPropertyValue(name, out var want) || want is null) continue;
        var actual = result.DeepClone().AsObject();
        foreach (var key in new[] { "name", "sequential", "concurrent" }) actual.Remove(key);
        if (!JsonNode.DeepEquals(actual, want))
        {
            differing++;
            Console.WriteLine($"DIFF {name}: expected {want.ToJsonString()} but was {actual.ToJsonString()}");
        }
    }
    Console.WriteLine(differing == 0 ? "GOLDEN MASTER REPRODUCED" : $"{differing} case(s) no longer reproduce the proven behaviour");
    return differing == 0 ? 0 : 1;
}
return 0;

public static class Harness
{
    public static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

    public static Type Find(JsonElement plan, string key) =>
        Type.GetType(plan.GetProperty(key).GetString()!, throwOnError: true)!;

    /// A new connection of the plan's provider, opened, with the plan's session settings.
    public static DbConnection Connect(JsonElement plan)
    {
        var connection = (DbConnection)Activator.CreateInstance(Find(plan, "provider"))!;
        // The delivered plan carries no credentials: the customer's test engine comes from the environment.
        var planned = plan.GetProperty("connection").GetString();
        connection.ConnectionString = string.IsNullOrEmpty(planned)
            ? Environment.GetEnvironmentVariable("NEXTI_LEGACY_CONNECTION")
                ?? throw new InvalidOperationException("set NEXTI_LEGACY_CONNECTION to the test engine's connection string")
            : planned;
        connection.Open();
        if (plan.TryGetProperty("session", out var session))
        {
            foreach (var sql in session.EnumerateArray()) Execute(connection, sql.GetString()!);
        }
        return connection;
    }

    public static JsonObject Run(JsonElement plan, JsonElement testCase, DbConnection connection, object db,
        bool prepare = true)
    {
        var output = new JsonObject { ["name"] = testCase.GetProperty("name").GetString() };
        var calls = new List<JsonObject>();
        var undone = new List<JsonObject>();
        try
        {
            if (prepare)
            {
                foreach (var sql in plan.GetProperty("reset").EnumerateArray()) Execute(connection, sql.GetString()!);
                foreach (var sql in testCase.GetProperty("setup").EnumerateArray()) Execute(connection, sql.GetString()!);
            }
            var (service, ports) = Service(plan, testCase, db, calls);
            var error = Execute(plan, testCase, service, db, out var response);
            if (error is null)
            {
                output["response"] = Fields(response);
            }
            else
            {
                // The rollback undoes the tables and the effects of the calls made inside the transaction: they are
                // reported apart, as "undone", like the legacy calls its rollback erased (ADR-0055).
                undone.AddRange(calls);
                calls.Clear();
                output["error"] = new JsonObject
                {
                    ["code"] = Text(Property(error, "Code")),
                    ["legacy_code"] = Text(Property(error, "LegacyCode")),
                    ["message"] = error.Message,
                };
            }
            // The messages the called programs raised through the generated adapters (ADR-0056): what the legacy's
            // caller saw from them, the target's caller sees too.
            output["messages"] = new JsonArray(Messages(ports).Select(m => (JsonNode)JsonValue.Create(m)!).ToArray());
            output["tables"] = Tables(plan, connection);
            output["calls"] = new JsonArray(calls.Select(c => (JsonNode)c).ToArray());
            output["undone"] = new JsonArray(undone.Select(c => (JsonNode)c).ToArray());
            if (plan.TryGetProperty("calls", out var logQuery) && logQuery.ValueKind == JsonValueKind.String)
            {
                // The legacy's engine logged the calls that survived the use case's transaction (ADR-0055).
                var logged = new JsonArray();
                foreach (var row in Rows(connection, logQuery.GetString()!))
                {
                    logged.Add(new JsonObject
                    {
                        ["program"] = row!["program"]?.DeepClone(),
                        ["args"] = row["args"]?.DeepClone(),
                    });
                }
                output["legacy_calls"] = logged;
            }
        }
        catch (Exception e)
        {
            var cause = e is TargetInvocationException { InnerException: not null } t ? t.InnerException! : e;
            output["failure"] = $"{cause.GetType().FullName}: {cause.Message}";
        }
        return output;
    }

    /// Runs the use case as the request does: inside one transaction, or (phase F) letting the service own it and
    /// closing only what it left open. Returns the business error of a rejection; any other failure is thrown.
    static Exception? Execute(JsonElement plan, JsonElement testCase, object service, object db, out object? response)
    {
        var requestType = Find(plan, "request");
        var request = Record(requestType, testCase.GetProperty("request"));
        var execute = service.GetType().GetMethod("Execute", [requestType])
            ?? throw new InvalidOperationException($"{service.GetType().Name} has no Execute({requestType.Name})");
        var owned = plan.TryGetProperty("service_transaction", out var flag) && flag.ValueKind == JsonValueKind.True;
        if (!owned) Invoke(db, "Begin");
        try
        {
            response = execute.Invoke(service, [request]);
            Invoke(db, "Commit");
            return null;
        }
        catch (TargetInvocationException e) when (e.InnerException is not null)
        {
            Invoke(db, "Rollback");
            response = null;
            if (e.InnerException.GetType().Name != "BusinessError") throw e.InnerException;
            return e.InnerException;
        }
    }

    /// ADR-0056 (point 12): the case runs twice at the same time, each run on its own connection, on the same rows;
    /// the final state must be the one of running it twice one after the other (serializable), and neither run may
    /// fail with a lock or a deadlock the sequential runs do not have.
    public static JsonObject Concurrency(JsonElement plan, JsonElement cases, string name, DbConnection connection,
        object db)
    {
        var output = new JsonObject { ["name"] = "__concurrency__", ["case"] = name };
        var testCase = cases.EnumerateArray().FirstOrDefault(c => c.GetProperty("name").GetString() == name);
        if (testCase.ValueKind != JsonValueKind.Object)
        {
            output["failure"] = "the plan names a case that is not in the suite: " + name;
            return output;
        }
        Run(plan, testCase, connection, db);
        var sequential = Run(plan, testCase, connection, db, prepare: false)["tables"]?.DeepClone();
        foreach (var sql in plan.GetProperty("reset").EnumerateArray()) Execute(connection, sql.GetString()!);
        foreach (var sql in testCase.GetProperty("setup").EnumerateArray()) Execute(connection, sql.GetString()!);
        var failures = new System.Collections.Concurrent.ConcurrentBag<string>();
        using var ready = new CountdownEvent(2);
        using var go = new ManualResetEventSlim(false);
        void One()
        {
            try
            {
                using var own = Connect(plan);
                var ownDb = Activator.CreateInstance(Find(plan, "db"), own)!;
                var (service, _) = Service(plan, testCase, ownDb, []);
                ready.Signal();
                go.Wait();
                Execute(plan, testCase, service, ownDb, out _);
            }
            catch (Exception e)
            {
                var cause = e is TargetInvocationException { InnerException: not null } t ? t.InnerException! : e;
                failures.Add($"{cause.GetType().FullName}: {cause.Message}");
            }
        }
        var a = new Thread(One) { Name = "nexti-concurrent-a" };
        var b = new Thread(One) { Name = "nexti-concurrent-b" };
        a.Start();
        b.Start();
        ready.Wait(TimeSpan.FromSeconds(120));
        go.Set();
        if (!a.Join(TimeSpan.FromSeconds(120)) || !b.Join(TimeSpan.FromSeconds(120)))
        {
            failures.Add("a run did not finish in 120 s (a lock the sequential runs do not have)");
        }
        var concurrent = Tables(plan, connection);
        output["failures"] = new JsonArray(failures.Select(f => (JsonNode)JsonValue.Create(f)!).ToArray());
        output["sequential"] = sequential;
        output["concurrent"] = concurrent;
        output["serializable"] = failures.IsEmpty && JsonNode.DeepEquals(sequential, concurrent);
        return output;
    }

    static JsonObject Tables(JsonElement plan, DbConnection connection)
    {
        var tables = new JsonObject();
        foreach (var dump in plan.GetProperty("dump").EnumerateObject())
        {
            tables[dump.Name] = Rows(connection, dump.Value.GetString()!);
        }
        return tables;
    }

    public static void Execute(DbConnection connection, string sql)
    {
        using var command = connection.CreateCommand();
        command.CommandText = sql;
        command.ExecuteNonQuery();
    }

    /// The rows a transactional substitute leaves (ADR-0055), written through the generated Db so they join the use
    /// case's transaction and a rejection undoes them. Returns the rows the statement changed.
    public static int Apply(object db, string sql)
    {
        var connection = (DbConnection)Property(db, "Connection")!;
        using var command = connection.CreateCommand();
        command.CommandText = sql;
        command.Transaction = Property(db, "Transaction") as DbTransaction;
        return command.ExecuteNonQuery();
    }

    static JsonArray Rows(DbConnection connection, string sql)
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

    /// The messages the adapters of the called programs kept (their Messages()), in the order of the ports.
    static List<string> Messages(IEnumerable<object> ports)
    {
        var found = new List<string>();
        foreach (var port in ports)
        {
            if (port.GetType().GetMethod("Messages", Type.EmptyTypes)?.Invoke(port, null) is IEnumerable<string> kept)
            {
                found.AddRange(kept);
            }
        }
        return found;
    }

    static object? Invoke(object target, string method) => target.GetType().GetMethod(method)!.Invoke(target, null);

    static object? Property(object target, string name) => target.GetType().GetProperty(name)?.GetValue(target);

    static (object Service, List<object> Ports) Service(JsonElement plan, JsonElement testCase, object db,
        List<JsonObject> calls)
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
            fake.Apply = sql => Apply(db, sql);
            fake.Answers = testCase.GetProperty("stubs").TryGetProperty(type.Name, out var answers) ? answers : default;
            ports.Add(fake);
        }
        var serviceType = Find(plan, "service");
        foreach (var constructor in serviceType.GetConstructors())
        {
            var parameters = constructor.GetParameters();
            var arguments = parameters.Select(p => ports.FirstOrDefault(p.ParameterType.IsInstanceOfType)).ToArray();
            if (arguments.All(a => a is not null)) return (constructor.Invoke(arguments), ports);
        }
        throw new InvalidOperationException($"{serviceType.Name} has no constructor taking its {ports.Count} ports");
    }

    public static object Record(Type type, JsonElement values)
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
    public Func<string, int>? Apply { get; set; }
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
        // A transactional substitute (ADR-0055): the rows the program leaves, inside the use case's transaction.
        if (has && answer.TryGetProperty("effects", out var effects) && effects.ValueKind == JsonValueKind.Array)
        {
            foreach (var effect in effects.EnumerateArray())
            {
                var changed = effect.TryGetProperty("update", out var update) && update.ValueKind == JsonValueKind.String
                    ? Apply!(update.GetString()!) : 0;
                if (changed == 0) Apply!(effect.GetProperty("insert").GetString()!);
            }
        }
        var carriesStatus = has && answer.TryGetProperty("carries_status", out var carries)
            && carries.ValueKind == JsonValueKind.True;
        if (has && !carriesStatus && answer.TryGetProperty("returns", out var returns)
            && returns.ValueKind == JsonValueKind.Number && returns.GetInt32() != 0)
        {
            throw new InvalidOperationException($"{Name} answered {returns.GetInt32()}");
        }
        if (method.ReturnType == typeof(void)) return null;
        // One call, every output (ADR-0043): the entity the method returns, built from the outputs of the case
        // (the status among them when the design maps it to `return`, ADR-0055 phase F).
        if (has && answer.TryGetProperty("outputs", out var outputs) && outputs.ValueKind == JsonValueKind.Object)
        {
            return Harness.Record(Nullable.GetUnderlyingType(method.ReturnType) ?? method.ReturnType, outputs);
        }
        string? output = null;
        if (has && answer.TryGetProperty("output", out var value) && value.ValueKind != JsonValueKind.Null)
        {
            output = value.ValueKind == JsonValueKind.String ? value.GetString() : value.GetRawText();
        }
        return Harness.Convert(output, method.ReturnType);
    }
}
