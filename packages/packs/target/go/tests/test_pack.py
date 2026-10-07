"""The Go pack (spec 8.4, ADR-0029): neutral types map exactly to Go and PostgreSQL, the idiomatic skeleton follows
from the design, and a hand-written reference target of the fictitious application builds, passes its tests and
reproduces the 12 cases Sybase recorded (the same golden master as the Java and .NET packs); without the declared mask
the one real difference shows up, and a canary mutation is caught. Sandbox tests skip without Docker or the image
nexti-sandbox-go:1 (infra/sandbox/go)."""

import asyncio
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from nexti_adapter_sybase.ase import RecordedRunner
from nexti_agents import prompt
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import GoldenMaster, Suite
from nexti_core.spec.design import Design
from nexti_pack_go import IMAGE, go_type, layer_of, module_path, skeleton, sql_type
from nexti_pack_go.build import build_errors, junit_from_events
from nexti_pack_go.canary import mutations
from nexti_pack_go.equivalence import glue, plan, run_equivalence, target_case
from nexti_pack_go.generate import GO_SUM, INDIRECT, REQUIRE
from nexti_pack_go.pack import PACK
from nexti_pack_spring_boot.pack import PACK as SPRING_BOOT
from nexti_sandbox import DockerSandbox
from nexti_sandbox.build import parse_junit

HERE = Path(__file__).parent / "fixtures" / "pago_orden"
PACKS = Path(__file__).resolve().parents[2]
REPO = PACKS.parents[2]
LEGACY = PACKS.parents[1] / "adapters/source/sybase/tests/fixtures/pago_orden"
DESIGN = Design.model_validate_json((PACKS / "spring_boot/tests/fixtures/pago_orden/design.json").read_text("utf-8"))
PAY = DESIGN.use_cases[0]
SUITE = Suite.model_validate_json((LEGACY / "characterization.json").read_text(encoding="utf-8"))
SOURCE = [SourceFile("sp/sp_pago_orden.sp", (LEGACY / "sp_pago_orden.sp").read_text(encoding="utf-8"))]
MASTER: GoldenMaster = asyncio.run(RecordedRunner(LEGACY / "golden", "replay").run(SOURCE, SUITE))


def reference_project(design: Design) -> dict[str, str]:
    files = PACK.skeleton(design)
    files[PACK.service_path(design, PAY)] = (HERE / "pay_order_service.go").read_text(encoding="utf-8")
    files[PACK.test_path(design, PAY)] = (HERE / "pay_order_service_test.go").read_text(encoding="utf-8")
    for port in design.ports:
        files[PACK.adapter_path(design, port)] = (HERE / Path(PACK.adapter_path(design, port)).name).read_text("utf-8")
    return files


@pytest.mark.parametrize(
    ("neutral", "go", "sql"),
    [
        ("decimal(19,4,signed)", "*decimal.Decimal", "NUMERIC(19,4)"),
        ("integer(32,signed)", "*int32", "INTEGER"),
        ("integer(64,signed)", "*int64", "BIGINT"),
        ("integer(32,unsigned)", "*int64", "BIGINT"),
        ("integer(16,signed)", "*int32", "SMALLINT"),
        ("text(fixed,3,iso8859-1)", "*string", "CHAR(3)"),
        ("text(var,max,utf8)", "*string", "TEXT"),
        ("timestamp(local)", "*time.Time", "TIMESTAMP"),
        ("timestamp(tz)", "*time.Time", "TIMESTAMPTZ"),
        ("date(yyyy-MM-dd)", "*time.Time", "DATE"),
        ("boolean", "*bool", "BOOLEAN"),
        ("enum(CTE|AHO|VIR)", "*string", "VARCHAR(3)"),
        ("binary(16)", "[]byte", "BYTEA"),
    ],
)
def test_neutral_types_map_to_go_and_postgresql(neutral: str, go: str, sql: str) -> None:
    assert (go_type(neutral), sql_type(neutral)) == (go, sql)


