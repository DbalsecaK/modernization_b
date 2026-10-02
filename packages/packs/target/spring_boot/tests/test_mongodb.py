"""MongoDB as the persistence of the Spring Boot pack (spec 8.4, 8.5, ADR-0029): the aggregate model decided by code
(one collection per entity, nothing embedded, references by key), neutral types map to BSON, legacy rows become
documents and come back as the same rows, and the hand-written reference target of the fictitious application (the
Spring Boot core with MongoDB adapters over the official sync driver) passes its tests and reproduces the 12 cases
Sybase recorded, compared collection by collection against a single-node replica set inside the sandbox with its
default hardening (no network, read-only root, user nobody); the canary is caught. Sandbox tests skip without Docker
or the image nexti-sandbox-java-mongodb:1 (infra/sandbox/java-mongodb)."""

import asyncio
import subprocess
from pathlib import Path

import pytest

from nexti_adapter_sybase.ase import RecordedRunner
from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import GoldenMaster, Suite, canonical
from nexti_core.spec.equivalence import column_of
from nexti_pack_spring_boot import Design
from nexti_pack_spring_boot.equivalence import harness_source
from nexti_pack_spring_boot.mongodb import (
    COLLECTIONS,
    IMAGE,
    MONGODB_LIMITS,
    aggregate_decision,
    aggregates,
    bson_type,
    bson_value,
    collections_script,
    document,
    mongodb_plan,
    row,
    tables,
    target_case,
    text_value,
    validator,
)
from nexti_pack_spring_boot.pack import MONGODB_PACK, PACK, SCHEMA
from nexti_sandbox import DockerSandbox

HERE = Path(__file__).parent / "fixtures" / "pago_orden"
LEGACY = Path(__file__).resolve().parents[4] / "adapters/source/sybase/tests/fixtures/pago_orden"
DESIGN = Design.model_validate_json((HERE / "design.json").read_text(encoding="utf-8"))
PAY = DESIGN.use_cases[0]
SUITE = Suite.model_validate_json((LEGACY / "characterization.json").read_text(encoding="utf-8"))
SOURCE = [SourceFile("sp/sp_pago_orden.sp", (LEGACY / "sp_pago_orden.sp").read_text(encoding="utf-8"))]
MASTER: GoldenMaster = asyncio.run(RecordedRunner(LEGACY / "golden", "replay").run(SOURCE, SUITE))
BASE = "src/main/java/com/bancoficticio/payments"


@pytest.mark.parametrize(
    ("neutral", "bson"),
    [
        ("decimal(19,4,signed)", "decimal"),
        ("integer(8,signed)", "int"),
        ("integer(16,signed)", "int"),
        ("integer(32,signed)", "int"),
        ("integer(32,unsigned)", "long"),
        ("integer(64,signed)", "long"),
        ("text(fixed,3,iso8859-1)", "string"),
        ("text(var,max,utf8)", "string"),
        ("enum(CTE|AHO|VIR)", "string"),
        ("date(yyyy-MM-dd)", "date"),
        ("timestamp(local)", "date"),
        ("timestamp(tz)", "date"),
        ("boolean", "bool"),
        ("binary(16)", "binData"),
    ],
)
def test_neutral_types_map_to_bson(neutral: str, bson: str) -> None:
    assert bson_type(neutral) == bson


def test_each_entity_is_a_collection_nothing_is_embedded_and_references_go_by_key() -> None:
    found = {a.entity: a for a in aggregates(DESIGN)}
    assert {a.collection for a in found.values()} == {"payment_order", "company_tariff", "account", "service_tariff"}
    assert all(a.embedded == () for a in found.values())
    assert found["PaymentOrder"].key == ("order_number", "company")
    assert found["Tariff"].references == ((("service",), "service_tariff"),)
    assert found["Account"].references == ()
    decision = aggregate_decision(DESIGN)
    assert "none is embedded" in decision.decision
    assert "Tariff is the collection company_tariff, unique key (company, service); refers to service_tariff by " \
           "service" in decision.decision  # fmt: skip
    script = collections_script(DESIGN)
    assert script.startswith("// MongoDB collections of the payments context")
    assert f"// {decision.title}." in script
    assert 'db.getCollection("payment_order").createIndex({"order_number": 1, "company": 1}, {unique: true, ' \
           'name: "payment_order_key"});' in script  # fmt: skip
    assert aggregates(DESIGN) == aggregates(DESIGN)  # deterministic


