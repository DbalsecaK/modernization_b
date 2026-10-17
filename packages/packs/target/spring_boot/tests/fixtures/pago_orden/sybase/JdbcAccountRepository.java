package com.bancoficticio.payments.adapters.out.jdbc;

import com.bancoficticio.payments.domain.model.Account;
import com.bancoficticio.payments.domain.port.AccountRepository;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * Accounts where the bank keeps them: db_cuentas..ct_cuenta in Sybase ASE (ADR-0055, same database). Reference
 * adapter of the fictitious application, written by hand.
 */
@Repository
public class JdbcAccountRepository implements AccountRepository {

    private final JdbcTemplate jdbc;

    public JdbcAccountRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<Account> find(String number, String type) {
        return jdbc.query(
                "select cta_numero, cta_tipo, cta_saldo from db_cuentas..ct_cuenta where cta_numero = ? and cta_tipo = ?",
                (rs, n) -> new Account(rs.getString("cta_numero").trim(), rs.getString("cta_tipo").trim(),
                        rs.getBigDecimal("cta_saldo")),
                number, type).stream().findFirst();
    }
}
