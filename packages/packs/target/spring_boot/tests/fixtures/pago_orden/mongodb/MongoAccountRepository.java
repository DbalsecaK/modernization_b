package com.bancoficticio.payments.adapters.out.mongodb;

import com.bancoficticio.payments.domain.model.Account;
import com.bancoficticio.payments.domain.port.AccountRepository;
import com.mongodb.client.MongoCollection;
import com.mongodb.client.MongoDatabase;
import com.mongodb.client.model.Filters;
import java.util.Optional;
import org.bson.Document;
import org.bson.conversions.Bson;
import org.bson.types.Decimal128;
import org.springframework.stereotype.Repository;

/** Accounts in the MongoDB collection account. Reference adapter of the fictitious application, written by hand. */
@Repository
public class MongoAccountRepository implements AccountRepository {

    private final MongoCollection<Document> accounts;

    public MongoAccountRepository(MongoDatabase database) {
        this.accounts = database.getCollection("account");
    }

    @Override
    public Optional<Account> find(String number, String type) {
        Bson key = Filters.and(Filters.eq("number", number), Filters.eq("type", type));
        Document found = MongoTransaction.current().map(session -> accounts.find(session, key))
                .orElseGet(() -> accounts.find(key)).first();
        return Optional.ofNullable(found).map(d -> {
            Decimal128 balance = d.get("balance", Decimal128.class);
            return new Account(d.getString("number"), d.getString("type"),
                    balance == null ? null : balance.bigDecimalValue());
        });
    }
}
