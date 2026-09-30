package com.bancoficticio.payments.adapters.out.jdbc;

import com.bancoficticio.payments.domain.model.PaymentOrder;
import com.bancoficticio.payments.domain.port.OrderRepository;
import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** Payment orders in PostgreSQL. Reference adapter of the fictitious application, written by hand. */
@Repository
public class JdbcOrderRepository implements OrderRepository {

    private final JdbcTemplate jdbc;

    public JdbcOrderRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<PaymentOrder> find(Integer orderNumber, Integer company) {
        return jdbc.query(
                "SELECT order_number, company, state, payment_date, commission FROM payment_order "
                        + "WHERE order_number = ? AND company = ?",
                (rs, n) -> new PaymentOrder(rs.getInt("order_number"), rs.getInt("company"), rs.getString("state"),
                        rs.getTimestamp("payment_date") == null ? null : rs.getTimestamp("payment_date").toLocalDateTime(),
                        rs.getBigDecimal("commission")),
                orderNumber, company).stream().findFirst();
    }

    @Override
    public int markPaid(Integer orderNumber, Integer company, LocalDateTime paymentDate, BigDecimal commission) {
        return jdbc.update(
                "UPDATE payment_order SET state = 'A', payment_date = ?, commission = ? WHERE order_number = ? AND company = ?",
                paymentDate == null ? null : Timestamp.valueOf(paymentDate), commission, orderNumber, company);
    }
}
