package com.bancoficticio.payments.adapters.out.jdbc;

import com.bancoficticio.payments.domain.model.PaymentOrder;
import com.bancoficticio.payments.domain.port.OrderRepository;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import java.math.BigDecimal;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.sql.Types;
import java.time.LocalDateTime;
import java.util.Optional;
import javax.sql.DataSource;

/** Payment orders in PostgreSQL over the Agroal datasource. Reference adapter of the fictitious application, by hand. */
@ApplicationScoped
public class JdbcOrderRepository implements OrderRepository {

    private final DataSource dataSource;

    @Inject
    public JdbcOrderRepository(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    @Override
    public Optional<PaymentOrder> find(Integer orderNumber, Integer company) {
        try (Connection connection = dataSource.getConnection();
                PreparedStatement statement = connection.prepareStatement(
                        "SELECT order_number, company, state, payment_date, commission FROM payment_order "
                                + "WHERE order_number = ? AND company = ?")) {
            statement.setObject(1, orderNumber, Types.INTEGER);
            statement.setObject(2, company, Types.INTEGER);
            try (ResultSet rs = statement.executeQuery()) {
                if (!rs.next()) {
                    return Optional.empty();
                }
                Timestamp paid = rs.getTimestamp("payment_date");
                return Optional.of(new PaymentOrder(rs.getInt("order_number"), rs.getInt("company"),
                        rs.getString("state"), paid == null ? null : paid.toLocalDateTime(),
                        rs.getBigDecimal("commission")));
            }
        } catch (SQLException e) {
            throw new IllegalStateException("order lookup failed", e);
        }
    }

    @Override
    public int markPaid(Integer orderNumber, Integer company, LocalDateTime paymentDate, BigDecimal commission) {
        try (Connection connection = dataSource.getConnection();
                PreparedStatement statement = connection.prepareStatement(
                        "UPDATE payment_order SET state = 'A', payment_date = ?, commission = ? "
                                + "WHERE order_number = ? AND company = ?")) {
            statement.setTimestamp(1, paymentDate == null ? null : Timestamp.valueOf(paymentDate));
            statement.setBigDecimal(2, commission);
            statement.setObject(3, orderNumber, Types.INTEGER);
            statement.setObject(4, company, Types.INTEGER);
            return statement.executeUpdate();
        } catch (SQLException e) {
            throw new IllegalStateException("order update failed", e);
        }
    }
}
