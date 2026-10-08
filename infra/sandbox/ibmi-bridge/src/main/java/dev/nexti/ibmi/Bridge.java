package dev.nexti.ibmi;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.ibm.as400.access.AS400;
import com.ibm.as400.access.AS400Bin2;
import com.ibm.as400.access.AS400Bin4;
import com.ibm.as400.access.AS400Bin8;
import com.ibm.as400.access.AS400DataType;
import com.ibm.as400.access.AS400JDBCDataSource;
import com.ibm.as400.access.AS400Message;
import com.ibm.as400.access.AS400PackedDecimal;
import com.ibm.as400.access.AS400SecurityException;
import com.ibm.as400.access.AS400Text;
import com.ibm.as400.access.AS400UnsignedBin2;
import com.ibm.as400.access.AS400UnsignedBin4;
import com.ibm.as400.access.AS400ZonedDecimal;
import com.ibm.as400.access.CommandCall;
import com.ibm.as400.access.ProgramCall;
import com.ibm.as400.access.ProgramParameter;
import com.ibm.as400.access.QSYSObjectPathName;
import com.ibm.as400.access.SecureAS400;
import java.io.IOException;
import java.io.PrintStream;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.Date;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.sql.Statement;
import java.sql.Timestamp;
import java.sql.Types;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.regex.Pattern;

/**
 * Runs the golden master cases of one RPG program on a customer's IBM i (ADR-0053). The request comes on stdin as
 * JSON (credentials included: never on the command line or in the environment); the answer goes to stdout as JSON.
 * Per case: every table of the case is emptied in the test library and loaded with the case rows, the program is
 * called with its typed parameters (the test library first in the library list), and the parameters and the tables
 * are read back. Nothing outside the test library is written.
 */
public final class Bridge {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final Pattern NAME = Pattern.compile("^[A-Z#$@][A-Z0-9#$@_.]{0,9}$");
    private static final DateTimeFormatter STAMP = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss.SSSSSS");

    private Bridge() {}

    public static void main(String[] args) throws IOException {
        JsonNode request = JSON.readTree(System.in);
        PrintStream out = new PrintStream(System.out, true, StandardCharsets.UTF_8);
        ObjectNode answer;
        try {
            answer = run(request);
        } catch (Failure failure) {
            answer = JSON.createObjectNode();
            ObjectNode error = answer.putObject("error");
            error.put("kind", failure.kind);
            error.put("message", failure.getMessage());
        }
        out.println(JSON.writeValueAsString(answer));
    }

    static final class Failure extends Exception {
        final String kind; // connect, signon, library, request

        Failure(String kind, String message) {
            super(message);
            this.kind = kind;
        }
    }

    static ObjectNode run(JsonNode request) throws Failure {
        JsonNode connection = request.path("connection");
        String library = name(request.path("library").asText(), "library");
        String programs = name(request.path("programs").asText(library), "programs");
        String program = name(request.path("program").asText(), "program");
        int ccsid = connection.path("ccsid").asInt(284);
        String host = connection.path("host").asText();
        char[] password = connection.path("password").asText().toCharArray();
        AS400 system = connection.path("tls").asBoolean(false)
                ? new SecureAS400(host, connection.path("user").asText(), password)
                : new AS400(host, connection.path("user").asText(), password);
        java.util.Arrays.fill(password, ' ');
        try {
            system.setGuiAvailable(false);
            if (!system.validateSignon()) {
                throw new Failure("signon", "the IBM i refused the sign-on");
            }
            ObjectNode answer = JSON.createObjectNode();
            ObjectNode info = answer.putObject("system");
            info.put("version", String.format("V%dR%dM%d", system.getVersion(), system.getRelease(),
                    system.getModification()));
            info.put("ccsid", ccsid);
            libraryList(system, library, programs);
            AS400JDBCDataSource source = new AS400JDBCDataSource(system);
            source.setNaming("system");
            source.setLibraries(library);
            source.setTransactionIsolation("none"); // test libraries are rarely journaled
            try (Connection db = source.getConnection()) {
                ArrayNode cases = answer.putArray("cases");
                for (JsonNode item : request.path("cases")) {
                    cases.add(runCase(system, db, library, programs, program, ccsid, request, item));
                }
            }
            return answer;
        } catch (AS400SecurityException e) {
            throw new Failure("signon", "sign-on refused: " + e.getMessage());
        } catch (IOException e) {
            throw new Failure("connect", "the IBM i did not answer: " + e.getMessage());
        } catch (SQLException e) {
            throw new Failure("connect", "the database server of the IBM i did not answer: " + e.getMessage());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new Failure("connect", "interrupted");
        } catch (Exception e) {
            if (e instanceof Failure failure) {
                throw failure;
            }
            throw new Failure("connect", e.getClass().getSimpleName() + ": " + e.getMessage());
        } finally {
            system.disconnectAllServices();
        }
    }

