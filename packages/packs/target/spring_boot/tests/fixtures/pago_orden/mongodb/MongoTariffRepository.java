package com.bancoficticio.payments.adapters.out.mongodb;

import com.bancoficticio.payments.domain.model.Tariff;
import com.bancoficticio.payments.domain.port.TariffRepository;
import com.mongodb.client.MongoCollection;
import com.mongodb.client.MongoDatabase;
import com.mongodb.client.model.Filters;
import java.math.BigDecimal;
import java.util.Optional;
import org.bson.Document;
import org.bson.conversions.Bson;
import org.bson.types.Decimal128;
import org.springframework.stereotype.Repository;

/**
 * Company tariffs (collection company_tariff, which refers to service_tariff by service) and general tariffs
 * (collection service_tariff). Reference adapter of the fictitious application, written by hand.
 */
@Repository
public class MongoTariffRepository implements TariffRepository {

    private final MongoCollection<Document> companyTariffs;
    private final MongoCollection<Document> serviceTariffs;

    public MongoTariffRepository(MongoDatabase database) {
        this.companyTariffs = database.getCollection("company_tariff");
        this.serviceTariffs = database.getCollection("service_tariff");
    }

    @Override
    public Optional<Tariff> companyTariff(Integer company, String service) {
        Bson key = Filters.and(Filters.eq("company", company), Filters.eq("service", service));
        return first(companyTariffs, key).map(d -> new Tariff(d.getInteger("company"), d.getString("service"),
                decimal(d.get("amount", Decimal128.class)), d.getBoolean("separate")));
    }

    @Override
    public Optional<Tariff> serviceTariff(String service) {
        return first(serviceTariffs, Filters.eq("service", service)).map(d -> new Tariff(null, d.getString("service"),
                decimal(d.get("amount", Decimal128.class)), false));
    }

    private static Optional<Document> first(MongoCollection<Document> collection, Bson filter) {
        return Optional.ofNullable(MongoTransaction.current().map(session -> collection.find(session, filter))
                .orElseGet(() -> collection.find(filter)).first());
    }

    private static BigDecimal decimal(Decimal128 value) {
        return value == null ? null : value.bigDecimalValue();
    }
}
