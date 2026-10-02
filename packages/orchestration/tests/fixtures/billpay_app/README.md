# BillPay as an existing application (fictitious)

The fictitious Contoso BillPay service (see `packages/ivv/tests/fixtures/billpay`) with its own unit tests, as a
customer would hand it over to add functionality to it (Flow 3, ADR-0026). The tests use hand-written fakes of the
JDBC template and of the core banking client, so they run without a database. Nothing here comes from a real
customer or vendor.
