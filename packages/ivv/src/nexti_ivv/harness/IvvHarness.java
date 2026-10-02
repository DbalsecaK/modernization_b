import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.sun.net.httpserver.HttpServer;
import java.io.File;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.Statement;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Map;

/**
 * The black-box harness of the independent validation (ADR-0025), run in the sandbox next to the third party's
 * service and its database. For every case of the golden master (already translated to the target's terms by the
 * platform): it resets and loads the target's tables, sets what the stubbed external services answer, calls the
 * endpoint, and prints what happened ("NXI {json}"): the HTTP status and body, the tables and the calls the service
 * made to the external services. The platform translates it back to the legacy's terms and compares.
 */
public class IvvHarness {
    static final ObjectMapper JSON = new ObjectMapper();
    static final Map<String, List<JsonNode>> answers = new HashMap<>();
    static final Map<String, Integer> served = new HashMap<>();
    static final List<ObjectNode> calls = new ArrayList<>();

    public static void main(String[] args) throws Exception {
        JsonNode plan = JSON.readTree(new File(args[0]));
        HttpServer stubs = HttpServer.create(new InetSocketAddress("127.0.0.1", plan.get("stubPort").asInt()), 0);
        stubs.createContext("/", exchange -> {
            String path = exchange.getRequestURI().getPath();
            String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            ObjectNode call = JSON.createObjectNode();
            call.put("path", path);
            call.set("body", body.isBlank() ? JSON.nullNode() : JSON.readTree(body));
            synchronized (calls) {
                calls.add(call);
            }
            List<JsonNode> queue = answers.getOrDefault(path, List.of());
            int index = served.merge(path, 1, Integer::sum) - 1;
            JsonNode answer = queue.isEmpty() ? JSON.createObjectNode() : queue.get(Math.min(index, queue.size() - 1));
            byte[] out = JSON.writeValueAsBytes(answer);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, out.length);
            exchange.getResponseBody().write(out);
            exchange.close();
        });
        stubs.start();

        HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
        String base = plan.get("base").asText();
        JsonNode endpoint = plan.get("endpoint");
        if (!ready(http, base, plan.path("startSeconds").asInt(180))) {
            System.out.println("NXI-NOT-READY");
            stubs.stop(0);
            return;
        }
        System.out.println("NXI-READY");
        try (Connection db = DriverManager.getConnection(plan.get("jdbc").asText(), plan.get("user").asText(), "")) {
            db.setAutoCommit(true);
            for (JsonNode c : plan.get("cases")) {
                try (Statement st = db.createStatement()) {
                    for (JsonNode sql : plan.get("reset")) {
                        st.execute(sql.asText());
                    }
                    for (JsonNode sql : c.get("setup")) {
                        st.execute(sql.asText());
                    }
                }
                answers.clear();
                served.clear();
                calls.clear();
                Iterator<Map.Entry<String, JsonNode>> it = c.path("answers").fields();
                while (it.hasNext()) {
                    Map.Entry<String, JsonNode> e = it.next();
                    List<JsonNode> list = new ArrayList<>();
                    e.getValue().forEach(list::add);
                    answers.put(e.getKey(), list);
                }
                ObjectNode result = JSON.createObjectNode();
                result.put("case", c.get("name").asText());
                try {
                    HttpRequest request = HttpRequest.newBuilder(URI.create(base + endpoint.get("path").asText()))
                            .timeout(Duration.ofSeconds(60))
                            .header("Content-Type", "application/json")
                            .method(endpoint.get("method").asText(),
                                    HttpRequest.BodyPublishers.ofString(JSON.writeValueAsString(c.get("body"))))
                            .build();
                    HttpResponse<String> response = http.send(request, HttpResponse.BodyHandlers.ofString());
                    result.put("status", response.statusCode());
                    String text = response.body();
                    result.set("body", text == null || text.isBlank() ? JSON.nullNode() : parse(text));
                } catch (Exception e) {
                    result.put("error", e.getClass().getSimpleName() + ": " + e.getMessage());
                }
                ObjectNode tables = JSON.createObjectNode();
                Iterator<Map.Entry<String, JsonNode>> dumps = plan.get("dump").fields();
                while (dumps.hasNext()) {
                    Map.Entry<String, JsonNode> d = dumps.next();
                    tables.set(d.getKey(), rows(db, d.getValue().asText()));
                }
                result.set("tables", tables);
                ArrayNode made = JSON.createArrayNode();
                synchronized (calls) {
                    calls.forEach(made::add);
                }
                result.set("calls", made);
                System.out.println("NXI " + JSON.writeValueAsString(result));
            }
        }
        stubs.stop(0);
    }

    static JsonNode parse(String text) {
        try {
            return JSON.readTree(text);
        } catch (Exception e) {
            return JSON.getNodeFactory().textNode(text);
        }
    }

    static boolean ready(HttpClient http, String base, int seconds) throws InterruptedException {
        long until = System.currentTimeMillis() + seconds * 1000L;
        while (System.currentTimeMillis() < until) {
            try {
                http.send(HttpRequest.newBuilder(URI.create(base + "/")).timeout(Duration.ofSeconds(2)).GET().build(),
                        HttpResponse.BodyHandlers.discarding());
                return true;
            } catch (Exception e) {
                Thread.sleep(500);
            }
        }
        return false;
    }

    static ArrayNode rows(Connection db, String sql) throws Exception {
        ArrayNode out = JSON.createArrayNode();
        try (Statement st = db.createStatement(); ResultSet rs = st.executeQuery(sql)) {
            ResultSetMetaData meta = rs.getMetaData();
            while (rs.next()) {
                ObjectNode row = JSON.createObjectNode();
                for (int i = 1; i <= meta.getColumnCount(); i++) {
                    String value = rs.getString(i);
                    if (value == null) {
                        row.putNull(meta.getColumnName(i));
                    } else {
                        row.put(meta.getColumnName(i), value);
                    }
                }
                out.add(row);
            }
        }
        return out;
    }
}