def test_the_collections_validate_types_lengths_and_keys() -> None:
    account = next(e for e in DESIGN.entities if e.name == "Account")
    schema = validator(account)["$jsonSchema"]
    assert schema["required"] == ["number", "type"]
    assert schema["properties"]["number"] == {"bsonType": "string", "maxLength": 10}
    assert schema["properties"]["balance"] == {"bsonType": ["decimal", "null"]}
    data = DESIGN.model_dump(mode="json")
    data["entities"][2]["fields"][1]["type"] = "enum(CTE|AHO|VIR)"
    data["entities"][2]["key"] = ["number"]
    changed = validator(Design.model_validate(data).entities[2])["$jsonSchema"]
    assert changed["properties"]["type"] == {"bsonType": ["string", "null"], "enum": ["CTE", "AHO", "VIR", None]}


@pytest.mark.parametrize(
    ("neutral", "text", "extended"),
    [
        ("decimal(19,4,signed)", "0.6300", {"$numberDecimal": "0.6300"}),
        ("integer(32,signed)", "-7", {"$numberInt": "-7"}),
        ("integer(64,signed)", "9000000000", {"$numberLong": "9000000000"}),
        ("text(var,10,iso8859-1)", "NOMINA", "NOMINA"),
        ("boolean", "true", True),
        ("date(yyyy-MM-dd)", "2024-03-15", {"$date": {"$numberLong": "1710460800000"}}),
        ("timestamp(local)", "2024-03-15T10:30:00.250", {"$date": {"$numberLong": "1710498600250"}}),
        ("timestamp(tz)", "2024-03-15T10:30:00.250+00:00", {"$date": {"$numberLong": "1710498600250"}}),
        ("binary(4)", "cafe0001", {"$binary": {"base64": "yv4AAQ==", "subType": "00"}}),
        ("decimal(19,4,signed)", None, None),
    ],
)
def test_a_value_goes_to_extended_json_and_back(neutral: str, text: str | None, extended: object) -> None:
    assert bson_value(neutral, text) == extended
    assert text_value(neutral, extended) == text


def test_a_value_read_back_takes_the_canonical_text_of_its_type() -> None:
    assert text_value("decimal(19,4,signed)", {"$numberDecimal": "0.63"}) == "0.6300"
    assert text_value("integer(32,signed)", 5) == "5"
    assert text_value("timestamp(local)", {"$date": "2024-03-15T10:30:00Z"}) == "2024-03-15T10:30:00.000"
    assert text_value("text(var,10,iso8859-1)", {"service": "X"}) == '{"service": "X"}'  # embedded: never a scalar


def test_every_legacy_row_becomes_a_document_and_comes_back_as_the_same_row() -> None:
    entities = {e.legacy_table.lower(): e for e in DESIGN.entities if e.legacy_table}
    checked = 0
    for result in MASTER.results:
        for table, rows in result.case.setup.items():
            entity = entities[table.lower()]
            by_legacy = {(f.legacy or "").lower(): f for f in entity.fields}
            for legacy in rows:
                values = {column_of(by_legacy[c.lower()].name, by_legacy[c.lower()].column):
                          canonical(by_legacy[c.lower()].type, v) for c, v in legacy.items()}  # fmt: skip
                back = row(entity, document(entity, values))
                assert {c: v for c, v in back.items() if c in values} == values
                checked += 1
    assert checked > 12
    case = next(r.case for r in MASTER.results if r.case.name == "separate_commission_is_a_second_debit")
    setup = target_case(DESIGN, PAY, case)["setup"]
    tariff = next(s for s in setup if s["collection"] == "company_tariff")
    assert tariff["document"]["separate"] is True
    assert tariff["document"]["amount"]["$numberDecimal"].count(".") == 1
    assert all(isinstance(s["document"], dict) and "_id" not in s["document"] for s in setup)
    printed = {"account": [{"number": "1", "type": "CTE", "balance": {"$numberDecimal": "5.5"}}], "other": []}
    assert tables(DESIGN, printed) == {"account": [{"number": "1", "type": "CTE", "balance": "5.5000"}]}


