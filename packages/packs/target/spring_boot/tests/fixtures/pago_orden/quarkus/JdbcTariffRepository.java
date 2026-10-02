package com.bancoficticio.payments.adapters.out.jdbc;

import com.bancoficticio.payments.domain.model.Tariff;
import com.bancoficticio.payments.domain.port.TariffRepository;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Types;
import java.util.Optional;
import javax.sql.DataSource;

/** Company and general tariffs in PostgreSQL over the Agroal datasource. Reference adapter, written by hand. */
@ApplicationScoped
public class JdbcTariffRepository implements TariffRepository {

    private final DataSource dataSource;

    @Inject
    public JdbcTariffRepository(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    @Override
    public Optional<Tariff> companyTariff(Integer company, String service) {
        try (Connection connection = dataSource.getConnection();
                PreparedStatement statement = connection.prepareStatement(
                        "SELECT company, service, amount, separate FROM company_tariff WHERE company = ? AND service = ?")) {
            statement.setObject(1, company, Types.INTEGER);
            statement.setString(2, service);
            try (ResultSet rs = statement.executeQuery()) {
                return rs.next()
                        ? Optional.of(new Tariff(rs.getInt("company"), rs.getString("service"), rs.getBigDecimal("amount"),
                                rs.getBoolean("separate")))
                        : Optional.empty();
            }
        } catch (SQLException e) {
            throw new IllegalStateException("company tariff lookup failed", e);
        }
    }

    @Override
    public Optional<Tariff> serviceTariff(String service) {
        try (Connection connection = dataSource.getConnection();
                PreparedStatement statement = connection.prepareStatement(
                        "SELECT service, amount FROM service_tariff WHERE service = ?")) {
            statement.setString(1, service);
            try (ResultSet rs = statement.executeQuery()) {
                return rs.next()
                        ? Optional.of(new Tariff(null, rs.getString("service"), rs.getBigDecimal("amount"), false))
                        : Optional.empty();
            }
        } catch (SQLException e) {
            throw new IllegalStateException("service tariff lookup failed", e);
        }
    }
}
