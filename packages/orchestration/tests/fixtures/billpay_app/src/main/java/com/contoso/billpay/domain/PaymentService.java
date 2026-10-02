package com.contoso.billpay.domain;

import com.contoso.billpay.api.PaymentRequest;
import com.contoso.billpay.api.PaymentResult;
import com.contoso.billpay.infra.CoreBankingClient;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class PaymentService {
    private static final Set<String> DEBITABLE = Set.of("CTE", "AHO", "VIR");
    private static final BigDecimal OVERDRAFT = new BigDecimal("100.00");
    private final JdbcTemplate jdbc;
    private final CoreBankingClient core;

    public PaymentService(JdbcTemplate jdbc, CoreBankingClient core) {
        this.jdbc = jdbc;
        this.core = core;
    }

    public PaymentResult pay(PaymentRequest r) {
        if (!DEBITABLE.contains(r.accountType())) {
            return reject(50001, "TIPO DE CUENTA NO PERMITIDO");
        }
        List<String> status = jdbc.queryForList(
                "SELECT status FROM orders WHERE order_no = ? AND company_id = ?", String.class,
                r.orderId(), r.companyId());
        if (status.isEmpty()) {
            return reject(50002, "ORDEN NO EXISTE");
        }
        if (!"P".equals(status.get(0).trim())) {
            return reject(50003, "ORDEN NO ESTA PENDIENTE");
        }

        BigDecimal fee;
        boolean chargedApart;
        List<Map<String, Object>> companyFee = jdbc.queryForList(
                "SELECT fee, charged_apart FROM company_fees WHERE company_id = ? AND service_code = ?",
                r.companyId(), r.serviceCode());
        if (!companyFee.isEmpty()) {
            fee = (BigDecimal) companyFee.get(0).get("fee");
            chargedApart = "S".equals(String.valueOf(companyFee.get(0).get("charged_apart")).trim());
        } else {
            List<BigDecimal> serviceFee = jdbc.queryForList(
                    "SELECT fee FROM services WHERE code = ?", BigDecimal.class, r.serviceCode());
            fee = serviceFee.isEmpty() ? null : serviceFee.get(0);
            chargedApart = false;
        }
        if (fee == null) {
            fee = BigDecimal.ZERO;
        }

        String channel = r.channel() == null ? "WEB" : r.channel();
        BigDecimal commission = "WEB".equals(channel)
                ? fee.divide(BigDecimal.valueOf(2)).setScale(2, RoundingMode.HALF_UP)
                : fee;
        if ("NOMINA".equals(r.serviceCode())) {
            commission = BigDecimal.ZERO;
        }
        BigDecimal total = chargedApart ? r.amount() : r.amount().add(commission);

        List<BigDecimal> balance = jdbc.queryForList(
                "SELECT balance FROM accounts WHERE account_no = ? AND account_type = ?", BigDecimal.class,
                r.accountNumber(), r.accountType());
        if (!balance.isEmpty()) {
            BigDecimal available = "VIR".equals(r.accountType()) ? balance.get(0) : balance.get(0).add(OVERDRAFT);
            if (available.compareTo(total) < 0) {
                return reject(50004, "FONDOS INSUFICIENTES");
            }
        }

        CoreBankingClient.Debit debit = core.debit(r.accountNumber(), r.accountType(), total, "PAGO ORDEN");
        if (debit.code() != 0) {
            return reject(50005, "ERROR EN DEBITO");
        }
        if (chargedApart && commission.signum() > 0) {
            CoreBankingClient.Debit second = core.debit(r.accountNumber(), r.accountType(), commission, "COMISION PAGO");
            if (second.code() != 0) {
                return reject(50006, "ERROR EN COMISION");
            }
        }

        int updated = jdbc.update(
                "UPDATE orders SET status = 'A', paid_at = ?, fee = ? WHERE order_no = ? AND company_id = ?",
                r.processDate(), commission, r.orderId(), r.companyId());
        if (updated == 0) {
            return reject(50007, "ERROR ACTUALIZANDO ORDEN");
        }
        return new PaymentResult(0, debit.sequence(), "PAGO REALIZADO");
    }

    private static PaymentResult reject(int code, String message) {
        return new PaymentResult(code, null, message);
    }
}
