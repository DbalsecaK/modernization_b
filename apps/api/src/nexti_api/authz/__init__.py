"""Authorization with OpenFGA (spec 16.4, D-15, ADR-0001). PostgreSQL is the source of truth; OpenFGA holds
tuples derived from it, kept in sync by an outbox and a reconciliation job."""
