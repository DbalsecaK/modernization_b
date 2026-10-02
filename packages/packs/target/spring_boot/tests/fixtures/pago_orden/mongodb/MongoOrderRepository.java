package com.bancoficticio.payments.adapters.out.mongodb;

import com.bancoficticio.payments.domain.model.PaymentOrder;
import com.bancoficticio.payments.domain.port.OrderRepository;
import com.mongodb.client.MongoCollection;
import com.mongodb.client.MongoDatabase;
import com.mongodb.client.model.Filters;
import com.mongodb.client.model.Updates;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.Date;
import java.util.Optional;
import org.bson.Document;
import org.bson.conversions.Bson;
import org.bson.types.Decimal128;
import org.springframework.stereotype.Repository;

/**
 * Payment orders in the MongoDB collection payment_order (one document per order, the fields under their column
 * names). Reference adapter of the fictitious application, written by hand.
 */
@Repository
public class MongoOrderRepository implements OrderRepository {

    private final MongoCollection<Document> orders;

    public MongoOrderRepository(MongoDatabase database) {
        this.orders = database.getCollection("payment_order");
    }

    @Override
    public Optional<PaymentOrder> find(Integer orderNumber, Integer company) {
        Bson key = key(orderNumber, company);
        Document found = MongoTransaction.current().map(session -> orders.find(session, key))
                .orElseGet(() -> orders.find(key)).first();
        return Optional.ofNullable(found).map(d -> new PaymentOrder(d.getInteger("order_number"),
                d.getInteger("company"), d.getString("state"), timestamp(d.getDate("payment_date")),
                decimal(d.get("commission", Decimal128.class))));
    }

    @Override
    public int markPaid(Integer orderNumber, Integer company, LocalDateTime paymentDate, BigDecimal commission) {
        Bson key = key(orderNumber, company);
        Bson update = Updates.combine(Updates.set("state", "A"),
                Updates.set("payment_date", paymentDate == null ? null : Date.from(paymentDate.toInstant(ZoneOffset.UTC))),
                Updates.set("commission", commission == null ? null
                        : new Decimal128(commission.setScale(4, RoundingMode.HALF_UP))));
        return (int) MongoTransaction.current().map(session -> orders.updateOne(session, key, update))
                .orElseGet(() -> orders.updateOne(key, update)).getMatchedCount();
    }

    private static Bson key(Integer orderNumber, Integer company) {
        return Filters.and(Filters.eq("order_number", orderNumber), Filters.eq("company", company));
    }

    private static LocalDateTime timestamp(Date value) {
        return value == null ? null : value.toInstant().atOffset(ZoneOffset.UTC).toLocalDateTime();
    }

    private static BigDecimal decimal(Decimal128 value) {
        return value == null ? null : value.bigDecimalValue();
    }
}
