package com.bancoficticio.payments.adapters.out.jdbc;

import com.bancoficticio.payments.domain.model.PaymentOrder;
import com.bancoficticio.payments.domain.port.OrderRepository;
import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * Payment orders where the bank keeps them: db_pagos..pg_orden in Sybase ASE (ADR-0055, same database). Reference
 * adapter of the fictitious application, written by hand.
 */
@Repository
public class JdbcOrderRepository implements OrderRepository {

    private final JdbcTemplate jdbc;

    public JdbcOrderRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<PaymentOrder> find(Integer orderNumber, Integer company) {
        return jdbc.query(
                "select ord_numero, ord_empresa, ord_estado, ord_fecha_pago, ord_comision from db_pagos..pg_orden "
                        + "where ord_numero = ? and ord_empresa = ?",
                (rs, n) -> new PaymentOrder(rs.getInt("ord_numero"), rs.getInt("ord_empresa"),
                        rs.getString("ord_estado") == null ? null : rs.getString("ord_estado").trim(),
                        rs.getTimestamp("ord_fecha_pago") == null ? null : rs.getTimestamp("ord_fecha_pago").toLocalDateTime(),
                        rs.getBigDecimal("ord_comision")),
                orderNumber, company).stream().findFirst();
    }

    @Override
    public int markPaid(Integer orderNumber, Integer company, LocalDateTime paymentDate, BigDecimal commission) {
        return jdbc.update(
                "update db_pagos..pg_orden set ord_estado = 'A', ord_fecha_pago = ?, ord_comision = ? "
                        + "where ord_numero = ? and ord_empresa = ?",
                paymentDate == null ? null : Timestamp.valueOf(paymentDate), commission, orderNumber, company);
    }
}