    static String name(String value, String what) throws Failure {
        String upper = value.toUpperCase();
        if (!NAME.matcher(upper).matches()) {
            throw new Failure("request", "not an IBM i name for " + what + ": " + value);
        }
        return upper;
    }

    static void libraryList(AS400 system, String library, String programs) throws Exception {
        CommandCall command = new CommandCall(system);
        for (String lib : programs.equals(library) ? List.of(library) : List.of(programs, library)) {
            if (!command.run("ADDLIBLE LIB(" + lib + ") POSITION(*FIRST)")) {
                String messages = messages(command.getMessageList());
                if (!messages.contains("CPF2103")) { // already in the library list
                    throw new Failure("library", "library " + lib + " cannot be used: " + messages);
                }
            }
        }
    }

    static ObjectNode runCase(AS400 system, Connection db, String library, String programs, String program,
                              int ccsid, JsonNode request, JsonNode item) throws Exception {
        ObjectNode result = JSON.createObjectNode();
        result.put("name", item.path("name").asText());
        List<String> tables = new ArrayList<>();
        for (JsonNode table : request.path("tables")) {
            tables.add(name(table.path("name").asText(), "table"));
        }
        Iterator<String> setupTables = item.path("setup").fieldNames();
        while (setupTables.hasNext()) {
            String table = name(setupTables.next(), "table");
            if (!tables.contains(table)) {
                tables.add(table);
            }
        }
        for (String table : tables) {
            try (Statement clear = db.createStatement()) {
                clear.executeUpdate("DELETE FROM " + library + "/" + table);
            }
            for (JsonNode row : item.path("setup").path(table)) {
                insert(db, library, table, row);
            }
        }
        JsonNode parameters = request.path("parameters");
        List<AS400DataType> types = new ArrayList<>();
        ProgramParameter[] list = new ProgramParameter[parameters.size()];
        for (int i = 0; i < parameters.size(); i++) {
            JsonNode p = parameters.get(i);
            AS400DataType type = type(p, ccsid, system);
            types.add(type);
            JsonNode input = item.path("inputs").path(p.path("name").asText());
            list[i] = new ProgramParameter(type.toBytes(value(p, input)), type.getByteLength());
        }
        ProgramCall call = new ProgramCall(system);
        call.setProgram(new QSYSObjectPathName(programs, program, "PGM").getPath(), list);
        if (!call.run()) {
            result.put("error", messages(call.getMessageList()));
        } else {
            result.putNull("error");
        }
        ObjectNode outputs = result.putObject("outputs");
        for (int i = 0; i < parameters.size(); i++) {
            byte[] data = list[i].getOutputData();
            if (data != null) {
                outputs.put(parameters.get(i).path("name").asText(), text(types.get(i).toObject(data)));
            }
        }
        ObjectNode after = result.putObject("tables");
        for (String table : tables) {
            after.set(table, read(db, library, table, request));
        }
        return result;
    }

    static AS400DataType type(JsonNode p, int ccsid, AS400 system) throws Failure {
        int length = p.path("length").asInt(1);
        int decimals = p.path("decimals").asInt(0);
        return switch (p.path("type").asText()) {
            case "packed" -> new AS400PackedDecimal(length, decimals);
            case "zoned" -> new AS400ZonedDecimal(length, decimals);
            case "char" -> new AS400Text(length, ccsid, system);
            case "int" -> length <= 5 ? new AS400Bin2() : length <= 10 ? new AS400Bin4() : new AS400Bin8();
            case "uns" -> length <= 5 ? new AS400UnsignedBin2() : new AS400UnsignedBin4();
            default -> throw new Failure("request", "a parameter type the bridge cannot pass: " + p);
        };
    }

