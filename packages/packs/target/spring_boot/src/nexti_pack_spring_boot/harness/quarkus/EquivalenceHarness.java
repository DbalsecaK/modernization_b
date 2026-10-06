package nexti.equivalence;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.File;
import java.lang.reflect.Constructor;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.lang.reflect.RecordComponent;
import java.math.BigDecimal;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import javax.sql.DataSource;

/**
 * Runs the golden master cases on the generated service (NexTI verification, spec 11.3 check 3). Written by the
 * platform, never by a model: the real JDBC adapters against PostgreSQL, the external programs replaced by fakes that
 * record their calls and answer what the case says, and the use case inside one transaction (a rejection undoes its
 * writes and its external calls, as in the legacy). One JSON line per case, prefixed with "NXE ".
 *
 * <p>The flavour of the Java pack with Quarkus (ADR-0028): the same cases and the same output as the Spring flavour,
 * with plain JDBC instead of Spring JDBC. The adapters take a {@code javax.sql.DataSource}; the harness gives them one
 * that always hands out the same connection (closing it does nothing), so the use case runs in one transaction.
 */
public final class EquivalenceHarness {

    private static final ObjectMapper JSON = new ObjectMapper();

    private EquivalenceHarness() {
    }

    public static void main(String[] args) throws Exception {
        JsonNode plan = JSON.readTree(new File(args[0]));
        JsonNode cases = JSON.readTree(new File(args[1]));
        String password = plan.has("password") ? plan.get("password").asText() : "";
        Connection connection = DriverManager.getConnection(
                plan.get("jdbc_url").asText(), plan.get("user").asText(), password);
        connection.setAutoCommit(true);
        // Session settings of the database (the date and number formats the cases are written in).
        if (plan.has("session")) {
            for (JsonNode sql : plan.get("session")) {
                execute(connection, sql.asText());
            }
        }
        DataSource dataSource = dataSource(connection);
        for (JsonNode testCase : cases) {
            System.out.println("NXE " + JSON.writeValueAsString(run(plan, testCase, connection, dataSource)));
        }
        connection.close();
    }

    /** A DataSource over one connection whose close does nothing: what the adapters open is the harness's. */
    private static DataSource dataSource(Connection connection) {
        Connection shared = (Connection) Proxy.newProxyInstance(Connection.class.getClassLoader(),
                new Class<?>[] {Connection.class}, (proxy, method, arguments) -> {
                    if (method.getName().equals("close") && method.getParameterCount() == 0) {
                        return null;
                    }
                    if (method.getName().equals("isClosed") && method.getParameterCount() == 0) {
                        return false;
                    }
                    try {
                        return method.invoke(connection, arguments);
                    } catch (InvocationTargetException e) {
                        throw e.getCause();
                    }
                });
        return (DataSource) Proxy.newProxyInstance(DataSource.class.getClassLoader(), new Class<?>[] {DataSource.class},
                (proxy, method, arguments) -> {
                    if (method.getName().equals("getConnection")) {
                        return shared;
                    }
                    if (method.getDeclaringClass() == Object.class) {
                        return method.getName().equals("toString") ? "harness DataSource"
                                : method.getName().equals("hashCode") ? System.identityHashCode(proxy)
                                : proxy == arguments[0];
                    }
                    throw new UnsupportedOperationException("DataSource." + method.getName());
                });
    }

    private static void execute(Connection connection, String sql) throws SQLException {
        try (Statement statement = connection.createStatement()) {
            statement.execute(sql);
        }
    }

    /** The rows of a query as column label -> value, like Spring's queryForList. */
    private static List<Map<String, Object>> rows(Connection connection, String sql) throws SQLException {
        List<Map<String, Object>> out = new ArrayList<>();
        try (Statement statement = connection.createStatement(); ResultSet result = statement.executeQuery(sql)) {
            ResultSetMetaData meta = result.getMetaData();
            while (result.next()) {
                Map<String, Object> row = new LinkedHashMap<>();
                for (int i = 1; i <= meta.getColumnCount(); i++) {
                    row.put(meta.getColumnLabel(i), result.getObject(i));
                }
                out.add(row);
            }
        }
        return out;
    }

    /** The use case in one transaction: committed when it returns, rolled back when it throws. */
    private static Object inTransaction(Connection connection, Method execute, Object service, Object request)
            throws SQLException {
        connection.setAutoCommit(false);
        try {
            Object response = invoke(execute, service, request);
            connection.commit();
            return response;
        } catch (RuntimeException e) {
            connection.rollback();
            throw e;
        } finally {
            connection.setAutoCommit(true);
        }
    }