def test_the_skeleton_is_idiomatic_go_and_follows_from_the_design() -> None:
    files = skeleton(DESIGN)
    assert module_path(DESIGN) == "bancoficticio.com/payments"
    assert files["go.mod"].startswith("module bancoficticio.com/payments\n\ngo 1.26\n")
    assert "type PaymentOrder struct {\n\tOrderNumber *int32\n" in files["internal/domain/payment_order.go"]
    assert (
        "Debit(ctx context.Context, account *string, typ *string, amount *decimal.Decimal, reference *string) "
        "(int64, error)"
    ) in files["internal/ports/debit_gateway.go"]
    assert "Find(ctx context.Context, orderNumber *int32, company *int32) (*domain.PaymentOrder, error)" in files[
        "internal/ports/order_repository.go"]  # fmt: skip
    assert 'Amount         *decimal.Decimal `json:"amount"`' in files["internal/app/pay_order_contract.go"]
    assert "type BusinessError struct {" in files["internal/domain/errors.go"]
    assert '_ "github.com/jackc/pgx/v5/stdlib"' in files["internal/adapters/pg/db.go"]
    assert files["db/schema.sql"] == SPRING_BOOT.skeleton(DESIGN)["src/main/resources/db/schema.sql"]
    assert "PRIMARY KEY (order_number, company)" in files["db/schema.sql"]
    server = files["cmd/server/main.go"]
    assert 'mux.Handle("POST /api/payments/orders/pay", httpapi.PayOrder(db, payOrderService))' in server
    assert "app.NewPayOrderService(orderRepository, tariffRepository, accountRepository, debitGateway)" in server
    assert {p for p in files if PACK.held_back(p)} == {
        "cmd/server/main.go", "internal/adapters/httpapi/pay_order_handler.go",
    }  # fmt: skip
    assert layer_of("internal/app/pay_order_contract.go", DESIGN) == "contracts"
    assert layer_of("internal/app/pay_order_service.go", DESIGN) == "domain"
    assert layer_of("internal/ports/debit_gateway.go", DESIGN) == "domain"
    assert layer_of("internal/adapters/pg/order_repository.go", DESIGN) == "adapters"
    assert layer_of("internal/app/pay_order_service_test.go", DESIGN) == "tests"
    assert layer_of("cmd/server/main.go", DESIGN) == "orchestration"


def test_the_module_requires_exactly_what_the_image_caches() -> None:
    seed = REPO / "infra/sandbox/go/seed"
    assert (seed / "go.sum").read_text(encoding="utf-8") == GO_SUM
    required = dict(re.findall(r"^\t(\S+) (v\S+)", (seed / "go.mod").read_text(encoding="utf-8"), re.MULTILINE))
    assert required == REQUIRE | INDIRECT
    assert skeleton(DESIGN)["go.sum"] == GO_SUM


def test_a_method_without_a_body_takes_the_request_from_the_query() -> None:
    data = DESIGN.model_dump(mode="json")
    data["use_cases"][0] = {**data["use_cases"][0], "http_method": "GET", "path": "/orders"}
    files = skeleton(Design.model_validate(data))
    handler = files["internal/adapters/httpapi/pay_order_handler.go"]
    assert '"encoding/json"' not in handler
    assert 'if request.OrderNumber, err = queryInt32(q, "orderNumber"); err != nil {' in handler
    assert 'mux.Handle("GET /api/payments/orders"' in files["cmd/server/main.go"]


def test_the_answer_must_carry_go() -> None:
    assert PACK.code_block("Here:\n```go\npackage app\n\ntype A struct{}\n```").startswith("package app")
    with pytest.raises(ValueError, match="no Go file"):
        PACK.code_block("```java\nclass A {}\n```")


def test_the_canary_changes_one_go_line_deterministically() -> None:
    source = (HERE / "pay_order_service.go").read_text(encoding="utf-8")
    found = mutations(source)
    assert len(found) == 3
    assert found == mutations(source)
    assert all(m.before != m.after and m.after in m.source for m in found)
    assert 'decimal.RequireFromString("100.01")' in found[0].after
    assert all('"github.com' not in m.before for m in found)
    every = mutations(source, limit=20)
    changes = {m.after.strip() for m in every}
    assert "commission = amount.Div(decimal.NewFromInt(2)).Truncate(2)" in changes
    assert any(".LessThanOrEqual(total)" in c for c in changes)
    assert any('"WEBX"' in c for c in changes)
    assert "if updated != 0 {" in changes


def test_a_legacy_case_is_translated_with_postgresql_types() -> None:
    case = next(r.case for r in MASTER.results if r.case.name == "separate_commission_is_a_second_debit")
    target = target_case(DESIGN, PAY, case)
    assert (
        "INSERT INTO company_tariff (company, service, amount, separate) VALUES (CAST('10' AS INTEGER), "
        "CAST('AGUA' AS VARCHAR(10)), CAST('1.5000' AS NUMERIC(19,4)), CAST('true' AS BOOLEAN))"
    ) in target["setup"]
    harness = plan(DESIGN, PAY)
    assert harness["reset"] == ["TRUNCATE payment_order, company_tariff, account, service_tariff"]
    assert harness["dump"][0]["sql"].startswith("SELECT order_number::text AS order_number, company::text AS company")