    static Object value(JsonNode p, JsonNode input) {
        String type = p.path("type").asText();
        boolean missing = input.isMissingNode() || input.isNull();
        if (type.equals("char")) {
            return missing ? "" : input.asText();
        }
        BigDecimal number = missing || input.asText().isBlank() ? BigDecimal.ZERO : new BigDecimal(input.asText().trim());
        return switch (type) {
            case "packed", "zoned" -> number.setScale(p.path("decimals").asInt(0));
            case "int" -> p.path("length").asInt(10) <= 5 ? (Object) number.shortValueExact()
                    : p.path("length").asInt(10) <= 10 ? (Object) number.intValueExact() : number.longValueExact();
            default -> p.path("length").asInt(10) <= 5 ? (Object) number.intValueExact() : number.longValueExact();
        };
    }

    static void insert(Connection db, String library, String table, JsonNode row) throws SQLException {
        List<String> columns = new ArrayList<>();
        row.fieldNames().forEachRemaining(columns::add);
        if (columns.isEmpty()) {
            return;
        }
        StringBuilder sql = new StringBuilder("INSERT INTO ").append(library).append('/').append(table).append(" (");
        StringBuilder marks = new StringBuilder();
        for (int i = 0; i < columns.size(); i++) {
            String column = columns.get(i).toUpperCase();
            if (!NAME.matcher(column).matches()) {
                throw new SQLException("not a column name: " + column);
            }
            sql.append(i == 0 ? "" : ", ").append(column);
            marks.append(i == 0 ? "?" : ", ?");
        }
        sql.append(") VALUES (").append(marks).append(')');
        try (PreparedStatement insert = db.prepareStatement(sql.toString())) {
            for (int i = 0; i < columns.size(); i++) {
                JsonNode value = row.get(columns.get(i));
                if (value == null || value.isNull()) {
                    insert.setNull(i + 1, Types.VARCHAR);
                } else {
                    insert.setString(i + 1, value.asText());
                }
            }
            insert.executeUpdate();
        }
    }

    static ArrayNode read(Connection db, String library, String table, JsonNode request) throws Exception {
        List<String> key = new ArrayList<>();
        for (JsonNode t : request.path("tables")) {
            if (t.path("name").asText().equalsIgnoreCase(table)) {
                for (JsonNode k : t.path("key")) {
                    key.add(name(k.asText(), "key column"));
                }
            }
        }
        String order = key.isEmpty() ? "" : " ORDER BY " + String.join(", ", key);
        ArrayNode rows = JSON.createArrayNode();
        try (Statement select = db.createStatement();
             ResultSet found = select.executeQuery("SELECT * FROM " + library + "/" + table + order)) {
            ResultSetMetaData meta = found.getMetaData();
            while (found.next()) {
                ObjectNode row = rows.addObject();
                for (int c = 1; c <= meta.getColumnCount(); c++) {
                    Object value = found.getObject(c);
                    if (value == null) {
                        row.putNull(meta.getColumnName(c));
                    } else {
                        row.put(meta.getColumnName(c), text(value));
                    }
                }
            }
        }
        return rows;
    }

    /** The canonical text of a value: decimals with their scale, dates ISO, fixed text without trailing blanks. */
    static String text(Object value) {
        if (value instanceof BigDecimal decimal) {
            return decimal.toPlainString();
        }
        if (value instanceof Timestamp stamp) {
            return stamp.toLocalDateTime().format(STAMP);
        }
        if (value instanceof Date date) {
            return date.toLocalDate().toString();
        }
        if (value instanceof String string) {
            return string.stripTrailing();
        }
        return String.valueOf(value);
    }

    static String messages(AS400Message[] list) {
        StringBuilder text = new StringBuilder();
        for (AS400Message message : list == null ? new AS400Message[0] : list) {
            text.append(text.isEmpty() ? "" : "; ").append(message.getID()).append(": ").append(message.getText());
        }
        return text.toString();
    }
}
