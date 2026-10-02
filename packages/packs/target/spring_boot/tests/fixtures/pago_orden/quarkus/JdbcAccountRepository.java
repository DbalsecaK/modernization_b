package com.bancoficticio.payments.adapters.out.jdbc;

import com.bancoficticio.payments.domain.model.Account;
import com.bancoficticio.payments.domain.port.AccountRepository;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.Optional;
import javax.sql.DataSource;

/** Accounts in PostgreSQL over the Agroal datasource. Reference adapter of the fictitious application, by hand. */
@ApplicationScoped
public class JdbcAccountRepository implements AccountRepository {

    private final DataSource dataSource;

    @Inject
    public JdbcAccountRepository(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    @Override
    public Optional<Account> find(String number, String type) {
        try (Connection connection = dataSource.getConnection();
                PreparedStatement statement = connection.prepareStatement(
                        "SELECT number, type, balance FROM account WHERE number = ? AND type = ?")) {
            statement.setString(1, number);
            statement.setString(2, type);
            try (ResultSet rs = statement.executeQuery()) {
                return rs.next()
                        ? Optional.of(new Account(rs.getString("number"), rs.getString("type"), rs.getBigDecimal("balance")))
                        : Optional.empty();
            }
        } catch (SQLException e) {
            throw new IllegalStateException("account lookup failed", e);
        }
    }
}
