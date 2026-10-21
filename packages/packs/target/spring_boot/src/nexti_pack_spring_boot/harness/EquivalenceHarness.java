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
 * writes and its external calls, as in the legacy: those calls are reported as "undone", ADR-0055). One JSON line per
 * case, prefixed with "NXE ".
 */
public final class EquivalenceHarness {

    private static final ObjectMapper JSON = new ObjectMapper();

    private EquivalenceHarness() {
    }

    public static void main(String[] args) throws Exception {
        JsonNode plan = JSON.readTree(new File(args[0]));
        if (plan.hasNonNull("driver")) { // the driver of the legacy's engine, generated with the project
            Class.forName(plan.get("driver").asText());
        }
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
        if (plan.hasNonNull("concurrency")) {
            System.out.println("NXE " + JSON.writeValueAsString(concurrency(plan, cases, jdbc, transaction, password)));
        }
        dataSource.destroy();
    }

    /**
     * ADR-0056 (phase D, point 12): the case the plan names runs twice at the same time, each run on its own
     * connection, on the same rows; the final state must be the one of running it twice one after the other
     * (serializable), and neither run may fail with a lock or a deadlock the sequential runs do not have.
     */
    static ObjectNode concurrency(JsonNode plan, JsonNode cases, JdbcTemplate jdbc, TransactionTemplate transaction,
            String password) throws Exception {
        ObjectNode out = JSON.createObjectNode();
        out.put("name", "__concurrency__");
        String wanted = plan.get("concurrency").asText();
        JsonNode testCase = null;
        for (JsonNode candidate : cases) {
            if (candidate.get("name").asText().equals(wanted)) {
                testCase = candidate;
            }
        }
        if (testCase == null) {
            out.put("failure", "the plan names a case that is not in the suite: " + wanted);
            return out;
        }
        out.put("case", wanted);
        // The sequential twin: the case twice, one after the other, on one connection.
        run(plan, testCase, jdbc, transaction);
        ObjectNode sequential = runAgain(plan, testCase, jdbc, transaction);
        // The concurrent run: reset once, then two threads on two connections.
        for (JsonNode sql : plan.get("reset")) {
            jdbc.execute(sql.asText());
        }
        for (JsonNode sql : testCase.get("setup")) {
            jdbc.execute(sql.asText());
        }
        org.springframework.jdbc.datasource.DriverManagerDataSource pool =
                new org.springframework.jdbc.datasource.DriverManagerDataSource(
                        plan.get("jdbc_url").asText(), plan.get("user").asText(), password);
        List<String> failures = java.util.Collections.synchronizedList(new ArrayList<>());
        java.util.concurrent.CountDownLatch ready = new java.util.concurrent.CountDownLatch(2);
        java.util.concurrent.CountDownLatch go = new java.util.concurrent.CountDownLatch(1);
        final JsonNode chosen = testCase;
        Runnable one = () -> {
            try {
                JdbcTemplate own = new JdbcTemplate(pool);
                TransactionTemplate ownTransaction = new TransactionTemplate(new DataSourceTransactionManager(pool));
                List<ObjectNode> calls = new ArrayList<>();
                Object service = service(plan, chosen, own, calls);
                Object request = record(Class.forName(plan.get("request").asText()), chosen.get("request"));
                Method execute = service.getClass().getMethod("execute", request.getClass());
                ready.countDown();
                go.await();
                try {
                    if (plan.path("service_transaction").asBoolean(false)) {
                        try {
                            invoke(execute, service, request);
                            unitOfWork(service, "commitIfActive");
                        } catch (RuntimeException e) {
                            unitOfWork(service, "rollbackIfActive");
                            throw e;
                        }
                    } else {
                        ownTransaction.executeWithoutResult(status -> invoke(execute, service, request));
                    }
                } catch (RuntimeException e) {
                    if (!e.getClass().getSimpleName().equals("BusinessError")) {
                        failures.add(e.getClass().getName() + ": " + e.getMessage());
                    }
                }
            } catch (Exception e) {
                failures.add(e.getClass().getName() + ": " + e.getMessage());
            }
        };
        Thread a = new Thread(one, "nexti-concurrent-a");
        Thread b = new Thread(one, "nexti-concurrent-b");
        a.start();
        b.start();
        ready.await();
        go.countDown();
        a.join(120000);
        b.join(120000);
        if (a.isAlive() || b.isAlive()) {
            failures.add("a run did not finish in 120 s (a lock the sequential runs do not have)");
        }
        ObjectNode concurrent = JSON.createObjectNode();
        ObjectNode tables = concurrent.putObject("tables");
        plan.get("dump").fields().forEachRemaining(entry -> {
            ArrayNode rows = tables.putArray(entry.getKey());
            for (Map<String, Object> row : jdbc.queryForList(entry.getValue().asText())) {
                ObjectNode printed = rows.addObject();
                row.forEach((column, value) -> printed.put(column, text(value)));
            }
        });
        ArrayNode failed = out.putArray("failures");
        failures.forEach(failed::add);
        out.set("sequential", sequential.get("tables"));
        out.set("concurrent", concurrent.get("tables"));
        out.put("serializable", failures.isEmpty() && sequential.get("tables").equals(concurrent.get("tables")));
        return out;
    }

