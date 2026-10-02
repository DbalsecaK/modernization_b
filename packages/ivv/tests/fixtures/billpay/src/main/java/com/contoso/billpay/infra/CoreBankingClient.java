package com.contoso.billpay.infra;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/** The debit of the core banking system, over HTTP. */
@Component
public class CoreBankingClient {
    public record Debit(int code, Long sequence) {
    }

    private final HttpClient http = HttpClient.newHttpClient();
    private final ObjectMapper json = new ObjectMapper();
    private final String debitUrl;

    public CoreBankingClient(@Value("${core.debit-url}") String debitUrl) {
        this.debitUrl = debitUrl;
    }

    public Debit debit(String account, String type, BigDecimal amount, String reference) {
        try {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("account", account);
            body.put("type", type);
            body.put("amount", amount);
            body.put("reference", reference);
            HttpRequest request = HttpRequest.newBuilder(URI.create(debitUrl))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(json.writeValueAsString(body)))
                    .build();
            JsonNode answer = json.readTree(http.send(request, HttpResponse.BodyHandlers.ofString()).body());
            JsonNode sequence = answer.get("sequence");
            return new Debit(answer.path("code").asInt(-1), sequence == null || sequence.isNull() ? null : sequence.asLong());
        } catch (Exception e) {
            return new Debit(-1, null);
        }
    }
}
