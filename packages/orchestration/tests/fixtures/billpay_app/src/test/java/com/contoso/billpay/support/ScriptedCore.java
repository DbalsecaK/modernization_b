package com.contoso.billpay.support;

import com.contoso.billpay.infra.CoreBankingClient;
import java.math.BigDecimal;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;

/** The core banking debit for unit tests: answers in the scripted order and records every debit. */
public class ScriptedCore extends CoreBankingClient {
    private final Deque<Debit> answers = new ArrayDeque<>();
    public final List<String> debits = new ArrayList<>();

    public ScriptedCore() {
        super("http://core.invalid/debit");
    }

    public ScriptedCore answer(int code, Long sequence) {
        answers.add(new Debit(code, sequence));
        return this;
    }

    @Override
    public Debit debit(String account, String type, BigDecimal amount, String reference) {
        debits.add(account + " " + type + " " + amount.toPlainString() + " " + reference);
        return answers.isEmpty() ? new Debit(0, 1L) : answers.poll();
    }
}
