package com.contoso.billpay.support;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * A JdbcTemplate for unit tests: each query answers what the test scripted for a fragment of its SQL, and every
 * statement is recorded with its arguments. No database is needed.
 */
public class ScriptedJdbc extends JdbcTemplate {
    private final Map<String, List<?>> answers = new LinkedHashMap<>();
    private final Map<String, Integer> updates = new LinkedHashMap<>();
    public final List<String> executed = new ArrayList<>();
    public final List<Object[]> arguments = new ArrayList<>();

    /** The rows (or single values) a query whose SQL contains `fragment` returns. */
    public ScriptedJdbc answer(String fragment, List<?> rows) {
        answers.put(fragment, rows);
        return this;
    }

    /** The count an update whose SQL contains `fragment` returns (1 when not scripted). */
    public ScriptedJdbc updates(String fragment, int count) {
        updates.put(fragment, count);
        return this;
    }

    private List<?> rows(String sql, Object... args) {
        executed.add(sql);
        arguments.add(args);
        return answers.entrySet().stream()
                .filter(e -> sql.contains(e.getKey()))
                .map(Map.Entry::getValue)
                .findFirst()
                .orElse(List.of());
    }

    @Override
    @SuppressWarnings("unchecked")
    public <T> List<T> queryForList(String sql, Class<T> elementType, Object... args) {
        return (List<T>) rows(sql, args);
    }

    @Override
    @SuppressWarnings("unchecked")
    public List<Map<String, Object>> queryForList(String sql, Object... args) {
        return (List<Map<String, Object>>) rows(sql, args);
    }

    @Override
    @SuppressWarnings("unchecked")
    public <T> T queryForObject(String sql, Class<T> requiredType, Object... args) {
        List<?> found = rows(sql, args);
        return found.isEmpty() ? null : (T) found.get(0);
    }

    @Override
    public int update(String sql, Object... args) {
        executed.add(sql);
        arguments.add(args);
        return updates.entrySet().stream()
                .filter(e -> sql.contains(e.getKey()))
                .map(Map.Entry::getValue)
                .findFirst()
                .orElse(1);
    }
}
