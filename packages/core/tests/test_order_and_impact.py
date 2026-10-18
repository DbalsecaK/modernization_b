"""The migration order by the call graph (ADR-0055, point 12) and the impact of a change over the target
application (point 11)."""

from nexti_core.adapters import Edge, Inventory, Node
from nexti_core.impact import target_impact
from nexti_core.order import migration_order, order_text


def _program(key: str, external: bool = False) -> Node:
    return Node(
        key=key, label="Program", name=key.split(":", 1)[1], properties={"external": external} if external else {}
    )


def test_the_migration_goes_from_the_leaves_of_the_call_graph_up_and_keeps_cycles_together() -> None:
    # PAGOMNU -> PAGOORD -> PAGODEB, PAGOMOV; PAGOORD -> PAGOMNU (a cycle): the menu and the order go together.
    nodes = [_program("program:PAGOMNU"), _program("program:PAGOORD"), _program("program:PAGODEB"),
             _program("program:PAGOMOV"), _program("proc:sp_debito", external=True)]  # fmt: skip
    edges = [Edge("program:PAGOMNU", "CALLS", "program:PAGOORD"), Edge("program:PAGOORD", "CALLS", "program:PAGODEB"),
             Edge("program:PAGOORD", "CALLS", "program:PAGOMOV"), Edge("program:PAGOORD", "CALLS", "program:PAGOMNU"),
             Edge("program:PAGODEB", "CALLS", "proc:sp_debito"),
             Edge("block:PAGOORD#1", "CALLS", "program:PAGODEB")]  # a block edge is not a program edge  # fmt: skip
    levels = migration_order(Inventory(adapter="cobol-cics", nodes=nodes, edges=edges))
    assert [(level.number, level.programs) for level in levels] == [
        (0, ("PAGOMOV", "sp_debito")),
        (1, ("PAGODEB",)),
        (2, ("PAGOMNU", "PAGOORD")),
    ]
    assert levels[0].external == ("sp_debito",)
    assert levels[2].groups == (("PAGOMNU", "PAGOORD"),)
    text = order_text(levels)
    assert "- level 0: PAGOMOV; external, stay where they are or run as substitutes: sp_debito" in text
    assert "- level 2: PAGOMNU, PAGOORD (migrated together, they call each other: PAGOMNU <-> PAGOORD)" in text
    assert migration_order(Inventory(adapter="x")) == []


def test_a_change_in_the_target_reaches_the_files_tables_and_transactions_that_depend_on_it() -> None:
    jdbc = "src/main/java/app/adapters/out/jdbc"
    files = {
        "src/main/java/app/domain/port/AccountRepository.java": "public interface AccountRepository { }",
        f"{jdbc}/JdbcAccountRepository.java": "public class JdbcAccountRepository implements AccountRepository { "
        'String sql = "select cta_saldo from db_cuentas..ct_cuenta where cta_numero = ?"; }',
        "src/main/java/app/application/PayOrderService.java": "public class PayOrderService { "
        "PayOrderService(AccountRepository accounts, OrderRepository orders) {} }",
        "src/main/java/app/adapters/in/rest/PayOrderController.java": "public class PayOrderController { "
        "TransactionTemplate transaction; PayOrderService service; }",
        "src/main/java/app/domain/port/OrderRepository.java": "public interface OrderRepository { }",
        f"{jdbc}/JdbcOrderRepository.java": "public class JdbcOrderRepository implements OrderRepository { "
        "String sql = \"update db_pagos..pg_orden set ord_estado = 'A'\"; }",
        "src/main/java/app/Other.java": "public class Other { }",
        "src/main/resources/db/schema.sql": "CREATE TABLE account (number CHAR(10));",
    }
    impact = target_impact(files, ["src/main/java/app/domain/port/AccountRepository.java"])
    assert impact.affected == (
        "src/main/java/app/adapters/in/rest/PayOrderController.java",
        "src/main/java/app/adapters/out/jdbc/JdbcAccountRepository.java",
        "src/main/java/app/application/PayOrderService.java",
        "src/main/java/app/domain/port/AccountRepository.java",
    )
    assert impact.tables == ("db_cuentas..ct_cuenta",)  # the order table is reached by no affected file
    assert impact.transactions == ("src/main/java/app/adapters/in/rest/PayOrderController.java",)
    assert impact.by_file["src/main/java/app/adapters/in/rest/PayOrderController.java"] == (
        "src/main/java/app/domain/port/AccountRepository.java",
        "src/main/java/app/application/PayOrderService.java",
    )
    assert impact.names() == "4 file(s) affected, 1 table(s), 1 transaction boundary(ies)"
    nothing = target_impact(files, ["src/main/resources/db/schema.sql"])
    assert nothing.affected == ()


def test_a_use_case_writes_when_a_port_of_its_acknowledges_or_says_so() -> None:
    from nexti_core.spec.design import Design, writes

    design = Design.model_validate({
        "context": "orders", "base_package": "com.x.orders",
        "entities": [{"name": "Order", "table": "orders", "key": ["id"],
                      "fields": [{"name": "id", "type": "integer(32,signed)", "column": "id"}]}],
        "ports": [{"name": "OrderRepository", "entity": "Order", "methods": [
            {"name": "find", "returns": "Order"}, {"name": "save", "returns": None}]},
                  {"name": "RateReader", "methods": [{"name": "rateOf", "returns": "int"}]}],
        "use_cases": [{"name": "PlaceOrder", "rules": ["RULE-001"], "ports": ["OrderRepository"]},
                      {"name": "QuoteOrder", "rules": ["RULE-002"], "ports": ["RateReader"]}],
    })  # fmt: skip
    assert [writes(design, u) for u in design.use_cases] == [True, False]


def test_a_service_owned_transaction_counts_as_a_transaction_boundary() -> None:
    # Phase F: the service calls unitOfWork.begin() where the legacy has `begin tran`; the verifier that demands a
    # transaction boundary in every writing use case finds it there.
    from nexti_core.impact import TRANSACTION_BOUNDARY

    assert TRANSACTION_BOUNDARY.search("        unitOfWork.begin();")
    assert TRANSACTION_BOUNDARY.search("import org.springframework.transaction.support.TransactionTemplate;")
    assert not TRANSACTION_BOUNDARY.search("        unitOfWork.savepoint(SAVEPOINT);")
