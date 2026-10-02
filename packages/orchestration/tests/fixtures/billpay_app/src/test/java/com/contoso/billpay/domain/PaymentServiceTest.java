package com.contoso.billpay.domain;

import static org.assertj.core.api.Assertions.assertThat;

import com.contoso.billpay.api.PaymentRequest;
import com.contoso.billpay.api.PaymentResult;
import com.contoso.billpay.support.ScriptedCore;
import com.contoso.billpay.support.ScriptedJdbc;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class PaymentServiceTest {
    private static final LocalDateTime NOW = LocalDateTime.of(2026, 3, 2, 9, 30);

    private static PaymentRequest request(String accountType, String amount, String channel) {
        return new PaymentRequest(1001, 10, "LUZ", accountType, "0012345678", new BigDecimal(amount), channel, NOW);
    }

    private static ScriptedJdbc pendingOrder() {
        return new ScriptedJdbc()
                .answer("FROM orders", List.of("P"))
                .answer("FROM company_fees", List.of(Map.of("fee", new BigDecimal("2.00"), "charged_apart", "N")))
                .answer("FROM accounts", List.of(new BigDecimal("500.00")));
    }

    @Test
    void a_prepaid_account_cannot_pay() {
        PaymentResult result = new PaymentService(pendingOrder(), new ScriptedCore()).pay(request("PRE", "100", "WEB"));
        assertThat(result.status()).isEqualTo(50001);
        assertThat(result.message()).isEqualTo("TIPO DE CUENTA NO PERMITIDO");
    }

    @Test
    void an_unknown_order_is_rejected() {
        ScriptedJdbc jdbc = new ScriptedJdbc().answer("FROM orders", List.of());
        PaymentResult result = new PaymentService(jdbc, new ScriptedCore()).pay(request("CTE", "100", "WEB"));
        assertThat(result.status()).isEqualTo(50002);
    }

    @Test
    void a_web_payment_is_charged_half_the_company_fee() {
        ScriptedCore core = new ScriptedCore().answer(0, 7001L);
        PaymentResult result = new PaymentService(pendingOrder(), core).pay(request("CTE", "100", "WEB"));
        assertThat(result.status()).isZero();
        assertThat(result.movementId()).isEqualTo(7001L);
        assertThat(core.debits).containsExactly("0012345678 CTE 101.00 PAGO ORDEN");
    }

    @Test
    void a_savings_account_overdraws_up_to_100() {
        ScriptedJdbc jdbc = pendingOrder().answer("FROM accounts", List.of(new BigDecimal("10.00")));
        PaymentResult result = new PaymentService(jdbc, new ScriptedCore()).pay(request("AHO", "120", "OFICINA"));
        assertThat(result.status()).isEqualTo(50004);
    }

    @Test
    void a_failed_debit_leaves_the_order_pending() {
        ScriptedJdbc jdbc = pendingOrder();
        PaymentResult result = new PaymentService(jdbc, new ScriptedCore().answer(9, null)).pay(request("CTE", "100", "WEB"));
        assertThat(result.status()).isEqualTo(50005);
        assertThat(jdbc.executed).noneMatch(sql -> sql.startsWith("UPDATE orders"));
    }
}
