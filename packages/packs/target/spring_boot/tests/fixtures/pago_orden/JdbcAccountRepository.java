package com.bancoficticio.payments.adapters.out.jdbc;

import com.bancoficticio.payments.domain.model.Account;
import com.bancoficticio.payments.domain.port.AccountRepository;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** Accounts in PostgreSQL. Reference adapter of the fictitious application, written by hand. */
@Repository
public class JdbcAccountRepository implements AccountRepository {

    private final JdbcTemplate jdbc;

    public JdbcAccountRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<Account> find(String number, String type) {
        return jdbc.query(
                "SELECT number, type, balance FROM account WHERE number = ? AND type = ?",
                (rs, n) -> new Account(rs.getString("number"), rs.getString("type"), rs.getBigDecimal("balance")),
                number, type).stream().findFirst();
    }
}