    /** The case once more on the rows the previous run left (no reset): the second of two sequential runs. */
    private static ObjectNode runAgain(JsonNode plan, JsonNode testCase, JdbcTemplate jdbc,
            TransactionTemplate transaction) {
        ObjectNode copy = testCase.deepCopy();
        copy.putArray("setup");
        ObjectNode bare = plan.deepCopy();
        bare.putArray("reset");
        return run(bare, copy, jdbc, transaction);
    }

    private static ObjectNode run(JsonNode plan, JsonNode testCase, JdbcTemplate jdbc, TransactionTemplate transaction) {
        ObjectNode out = JSON.createObjectNode();
        out.put("name", testCase.get("name").asText());
        List<ObjectNode> calls = new ArrayList<>();
        List<ObjectNode> undone = new ArrayList<>();
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
                if (plan.path("service_transaction").asBoolean(false)) {
                    // Phase F: the service begins, commits and rolls back through its UnitOfWork port, as the
                    // legacy does; the harness only closes what a failure left open.
                    try {
                        response[0] = invoke(execute, service, request);
                        unitOfWork(service, "commitIfActive");
                    } catch (RuntimeException e) {
                        unitOfWork(service, "rollbackIfActive");
                        throw e;
                    }
                } else {
                    transaction.executeWithoutResult(status -> response[0] = invoke(execute, service, request));
                }
                out.set("response", fields(response[0]));
            } catch (RuntimeException e) {
                // The rollback undoes the tables (dumped after it) and the effects of the calls made inside the
                // transaction: they are reported apart, as `undone`, like the legacy's calls its rollback erased
                // (ADR-0055).
                if (!e.getClass().getSimpleName().equals("BusinessError")) {
                    throw e;
                }
                undone.addAll(calls);
                calls.clear();
                ObjectNode error = out.putObject("error");
                error.put("code", String.valueOf(call(e, "code")));
                error.put("legacy_code", String.valueOf(call(e, "legacyCode")));
                error.put("message", e.getMessage());
            }
            // The messages the called programs raised through the generated adapters (ADR-0056): what the
            // legacy's caller saw from them, the target's caller sees too.
            ArrayNode raised = out.putArray("messages");
            messages(service).forEach(raised::add);
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
            ArrayNode erased = out.putArray("undone");
            undone.forEach(erased::add);
            if (plan.hasNonNull("calls")) { // the legacy's engine logged the calls that survived (ADR-0055)
                ArrayNode logged = out.putArray("legacy_calls");
                for (Map<String, Object> row : jdbc.queryForList(plan.get("calls").asText())) {
                    ObjectNode call = logged.addObject();
                    call.put("program", text(row.get("program")));
                    call.put("args", text(row.get("args")));
                }
            }
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

    /** The messages the adapters of the called programs kept for this thread (their `messages()`), in order. */
    private static List<String> messages(Object service) {
        List<String> found = new ArrayList<>();
        for (java.lang.reflect.Field field : service.getClass().getDeclaredFields()) {
            try {
                field.setAccessible(true);
                Object port = field.get(service);
                if (port != null) {
                    Object kept = port.getClass().getMethod("messages").invoke(port);
                    if (kept instanceof List<?> list) {
                        list.forEach(item -> found.add(String.valueOf(item)));
                    }
                }
            } catch (ReflectiveOperationException | RuntimeException e) {
                // not an adapter that keeps messages
            }
        }
        return found;
    }

    /** The UnitOfWork adapter among the service's ports (a field of the service), told to close what is open. */
    private static void unitOfWork(Object service, String method) {
        for (java.lang.reflect.Field field : service.getClass().getDeclaredFields()) {
            try {
                field.setAccessible(true);
                Object port = field.get(service);
                if (port != null && port.getClass().getSimpleName().equals("JdbcUnitOfWork")) {
                    port.getClass().getMethod(method).invoke(port);
                    return;
                }
            } catch (ReflectiveOperationException | RuntimeException e) {
                // not this field
            }
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
                ports.add(fake(type, name, testCase.path("stubs").path(name), calls, jdbc));
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

    private static Object fake(Class<?> type, String name, JsonNode answers, List<ObjectNode> calls,
            JdbcTemplate jdbc) {
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
            // A transactional substitute (ADR-0055): the rows the program leaves, written on the same connection,
            // inside the use case's transaction, so a rejection undoes them as the legacy's rollback does.
            for (JsonNode effect : answer.path("effects")) {
                int changed = effect.hasNonNull("update") ? jdbc.update(effect.get("update").asText()) : 0;
                if (changed == 0) {
                    jdbc.update(effect.get("insert").asText());
                }
            }
            // A method that carries the status (a field mapped to `return`) receives it as data, as the legacy
            // does; only a method that cannot carry it fails on a non-zero status (ADR-0055, phase F).
            if (answer.path("returns").asInt(0) != 0 && !answer.path("carries_status").asBoolean(false)) {
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
