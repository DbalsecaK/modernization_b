package com.contoso.billpay.api;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/** A payment of one order, as the channels send it. */
public record PaymentRequest(
        Integer orderId,
        Integer companyId,
        String serviceCode,
        String accountType,
        String accountNumber,
        BigDecimal amount,
        String channel,
        LocalDateTime processDate) {
}
