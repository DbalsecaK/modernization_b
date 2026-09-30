package com.bancoficticio.payments.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.bancoficticio.payments.adapters.in.rest.PayOrderRequest;
import com.bancoficticio.payments.domain.error.BusinessError;
import com.bancoficticio.payments.domain.model.Account;
import com.bancoficticio.payments.domain.model.PaymentOrder;
import com.bancoficticio.payments.domain.model.Tariff;
import com.bancoficticio.payments.domain.port.AccountRepository;
import com.bancoficticio.payments.domain.port.DebitGateway;
import com.bancoficticio.payments.domain.port.OrderRepository;
import com.bancoficticio.payments.domain.port.TariffRepository;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;

/** Tests of the reference implementation with in-memory ports (one per rule scenario). */
class PayOrderServiceTest {

    static final LocalDateTime DAY = LocalDateTime.of(2026, 9, 29, 10, 0);

    final List<BigDecimal> debited = new ArrayList<>();
    String state = "P";
    Tariff tariff = new Tariff(7, "PAGOS", new BigDecimal("1.25"), false);
    BigDecimal balance = new BigDecimal("500.00");

    PayOrderService service() {
        OrderRepository orders = new OrderRepository() {
            public Optional<PaymentOrder> find(Integer orderNumber, Integer company) {
                return state == null ? Optional.empty()
                        : Optional.of(new PaymentOrder(orderNumber, company, state, null, BigDecimal.ZERO));
            }

            public int markPaid(Integer orderNumber, Integer company, LocalDateTime paymentDate, BigDecimal commission) {
                return 1;
            }
        };
        TariffRepository tariffs = new TariffRepository() {
            public Optional<Tariff> companyTariff(Integer company, String service) {
                return Optional.ofNullable(tariff);
            }

            public Optional<Tariff> serviceTariff(String service) {
                return Optional.of(new Tariff(0, service, new BigDecimal("2.00"), false));
            }
        };
        AccountRepository accounts = (number, type) -> Optional.of(new Account(number, type, balance));
        DebitGateway debits = (account, type, amount, reference) -> {
            debited.add(amount);
            return 900L + debited.size();
        };
        return new PayOrderService(orders, tariffs, accounts, debits);
    }

    PayOrderRequest request(String accountType, String channel, String service, String amount) {
        return new PayOrderRequest(1, 7, service, accountType, "0012345678", new BigDecimal(amount), channel, DAY);
    }

    @Test
    void a_credit_card_account_cannot_be_debited() {
        assertThatThrownBy(() -> service().execute(request("TCR", "WEB", "PAGOS", "10")))
                .isInstanceOf(BusinessError.class).extracting("legacyCode").isEqualTo("50001");
    }

    @Test
    void a_web_order_pays_half_the_tariff_rounded() {
        var response = service().execute(request("CTE", "WEB", "PAGOS", "100.00"));
        assertThat(debited).containsExactly(new BigDecimal("100.63"));
        assertThat(response.movement()).isEqualTo(901L);
        assertThat(response.message()).isEqualTo("PAGO REALIZADO");
    }

    @Test
    void payroll_pays_no_commission() {
        service().execute(request("AHO", "OFI", "NOMINA", "100.00"));
        assertThat(debited).containsExactly(new BigDecimal("100.00"));
    }

    @Test
    void without_a_company_tariff_the_general_tariff_applies() {
        tariff = null;
        service().execute(request("CTE", "OFI", "PAGOS", "100.00"));
        assertThat(debited).containsExactly(new BigDecimal("102.00"));
    }

    @Test
    void a_separate_commission_is_a_second_debit() {
        tariff = new Tariff(7, "PAGOS", new BigDecimal("3.00"), true);
        service().execute(request("CTE", "OFI", "PAGOS", "100.00"));
        assertThat(debited).containsExactly(new BigDecimal("100.00"), new BigDecimal("3.00"));
    }

    @Test
    void a_virtual_account_cannot_overdraw_but_others_can_up_to_100() {
        balance = new BigDecimal("50.00");
        assertThatThrownBy(() -> service().execute(request("VIR", "OFI", "PAGOS", "49.00")))
                .extracting("legacyCode").isEqualTo("50004");
        service().execute(request("CTE", "OFI", "PAGOS", "147.00"));
        assertThat(debited).containsExactly(new BigDecimal("148.25"));
    }

    @Test
    void an_order_that_is_not_pending_is_rejected() {
        state = "A";
        assertThatThrownBy(() -> service().execute(request("CTE", "OFI", "PAGOS", "1")))
                .extracting("legacyCode").isEqualTo("50003");
    }
}