    private static ObjectNode run(JsonNode plan, JsonNode testCase, Connection jdbc, DataSource dataSource) {
        ObjectNode out = JSON.createObjectNode();
        out.put("name", testCase.get("name").asText());
        List<ObjectNode> calls = new ArrayList<>();
        try {
            for (JsonNode sql : plan.get("reset")) {
                execute(jdbc, sql.asText());
            }
            for (JsonNode sql : testCase.get("setup")) {
                execute(jdbc, sql.asText());
            }
            Object service = service(plan, testCase, dataSource, calls);
            Object request = record(Class.forName(plan.get("request").asText()), testCase.get("request"));
            Method execute = service.getClass().getMethod("execute", request.getClass());
            try {
                out.set("response", fields(inTransaction(jdbc, execute, service, request)));
            } catch (RuntimeException e) {
                calls.clear(); // inside the rolled-back transaction: they had no effect
                if (!e.getClass().getSimpleName().equals("BusinessError")) {
                    throw e;
                }
                ObjectNode error = out.putObject("error");
                error.put("code", String.valueOf(call(e, "code")));
                error.put("legacy_code", String.valueOf(call(e, "legacyCode")));
                error.put("message", e.getMessage());
            }
            ObjectNode tables = out.putObject("tables");
            for (Map.Entry<String, JsonNode> entry : plan.get("dump").properties()) {
                ArrayNode printedRows = tables.putArray(entry.getKey());
                for (Map<String, Object> row : rows(jdbc, entry.getValue().asText())) {
                    ObjectNode printed = printedRows.addObject();
                    row.forEach((column, value) -> printed.put(column, text(value)));
                }
            }
            ArrayNode recorded = out.putArray("calls");
            calls.forEach(recorded::add);
        } catch (Exception e) {
            Throwable cause = e instanceof InvocationTargetException ite ? ite.getCause() : e;
            out.put("failure", cause.getClass().getName() + ": " + cause.getMessage() + where(cause, plan));
        }
        return out;
    }

    private static Object invoke(Method method, Object target, Object argument) {
        try {
            return method.invoke(target, argument);
        } catch (InvocationTargetException e) {
            if (e.getCause() instanceof RuntimeException runtime) {
                throw runtime;
            }
            throw new IllegalStateException(e.getCause());
        } catch (IllegalAccessException e) {
            throw new IllegalStateException(e);
        }
    }

    private static Object call(Object target, String name) {
        try {
            return target.getClass().getMethod(name).invoke(target);
        } catch (ReflectiveOperationException e) {
            return null;
        }
    }

    private static Object service(JsonNode plan, JsonNode testCase, DataSource dataSource, List<ObjectNode> calls)
            throws ReflectiveOperationException {
        List<Object> ports = new ArrayList<>();
        for (JsonNode port : plan.get("ports")) {
            Class<?> type = Class.forName(port.get("interface").asText());
            if (port.hasNonNull("adapter")) {
                ports.add(Class.forName(port.get("adapter").asText()).getConstructor(DataSource.class)
                        .newInstance(dataSource));
            } else {
                String name = type.getSimpleName();
                ports.add(fake(type, name, testCase.path("stubs").path(name), calls));
            }
        }
        Class<?> serviceType = Class.forName(plan.get("service").asText());
        for (Constructor<?> constructor : serviceType.getConstructors()) {
            if (constructor.getParameterCount() == ports.size()) {
                return constructor.newInstance(ports.toArray());
            }
        }
        throw new IllegalStateException(serviceType.getName() + " has no constructor with " + ports.size() + " ports");
    }