def test_the_glue_uses_the_adapters_and_fakes_the_external_program() -> None:
    source = glue(DESIGN, PAY)
    assert (
        "app.NewPayOrderService(pg.NewOrderRepository(db), pg.NewTariffRepository(db), pg.NewAccountRepository(db), "
        "&fakeDebitGateway{rec: rec})"
    ) in source
    assert 'f.rec.call("DebitGateway", "debit", text(account), text(typ), text(amount), text(reference))' in source
    assert 'OrderNumber:    asInt32(in["orderNumber"]),' in source
    assert '"message":  text(response.Message),' in source


def test_go_test_events_become_the_same_test_report() -> None:
    events: list[dict[str, Any]] = [
        {"Action": "run", "Package": "m/internal/app", "Test": "TestA"},
        {"Action": "pass", "Package": "m/internal/app", "Test": "TestA", "Elapsed": 0.01},
        {"Action": "run", "Package": "m/internal/app", "Test": "TestB"},
        {"Action": "run", "Package": "m/internal/app", "Test": "TestB/one"},
        {"Action": "pass", "Package": "m/internal/app", "Test": "TestB/one"},
        {"Action": "output", "Package": "m/internal/app", "Test": "TestB/two", "Output": "    x_test.go:9: want 1\n"},
        {"Action": "fail", "Package": "m/internal/app", "Test": "TestB/two"},
        {"Action": "fail", "Package": "m/internal/app", "Test": "TestB"},
        {"Action": "fail", "Package": "m/internal/app"},
        {"Action": "output", "Package": "m/internal/pg", "Output": "panic: boom\n"},
        {"Action": "fail", "Package": "m/internal/pg"},
        {"Action": "skip", "Package": "m/internal/domain"},
    ]
    tests = parse_junit(junit_from_events(events))
    assert [(t.classname, t.name, t.status) for t in tests] == [
        ("m/internal/app", "TestA", "passed"), ("m/internal/app", "TestB/one", "passed"),
        ("m/internal/app", "TestB/two", "failed"), ("m/internal/pg", "(package)", "failed"),
    ]  # fmt: skip
    assert "want 1" in tests[2].message
    failed: list[dict[str, Any]] = [
        {"Action": "build-output", "Output": "./a_test.go:3:1: undefined: x\n"},
        {"Action": "build-fail"},
    ]
    assert build_errors(failed) == "./a_test.go:3:1: undefined: x"
    assert build_errors(events) == ""


def test_a_probe_names_each_service_and_adapter_as_the_wiring_does() -> None:
    probe = PACK.probe(DESIGN, PACK.adapter_path(DESIGN, DESIGN.ports[0]))["internal/probe/probe.go"]
    assert "var _ func(*pg.DB) *pg.OrderRepository = pg.NewOrderRepository" in probe
    assert "var _ ports.OrderRepository = (*pg.OrderRepository)(nil)" in probe
    service = PACK.probe(DESIGN, PACK.service_path(DESIGN, PAY))["internal/probe/probe.go"]
    assert (
        "var _ func(ports.OrderRepository, ports.TariffRepository, ports.AccountRepository, ports.DebitGateway) "
        "*app.PayOrderService = app.NewPayOrderService"
    ) in service
    assert PACK.probe(DESIGN, "db/schema.sql") == {}


def test_the_prompts_are_the_go_ones() -> None:
    developer, tester = prompt(PACK.developer_prompt), prompt(PACK.tester_prompt)
    assert "shopspring/decimal" in developer
    assert "func (s *<UseCase>Service) Execute(ctx context.Context" in developer
    assert "package app_test" in tester
    assert "```go" in developer
    assert "```go" in tester
    request = PACK.adapter_request(DESIGN, "AccountRepository", PACK.skeleton(DESIGN))
    assert "func NewAccountRepository(db *DB) *AccountRepository" in request
    assert "CREATE TABLE account" in request
    assert PACK.describe() == {"name": "go", "image": IMAGE, "database": "postgresql"}


def _image_available() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


@pytest.fixture(scope="module")
def go_sandbox() -> DockerSandbox:
    box = DockerSandbox(image=IMAGE)
    if not asyncio.run(box.available()) or not _image_available():
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    return box