def test_the_skeleton_swaps_the_schema_and_the_driver_and_asks_for_mongodb_adapters() -> None:
    files = MONGODB_PACK.skeleton(DESIGN)
    assert SCHEMA not in files
    assert files[COLLECTIONS] == collections_script(DESIGN)
    pom = files["pom.xml"]
    assert "<artifactId>mongodb-driver-sync</artifactId>" in pom
    assert "postgresql" not in pom
    assert "spring-boot-starter-jdbc" not in pom
    assert f"{BASE}/adapters/out/mongodb/MongoTransaction.java" in files
    assert "MONGODB_URI" in files[f"{BASE}/config/MongoConfig.java"]
    core = [p for p in PACK.skeleton(DESIGN) if "/domain/" in p or p.endswith(("Request.java", "Response.java"))]
    assert all(files[p] == PACK.skeleton(DESIGN)[p] for p in core)
    port = DESIGN.ports[2]
    assert MONGODB_PACK.adapter_path(DESIGN, port) == f"{BASE}/adapters/out/mongodb/MongoAccountRepository.java"
    assert MONGODB_PACK.adapter_name("AccountRepository") == "MongoAccountRepository"
    assert MONGODB_PACK.layer_of(COLLECTIONS, DESIGN) == "adapters"
    request = MONGODB_PACK.adapter_request(DESIGN, "AccountRepository", files)
    for words in ("MongoCollection", "Decimal128", "java.util.Date in UTC", "MongoTransaction.current()",
                  'db.createCollection("account"'):  # fmt: skip
        assert words in request
    assert MONGODB_PACK.describe() == {"name": "spring-boot", "image": IMAGE, "database": "mongodb"}
    harness = mongodb_plan(DESIGN, PAY)
    assert harness["uri"].startswith("mongodb://127.0.0.1:27017/?replicaSet=rs0")
    assert harness["ports"][2]["adapter"] == "com.bancoficticio.payments.adapters.out.mongodb.MongoAccountRepository"
    assert harness["ports"][3]["adapter"] is None  # the external program: a fake
    assert "org.springframework" not in harness_source("mongodb")
    assert "replSetInitiate" in harness_source("mongodb")


def test_mongodb_keeps_the_default_hardening_of_the_sandbox() -> None:
    assert not MONGODB_LIMITS.internal_network
    assert not MONGODB_LIMITS.writable_root
    assert MONGODB_LIMITS.user is None


def reference_project(design: Design) -> dict[str, str]:
    files = MONGODB_PACK.skeleton(design)
    files[MONGODB_PACK.service_path(design, PAY)] = (HERE / "PayOrderService.java").read_text(encoding="utf-8")
    files[MONGODB_PACK.test_path(design, PAY)] = (HERE / "PayOrderServiceTest.java").read_text(encoding="utf-8")
    for port in design.ports:
        reference = HERE / "mongodb" / f"Mongo{port.name}.java"
        if reference.exists():
            files[MONGODB_PACK.adapter_path(design, port)] = reference.read_text(encoding="utf-8")
    return files


def _image_available() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


@pytest.fixture(scope="module")
def mongodb_sandbox() -> DockerSandbox:
    box = DockerSandbox(image=IMAGE)
    if not asyncio.run(box.available()) or not _image_available():
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    return box


def test_a_jdbc_adapter_does_not_compile_in_the_mongodb_sandbox(mongodb_sandbox: DockerSandbox) -> None:
    files = reference_project(DESIGN)
    files[f"{BASE}/adapters/out/jdbc/JdbcAccountRepository.java"] = (HERE / "JdbcAccountRepository.java").read_text(
        encoding="utf-8"
    )
    build = asyncio.run(MONGODB_PACK.compile_and_test(mongodb_sandbox, files, run_tests=False))
    assert not build.compiled
    assert "JdbcAccountRepository.java" in build.compile_errors


def test_the_reference_target_reproduces_the_golden_master_on_mongodb(mongodb_sandbox: DockerSandbox) -> None:
    run = asyncio.run(MONGODB_PACK.run_equivalence(mongodb_sandbox, reference_project(DESIGN), DESIGN, PAY, MASTER))
    assert run.problem is None, run.problem
    assert (run.build.passed, run.build.failed) == (7, 0)
    different = {c.name: (c.failure, c.expected, c.actual) for c in run.cases if c.failure or c.expected != c.actual}
    assert len(run.cases) == 12
    assert different == {}


def test_the_canary_is_caught(mongodb_sandbox: DockerSandbox) -> None:
    files = reference_project(DESIGN)
    target = MONGODB_PACK.service_path(DESIGN, PAY)
    mutation = MONGODB_PACK.mutations(files[target])[0]
    run = asyncio.run(
        MONGODB_PACK.run_equivalence(mongodb_sandbox, {**files, target: mutation.source}, DESIGN, PAY, MASTER)
    )
    assert run.problem is None, run.problem
    differs = [c.name for c in run.cases if c.failure or c.expected != c.actual]
    assert run.build.failed > 0 or differs


def test_a_decimal_written_as_a_double_is_refused_by_the_collection(mongodb_sandbox: DockerSandbox) -> None:
    files = reference_project(DESIGN)
    path = MONGODB_PACK.adapter_path(DESIGN, DESIGN.ports[0])
    files[path] = files[path].replace("new Decimal128(commission.setScale(4, RoundingMode.HALF_UP))",
                                      "commission.doubleValue()")  # fmt: skip
    run = asyncio.run(MONGODB_PACK.run_equivalence(mongodb_sandbox, files, DESIGN, PAY, MASTER))
    assert run.problem is None, run.problem
    failures = [c.failure for c in run.cases if c.failure]
    assert failures
    assert all("validation" in (f or "").lower() for f in failures), failures