    private static Object fake(Class<?> type, String name, JsonNode answers, List<ObjectNode> calls) {
        Map<String, Integer> counter = new HashMap<>();
        return Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[] {type}, (proxy, method, arguments) -> {
            if (method.getDeclaringClass() == Object.class) {
                return method.getName().equals("toString") ? name : method.getName().equals("hashCode")
                        ? System.identityHashCode(proxy) : proxy == arguments[0];
            }
            ObjectNode call = JSON.createObjectNode();
            call.put("port", name);
            call.put("method", method.getName());
            ArrayNode printed = call.putArray("arguments");
            for (Object argument : arguments == null ? new Object[0] : arguments) {
                printed.add(text(argument));
            }
            calls.add(call);
            int index = counter.merge(name, 1, Integer::sum) - 1;
            JsonNode answer = answers.isArray() && answers.size() > 0 ? answers.get(Math.min(index, answers.size() - 1))
                    : JSON.createObjectNode();
            if (answer.path("returns").asInt(0) != 0) {
                throw new RuntimeException(name + " answered " + answer.path("returns").asInt());
            }
            JsonNode outputs = answer.path("outputs");
            if (outputs.isObject()) { // one call, every output: the entity the method returns (ADR-0043)
                return recordOf(method, outputs);
            }
            JsonNode output = answer.path("output");
            return convert(output.isMissingNode() || output.isNull() ? null : output.asText(), method.getReturnType());
        });
    }

    /** The entity a port method returns, built from the outputs of the case (Optional when the method says so). */
    private static Object recordOf(Method method, JsonNode outputs) throws ReflectiveOperationException {
        Class<?> type = method.getReturnType();
        if (type == java.util.Optional.class) {
            java.lang.reflect.Type generic = method.getGenericReturnType();
            if (generic instanceof java.lang.reflect.ParameterizedType parameterized) {
                Class<?> inner = (Class<?>) parameterized.getActualTypeArguments()[0];
                return java.util.Optional.of(record(inner, outputs));
            }
            return java.util.Optional.empty();
        }
        return type.isRecord() ? record(type, outputs) : null;
    }

    /** Where in the generated code the exception was raised: the first frame inside the base package. */
    private static String where(Throwable cause, JsonNode plan) {
        String service = plan.path("service").asText("");
        String base = service.contains(".application.") ? service.substring(0, service.indexOf(".application.")) : "";
        for (StackTraceElement frame : cause.getStackTrace()) {
            if (!base.isEmpty() && frame.getClassName().startsWith(base)) {
                return " at " + frame.getClassName() + "." + frame.getMethodName() + "(" + frame.getFileName() + ":"
                        + frame.getLineNumber() + ")";
            }
        }
        return "";
    }

    private static Object record(Class<?> type, JsonNode values) throws ReflectiveOperationException {
        RecordComponent[] components = type.getRecordComponents();
        Class<?>[] types = new Class<?>[components.length];
        Object[] arguments = new Object[components.length];
        for (int i = 0; i < components.length; i++) {
            types[i] = components[i].getType();
            JsonNode value = values.path(components[i].getName());
            arguments[i] = convert(value.isMissingNode() || value.isNull() ? null : value.asText(), types[i]);
        }
        return type.getDeclaredConstructor(types).newInstance(arguments);
    }

    private static ObjectNode fields(Object value) throws RuntimeException {
        ObjectNode out = JSON.createObjectNode();
        if (value == null || !value.getClass().isRecord()) {
            return out;
        }
        for (RecordComponent component : value.getClass().getRecordComponents()) {
            try {
                out.put(component.getName(), text(component.getAccessor().invoke(value)));
            } catch (ReflectiveOperationException e) {
                throw new IllegalStateException(e);
            }
        }
        return out;
    }

    private static String text(Object value) {
        if (value instanceof Optional<?> optional) {
            return optional.map(EquivalenceHarness::text).orElse(null);
        }
        if (value instanceof BigDecimal decimal) {
            return decimal.toPlainString();
        }
        return value == null ? null : value.toString();
    }

    private static Object convert(String text, Class<?> type) {
        if (text == null) {
            if (type == long.class) {
                return 0L;
            }
            if (type == int.class) {
                return 0;
            }
            return type == boolean.class ? Boolean.FALSE : null;
        }
        if (type == Integer.class || type == int.class) {
            return new BigDecimal(text).intValueExact();
        }
        if (type == Long.class || type == long.class) {
            return new BigDecimal(text).longValueExact();
        }
        if (type == BigDecimal.class) {
            return new BigDecimal(text);
        }
        if (type == Boolean.class || type == boolean.class) {
            return Boolean.valueOf(text);
        }
        if (type == LocalDateTime.class) {
            return LocalDateTime.parse(text.replace(' ', 'T'));
        }
        if (type == LocalDate.class) {
            return LocalDate.parse(text.substring(0, 10));
        }
        if (type == OffsetDateTime.class) {
            return OffsetDateTime.parse(text);
        }
        return text;
    }
}
