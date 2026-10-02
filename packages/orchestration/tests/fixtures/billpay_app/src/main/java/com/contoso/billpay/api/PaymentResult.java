package com.contoso.billpay.api;

/** status 0 is a payment made; any other status is the business error code. */
public record PaymentResult(int status, Long movementId, String message) {
}