def test_the_skeleton_alone_compiles(go_sandbox: DockerSandbox) -> None:
    files = {p: c for p, c in PACK.skeleton(DESIGN).items() if not PACK.held_back(p)}
    build = asyncio.run(PACK.compile_and_test(go_sandbox, files, run_tests=False))
    assert build.compiled, build.compile_errors


def test_the_service_and_its_tests_pass_before_the_handlers_join(go_sandbox: DockerSandbox) -> None:
    """The generation's middle step: the service and its tests, while the wiring and the handlers wait."""
    adapters = {PACK.adapter_path(DESIGN, port) for port in DESIGN.ports}
    files = {p: c for p, c in reference_project(DESIGN).items() if not PACK.held_back(p) and p not in adapters}
    files |= PACK.probe(DESIGN, PACK.service_path(DESIGN, PAY))
    build = asyncio.run(PACK.compile_and_test(go_sandbox, files))
    assert build.compiled, build.compile_errors
    assert (build.passed, build.failed) == (7, 0)
    assert build.junit_xml.startswith("<?xml")


def test_a_compile_error_is_reported(go_sandbox: DockerSandbox) -> None:
    files = reference_project(DESIGN)
    files[PACK.service_path(DESIGN, PAY)] += "\nthis is not Go\n"
    build = asyncio.run(PACK.compile_and_test(go_sandbox, files))
    assert not build.compiled
    assert "pay_order_service.go" in build.compile_errors


def test_a_failing_test_is_counted(go_sandbox: DockerSandbox) -> None:
    files = reference_project(DESIGN)
    target = PACK.test_path(DESIGN, PAY)
    files[target] = files[target].replace('assertDebited(t, w, "102.00")', 'assertDebited(t, w, "102.01")')
    build = asyncio.run(PACK.compile_and_test(go_sandbox, files))
    assert build.compiled, build.compile_errors
    assert (build.passed, build.failed) == (6, 1)
    assert "102.01" in build.diagnostic()


def test_the_reference_target_reproduces_the_golden_master(go_sandbox: DockerSandbox) -> None:
    run = asyncio.run(run_equivalence(go_sandbox, reference_project(DESIGN), DESIGN, PAY, MASTER))
    assert run.problem is None, run.problem
    assert (run.build.passed, run.build.failed) == (7, 0)
    different = {c.name: (c.failure, c.expected, c.actual) for c in run.cases if c.failure or c.expected != c.actual}
    assert len(run.cases) == 12
    assert different == {}


def test_without_the_declared_mask_the_rejected_path_output_is_masked_with_its_reason(
    go_sandbox: DockerSandbox,
) -> None:
    # P36 (ADR-0044): on a path the legacy rejects, the target raises its business error; the legacy output that
    # the design did not mask is masked automatically, declared with its reason, never silently.
    undeclared = Design.model_validate({**json.loads(DESIGN.model_dump_json()), "masks": []})
    run = asyncio.run(run_equivalence(go_sandbox, reference_project(undeclared), undeclared, PAY, MASTER))
    assert [c.name for c in run.cases if c.failure or c.expected != c.actual] == []
    declared = {m.path: m for m in run.masks}
    assert declared["outputs:@o_movimiento"].when == "rejected"
    assert declared["outputs:@o_movimiento"].reason.startswith("a rejection of the target is an exception")


def test_the_canary_is_caught(go_sandbox: DockerSandbox) -> None:
    files = reference_project(DESIGN)
    target = PACK.service_path(DESIGN, PAY)
    mutation = PACK.mutations(files[target])[0]
    run = asyncio.run(PACK.run_equivalence(go_sandbox, {**files, target: mutation.source}, DESIGN, PAY, MASTER))
    differs = [c.name for c in run.cases if c.failure or c.expected != c.actual]
    assert run.build.failed > 0 or differs


def test_an_adapter_with_another_constructor_does_not_compile(go_sandbox: DockerSandbox) -> None:
    files = reference_project(DESIGN)
    port = DESIGN.ports[0]
    target = PACK.adapter_path(DESIGN, port)
    files[target] = files[target].replace("func NewOrderRepository(db *DB)", "func NewOrders(db *DB)")
    files = {p: c for p, c in files.items() if not PACK.held_back(p)} | PACK.probe(DESIGN, target)
    build = asyncio.run(PACK.compile_and_test(go_sandbox, files, run_tests=False))
    assert not build.compiled
    assert "probe.go" in build.compile_errors
