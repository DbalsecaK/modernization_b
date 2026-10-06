package nexti.equivalence;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.mongodb.MongoCommandException;
import com.mongodb.MongoException;
import com.mongodb.client.MongoClient;
import com.mongodb.client.MongoClients;
import com.mongodb.client.MongoCollection;
import com.mongodb.client.MongoDatabase;
import com.mongodb.client.model.CreateCollectionOptions;
import com.mongodb.client.model.IndexOptions;
import com.mongodb.client.model.ValidationAction;
import com.mongodb.client.model.ValidationLevel;
import com.mongodb.client.model.ValidationOptions;
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
import java.util.function.Supplier;
import org.bson.Document;
import org.bson.json.JsonMode;
import org.bson.json.JsonWriterSettings;

/**
 * Runs the golden master cases on the generated service with MongoDB (NexTI verification, spec 11.3 check 3,
 * ADR-0029). Written by the platform, never by a model: it initiates the single-node replica set of the sandbox's
 * mongod (transactions need one), creates the collections with their validators and unique keys, and for each case
 * inserts the legacy rows as documents, runs the use case inside the project's MongoTransaction with the real MongoDB
 * adapters and fakes for the external programs (a rejection undoes its writes and its external calls, as in the
 * legacy) and prints every collection as MongoDB Extended JSON. One JSON line per case, prefixed with "NXE ".
 */
public final class EquivalenceHarness {

    private static final ObjectMapper JSON = new ObjectMapper();
    private static final JsonWriterSettings EXTENDED = JsonWriterSettings.builder().outputMode(JsonMode.EXTENDED).build();
    private static final int ALREADY_INITIALIZED = 23;

    private EquivalenceHarness() {
    }

    public static void main(String[] args) throws Exception {
        JsonNode plan = JSON.readTree(new File(args[0]));
        JsonNode cases = JSON.readTree(new File(args[1]));
        if (!primary(plan)) {
            System.out.println("===HARNESS-FAILED===");
            System.out.println("MongoDB did not become the primary of its single-node replica set");
            System.exit(5);
        }
        try (MongoClient client = MongoClients.create(plan.get("uri").asText())) {
            MongoDatabase database = client.getDatabase(plan.get("database").asText());
            for (JsonNode collection : plan.get("collections")) {
                String name = collection.get("name").asText();
                database.createCollection(name, new CreateCollectionOptions().validationOptions(new ValidationOptions()
                        .validator(Document.parse(collection.get("validator").toString()))
                        .validationLevel(ValidationLevel.STRICT).validationAction(ValidationAction.ERROR)));
                if (!collection.get("key").isEmpty()) {
                    database.getCollection(name).createIndex(sort(collection), new IndexOptions().unique(true)
                            .name(name + "_key"));
                }
            }
            Method transaction = Class.forName(plan.get("transaction").asText())
                    .getMethod("inTransaction", MongoClient.class, Supplier.class);
            for (JsonNode testCase : cases) {
                System.out.println("NXE " + JSON.writeValueAsString(run(plan, testCase, client, database, transaction)));
            }
        }
    }

    /** Initiates the replica set (once) and waits until its only member is the writable primary. */
    private static boolean primary(JsonNode plan) throws InterruptedException {
        long deadline = System.currentTimeMillis() + 90_000;
        boolean initiated = false;
        try (MongoClient client = MongoClients.create(plan.get("init_uri").asText())) {
            MongoDatabase admin = client.getDatabase("admin");
            while (System.currentTimeMillis() < deadline) {
                try {
                    if (admin.runCommand(new Document("hello", 1)).getBoolean("isWritablePrimary", false)) {
                        return true;
                    }
                    if (!initiated) {
                        Document member = new Document("_id", 0).append("host", plan.get("host").asText());
                        try {
                            admin.runCommand(new Document("replSetInitiate", new Document("_id",
                                    plan.get("replica_set").asText()).append("members", List.of(member))));
                        } catch (MongoCommandException e) {
                            if (e.getErrorCode() != ALREADY_INITIALIZED) {
                                throw e;
                            }
                        }
                        initiated = true;
                    }
                } catch (MongoException e) {
                    // not listening yet, or the election is still running
                }
                Thread.sleep(250);
            }
        }
        return false;
    }

    private static Document sort(JsonNode collection) {
        Document keys = new Document();
        collection.get("key").forEach(key -> keys.append(key.asText(), 1));
        return keys;
    }

    private static ObjectNode run(JsonNode plan, JsonNode testCase, MongoClient client, MongoDatabase database,
            Method transaction) {
        ObjectNode out = JSON.createObjectNode();
        out.put("name", testCase.get("name").asText());
        List<ObjectNode> calls = new ArrayList<>();
        try {
            for (JsonNode collection : plan.get("collections")) {
                database.getCollection(collection.get("name").asText()).deleteMany(new Document());
            }
            for (JsonNode item : testCase.get("setup")) {
                database.getCollection(item.get("collection").asText())
                        .insertOne(Document.parse(item.get("document").toString()));
            }
            Object service = service(plan, testCase, database, calls);
            Object request = record(Class.forName(plan.get("request").asText()), testCase.get("request"));
            Method execute = service.getClass().getMethod("execute", request.getClass());
            try {
                Supplier<Object> work = () -> invoke(execute, service, request);
                out.set("response", fields(invoke(transaction, null, client, work)));
            } catch (RuntimeException e) {
                // The calls stay: they are what the service did before it rejected, as the legacy's calls before
                // its `return code` are (ADR-0044); the rollback undoes the tables, which are dumped after it.
                if (!e.getClass().getSimpleName().equals("BusinessError")) {
                    throw e;
                }
                ObjectNode error = out.putObject("error");
                error.put("code", String.valueOf(call(e, "code")));
                error.put("legacy_code", String.valueOf(call(e, "legacyCode")));
                error.put("message", e.getMessage());
            }
            ObjectNode documents = out.putObject("documents");
            for (JsonNode collection : plan.get("collections")) {
                String name = collection.get("name").asText();
                ArrayNode printed = documents.putArray(name);
                MongoCollection<Document> found = database.getCollection(name);
                for (Document document : found.find().sort(sort(collection))) {
                    document.remove("_id");
                    printed.add(JSON.readTree(document.toJson(EXTENDED)));
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

    private static Object invoke(Method method, Object target, Object... arguments) {
        try {
            return method.invoke(target, arguments);
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

    private static Object service(JsonNode plan, JsonNode testCase, MongoDatabase database, List<ObjectNode> calls)
            throws ReflectiveOperationException {
        List<Object> ports = new ArrayList<>();
        for (JsonNode port : plan.get("ports")) {
            Class<?> type = Class.forName(port.get("interface").asText());
            if (port.hasNonNull("adapter")) {
                ports.add(Class.forName(port.get("adapter").asText()).getConstructor(MongoDatabase.class)
                        .newInstance(database));
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

    private static ObjectNode fields(Object value) {
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
