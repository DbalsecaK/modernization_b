"""Independent validation (ADR-0025) of BillPay, a fictitious third-party migration of the reference application:
its inventory is read by code, the vendor's mapping fits the golden master recorded on Sybase, a proposal from names
lists what a person must complete, and the black-box run reproduces every golden case on the correct target while a
target with a changed overdraft rule fails the overdraft cases. Sandbox tests skip without Docker or the Java image."""

import asyncio
import subprocess
from pathlib import Path

import pytest

from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import GoldenMaster
from nexti_ivv import mapping as ivv_mapping
from nexti_ivv.runner import IMAGE, run
from nexti_ivv.target import TargetInventory, inventory
from nexti_sandbox import DockerSandbox

HERE = Path(__file__).resolve().parent
TARGET = HERE / "fixtures" / "billpay"
GOLDEN = HERE.parents[1] / "adapters/source/sybase/tests/fixtures/pago_orden/golden"
SERVICE = "src/main/java/com/contoso/billpay/domain/PaymentService.java"


def golden() -> GoldenMaster:
    masters = [GoldenMaster.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(GOLDEN.glob("*.json"))]
    return next(m for m in masters if any(r.case.name == "web_order_pays_half_the_service_tariff" for r in m.results))


def archive(changes: dict[str, tuple[str, str]] | None = None) -> dict[str, bytes]:
    found = {p.relative_to(TARGET).as_posix(): p.read_bytes() for p in TARGET.rglob("*") if p.is_file()}
    for path, (old, new) in (changes or {}).items():
        text = found[path].decode("utf-8")
        assert old in text
        found[path] = text.replace(old, new).encode("utf-8")
    return found


def target_inventory(files: dict[str, bytes]) -> TargetInventory:
    return inventory([SourceFile(p, d.decode("utf-8")) for p, d in files.items() if not p.endswith(".jar")],
                     [p for p in files if p.endswith(".jar")])  # fmt: skip


def test_the_inventory_of_the_target_is_read_by_code() -> None:
    found = target_inventory(archive())
    assert (found.stack, found.main_class, found.artifact) == ("spring-boot", "com.contoso.billpay.BillPayApplication",
                                                               None)  # fmt: skip
    (endpoint,) = found.endpoints
    assert (endpoint.method, endpoint.path, endpoint.handler) == ("POST", "/api/v1/payments", "PaymentController.pay")
    assert [f.name for f in endpoint.request] == ["orderId", "companyId", "serviceCode", "accountType",
                                                  "accountNumber", "amount", "channel", "processDate"]  # fmt: skip
    assert [f.name for f in endpoint.response] == ["status", "movementId", "message"]
    assert {t.name: t.key for t in found.tables} == {"orders": ("order_no", "company_id"),
                                                     "company_fees": ("company_id", "service_code"),
                                                     "services": ("code",),
                                                     "accounts": ("account_no", "account_type")}  # fmt: skip
    assert [s.unit for s in found.slices] == ["PaymentService.pay", "PaymentService.reject", "CoreBankingClient.debit"]
    assert found.properties["core.debit-url"] == "https://core.contoso.internal/debit"


def test_an_aspnet_core_target_is_inventoried_too() -> None:
    files = [
        SourceFile("Pay.csproj", '<Project Sdk="Microsoft.NET.Sdk.Web"></Project>'),
        SourceFile(
            "Api/PaymentsController.cs",
            """[ApiController]
[Route("api/[controller]")]
public class PaymentsController : ControllerBase {
    [HttpPost("pay")]
    public ActionResult<PayResult> Pay([FromBody] PayRequest request) { return Ok(); }
}
public record PayRequest(int OrderId, decimal Amount);
public record PayResult(int Status, string Message);""",
        ),
        SourceFile(
            "Domain/PaymentService.cs",
            "public class PaymentService { public PayResult Pay(PayRequest r) { return null; } }",
        ),
    ]
    found = inventory(files)
    (endpoint,) = found.endpoints
    assert (found.stack, endpoint.method, endpoint.path) == ("aspnet-core", "POST", "/api/payments/pay")
    assert [f.name for f in endpoint.request] == ["OrderId", "Amount"]
    assert [s.unit for s in found.slices] == ["PaymentService.Pay"]


def test_the_vendor_mapping_fits_and_a_proposal_lists_what_is_missing() -> None:
    files, master = archive(), golden()
    found = target_inventory(files)
    vendor = ivv_mapping.load(files["ivv-mapping.yaml"].decode("utf-8"))
    assert ivv_mapping.problems(vendor, master, found) == []
    broken = vendor.model_copy(deep=True)
    broken.programs[0].request.pop("channel")
    assert ivv_mapping.problems(broken, master, found) == ["The legacy parameter @i_canal goes to no request field"]
    proposal, gaps = ivv_mapping.propose(master, found)
    assert proposal.programs[0].endpoint.path == "/api/v1/payments"
    assert proposal.programs[0].response.returns == "status"
    assert "How does the target call the external program db_cuentas..sp_debito? (or mask it)" in gaps
    assert ivv_mapping.load(ivv_mapping.dump(vendor)) == vendor


def _image_available() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


@pytest.fixture(scope="module")
def java_sandbox() -> DockerSandbox:
    box = DockerSandbox(image=IMAGE)
    if not asyncio.run(box.available()) or not _image_available():
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    return box


def test_the_correct_target_reproduces_every_golden_case(java_sandbox: DockerSandbox) -> None:
    files, master = archive(), golden()
    found = target_inventory(files)
    result = asyncio.run(run(java_sandbox, files, found, ivv_mapping.load(files["ivv-mapping.yaml"].decode()), master))
    assert result.ready, result.diagnostic
    assert result.matched == len(master.results) == 12, [(c.name, c.differences, c.error) for c in result.cases]


def test_a_target_with_a_changed_rule_fails_its_cases(java_sandbox: DockerSandbox) -> None:
    files = archive({SERVICE: ('new BigDecimal("100.00")', 'new BigDecimal("50.00")')})
    master = golden()
    result = asyncio.run(run(java_sandbox, files, target_inventory(files),
                             ivv_mapping.load(files["ivv-mapping.yaml"].decode()), master))  # fmt: skip
    failed = {c.name for c in result.cases if not c.matched}
    assert "current_account_overdraws_up_to_100" in failed
    assert result.matched < len(master.results)


def test_the_stored_inventory_reads_back_the_same() -> None:
    import json
    from dataclasses import asdict

    found = target_inventory(archive())
    assert TargetInventory.from_dict(json.loads(json.dumps(asdict(found), default=list))) == found


def test_codes_with_leading_zeros_are_compared_as_text() -> None:
    from nexti_ivv.runner import _like

    assert _like("0012345678", "0012345678") == "0012345678"
    assert _like("7001", 7001.0) == "7001"
    assert _like("2.0000", "2") == "2.0000"
