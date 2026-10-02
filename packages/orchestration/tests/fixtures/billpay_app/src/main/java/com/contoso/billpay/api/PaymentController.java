package com.contoso.billpay.api;

import com.contoso.billpay.domain.PaymentService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1")
public class PaymentController {
    private final PaymentService payments;

    public PaymentController(PaymentService payments) {
        this.payments = payments;
    }

    @PostMapping("/payments")
    public ResponseEntity<PaymentResult> pay(@RequestBody PaymentRequest request) {
        PaymentResult result = payments.pay(request);
        return result.status() == 0 ? ResponseEntity.ok(result) : ResponseEntity.unprocessableEntity().body(result);
    }
}
