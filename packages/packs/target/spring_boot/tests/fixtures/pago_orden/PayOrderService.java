package com.bancoficticio.payments.application;

import com.bancoficticio.payments.adapters.in.rest.PayOrderRequest;
import com.bancoficticio.payments.adapters.in.rest.PayOrderResponse;
import com.bancoficticio.payments.domain.error.BusinessError;
import com.bancoficticio.payments.domain.model.Account;
import com.bancoficticio.payments.domain.model.PaymentOrder;
import com.bancoficticio.payments.domain.model.Tariff;
import com.bancoficticio.payments.domain.port.AccountRepository;
import com.bancoficticio.payments.domain.port.DebitGateway;
import com.bancoficticio.payments.domain.port.OrderRepository;
import com.bancoficticio.payments.domain.port.TariffRepository;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Set;

/** Pays one order (RULE-001..RULE-009). Reference implementation of the fictitious application, written by hand. */
public class PayOrderService {

    private static final Set<String> DEBITABLE = Set.of("CTE", "AHO", "VIR");
    private static final BigDecimal OVERDRAFT = new BigDecimal("100.00");

    private final OrderRepository orders;
    private final TariffRepository tariffs;
    private final AccountRepository accounts;
    private final DebitGateway debits;

    public PayOrderService(OrderRepository orders, TariffRepository tariffs, AccountRepository accounts, DebitGateway debits) {
        this.orders = orders;
        this.tariffs = tariffs;
        this.accounts = accounts;
        this.debits = debits;
    }

    public PayOrderResponse execute(PayOrderRequest request) {
        if (!DEBITABLE.contains(request.accountType())) {
            throw new BusinessError("ACCOUNT_TYPE_NOT_ALLOWED", "50001", "TIPO DE CUENTA NO PERMITIDO");
        }
        PaymentOrder order = orders.find(request.orderNumber(), request.company())
                .orElseThrow(() -> new BusinessError("ORDER_NOT_FOUND", "50002", "ORDEN NO EXISTE"));
        if (!"P".equals(order.state())) {
            throw new BusinessError("ORDER_NOT_PENDING", "50003", "ORDEN NO ESTA PENDIENTE");
        }
        Tariff tariff = tariffs.companyTariff(request.company(), request.service())
                .or(() -> tariffs.serviceTariff(request.service()))
                .orElse(new Tariff(request.company(), request.service(), BigDecimal.ZERO, false));
        BigDecimal amount = tariff.amount() == null ? BigDecimal.ZERO : tariff.amount();
        BigDecimal commission = "WEB".equals(request.channel())
                ? amount.divide(BigDecimal.valueOf(2), 2, RoundingMode.HALF_UP)
                : amount;
        if ("NOMINA".equals(request.service())) {
            commission = BigDecimal.ZERO;
        }
        boolean separate = Boolean.TRUE.equals(tariff.separate());
        BigDecimal total = separate ? request.amount() : request.amount().add(commission);
        BigDecimal balance = accounts.find(request.account(), request.accountType())
                .map(Account::balance).orElse(BigDecimal.ZERO);
        boolean virtual = "VIR".equals(request.accountType());
        if ((virtual && balance.compareTo(total) < 0) || (!virtual && balance.add(OVERDRAFT).compareTo(total) < 0)) {
            throw new BusinessError("INSUFFICIENT_FUNDS", "50004", "FONDOS INSUFICIENTES");
        }
        long movement;
        try {
            movement = debits.debit(request.account(), request.accountType(), total, "PAGO ORDEN");
        } catch (RuntimeException e) {
            throw new BusinessError("DEBIT_FAILED", "50005", "ERROR EN DEBITO");
        }
        if (separate && commission.signum() > 0) {
            try {
                debits.debit(request.account(), request.accountType(), commission, "COMISION PAGO");
            } catch (RuntimeException e) {
                throw new BusinessError("COMMISSION_FAILED", "50006", "ERROR EN COMISION");
            }
        }
        if (orders.markPaid(request.orderNumber(), request.company(), request.processingDate(), commission) == 0) {
            throw new BusinessError("ORDER_NOT_UPDATED", "50007", "ERROR ACTUALIZANDO ORDEN");
        }
        return new PayOrderResponse(movement, "PAGO REALIZADO");
    }
}
