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
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Runs the golden master cases on the generated service (NexTI verification, spec 11.3 check 3). Written by the
 * platform, never by a model: the real JDBC adapters against PostgreSQL, the external programs replaced by fakes that
 * record their calls and answer what the case says, and the use case inside one transaction (a rejection undoes its
 * writes and its external calls, as in the legacy). One JSON line per case, prefixed with "NXE ".
 */
public final class EquivalenceHarness {

    private static final ObjectMapper JSON = new ObjectMapper();

    private EquivalenceHarness() {
    }

    public static void main(String[] args) throws Exception {
        JsonNode plan = JSON.readTree(new File(args[0]));
        JsonNode cases = JSON.readTree(new File(args[1]));
        String password = plan.has("password") ? plan.get("password").asText() : "";
        SingleConnectionDataSource dataSource = new SingleConnectionDataSource(
                plan.get("jdbc_url").asText(), plan.get("user").asText(), password, true);
        JdbcTemplate jdbc = new JdbcTemplate(dataSource);
        // Session settings of the database (Oracle: the date and number formats the cases are written in).
        if (plan.has("session")) {
            for (JsonNode sql : plan.get("session")) {
                jdbc.execute(sql.asText());
            }
        }
        TransactionTemplate transaction = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
        for (JsonNode testCase : cases) {
            System.out.println("NXE " + JSON.writeValueAsString(run(plan, testCase, jdbc, transaction)));
        }
        dataSource.destroy();
    }

    private static ObjectNode run(JsonNode plan, JsonNode testCase, JdbcTemplate jdbc, TransactionTemplate transaction) {
        ObjectNode out = JSON.createObjectNode();
        out.put("name", testCase.get("name").asText());
        List<ObjectNode> calls = new ArrayList<>();
        try {
            for (JsonNode sql : plan.get("reset")) {
                jdbc.execute(sql.asText());
            }
            for (JsonNode sql : testCase.get("setup")) {
                jdbc.execute(sql.asText());
            }
            Object service = service(plan, testCase, jdbc, calls);
            Object request = record(Class.forName(plan.get("request").asText()), testCase.get("request"));
            Method execute = service.getClass().getMethod("execute", request.getClass());
            Object[] response = new Object[1];
            try {
                transaction.executeWithoutResult(status -> response[0] = invoke(execute, service, request));
                out.set("response", fields(response[0]));
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
            plan.get("dump").fields().forEachRemaining(entry -> {
                ArrayNode rows = tables.putArray(entry.getKey());
                for (Map<String, Object> row : jdbc.queryForList(entry.getValue().asText())) {
                    ObjectNode printed = rows.addObject();
                    row.forEach((column, value) -> printed.put(column, text(value)));
                }
            });
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

    private static Object service(JsonNode plan, JsonNode testCase, JdbcTemplate jdbc, List<ObjectNode> calls)
            throws ReflectiveOperationException {
        List<Object> ports = new ArrayList<>();
        for (JsonNode port : plan.get("ports")) {
            Class<?> type = Class.forName(port.get("interface").asText());
            if (port.hasNonNull("adapter")) {
                ports.add(Class.forName(port.get("adapter").asText()).getConstructor(JdbcTemplate.class).newInstance(jdbc));
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
