"""Model gateway (spec 12.7, rule 2 of CLAUDE.md): no code outside this package calls a model provider or reads
a provider credential. It applies the tenant policy, the profile (effort, limits, fallback), the budget, and
records every call in the usage ledger."""
