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
