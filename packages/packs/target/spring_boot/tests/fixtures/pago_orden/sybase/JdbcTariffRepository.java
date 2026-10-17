package com.bancoficticio.payments.adapters.out.jdbc;

import com.bancoficticio.payments.domain.model.Tariff;
import com.bancoficticio.payments.domain.port.TariffRepository;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * Company and general tariffs where the bank keeps them: db_admin..ad_tarifa_empresa and db_admin..ad_servicio in
 * Sybase ASE (ADR-0055, same database). The legacy stores the separate flag as 'S'/'N'. Reference adapter of the
 * fictitious application, written by hand.
 */
@Repository
public class JdbcTariffRepository implements TariffRepository {

    private final JdbcTemplate jdbc;

    public JdbcTariffRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<Tariff> companyTariff(Integer company, String service) {
        return jdbc.query(
                "select tar_empresa, tar_servicio, tar_valor, tar_separada from db_admin..ad_tarifa_empresa "
                        + "where tar_empresa = ? and tar_servicio = ?",
                (rs, n) -> new Tariff(rs.getInt("tar_empresa"), rs.getString("tar_servicio").trim(),
                        rs.getBigDecimal("tar_valor"), "S".equalsIgnoreCase(trimmed(rs.getString("tar_separada")))),
                company, service).stream().findFirst();
    }

    @Override
    public Optional<Tariff> serviceTariff(String service) {
        return jdbc.query(
                "select srv_codigo, srv_tarifa from db_admin..ad_servicio where srv_codigo = ?",
                (rs, n) -> new Tariff(null, rs.getString("srv_codigo").trim(), rs.getBigDecimal("srv_tarifa"), false),
                service).stream().findFirst();
    }

    private static String trimmed(String value) {
        return value == null ? "" : value.trim();
    }
}
