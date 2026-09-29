package com.bancoficticio.payments.adapters.out.jdbc;

import com.bancoficticio.payments.domain.model.Tariff;
import com.bancoficticio.payments.domain.port.TariffRepository;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** Company and general tariffs in PostgreSQL. Reference adapter of the fictitious application, written by hand. */
@Repository
public class JdbcTariffRepository implements TariffRepository {

    private final JdbcTemplate jdbc;

    public JdbcTariffRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<Tariff> companyTariff(Integer company, String service) {
        return jdbc.query(
                "SELECT company, service, amount, separate FROM company_tariff WHERE company = ? AND service = ?",
                (rs, n) -> new Tariff(rs.getInt("company"), rs.getString("service"), rs.getBigDecimal("amount"),
                        rs.getBoolean("separate")),
                company, service).stream().findFirst();
    }

    @Override
    public Optional<Tariff> serviceTariff(String service) {
        return jdbc.query(
                "SELECT service, amount FROM service_tariff WHERE service = ?",
                (rs, n) -> new Tariff(null, rs.getString("service"), rs.getBigDecimal("amount"), false),
                service).stream().findFirst();
    }
}
