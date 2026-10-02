# ruff: noqa: E501 - the HCL lines are replaced as OpenTofu formats them
"""The deployment pack (spec 8.4, ADR-0021, ADR-0027): the IaC of the fictitious application for AWS, Azure and GCP,
with each database engine and as containers or serverless, validates in the sandbox without network or credentials
and meets the fitness functions; a break of each function is caught. Sandbox tests skip without Docker or the image
nexti-sandbox-iac:2."""

import asyncio
import subprocess
from pathlib import Path

import pytest

from nexti_core.spec.design import Design
from nexti_pack_iac import IMAGE, generate, unsupported, verdict
from nexti_pack_iac.fitness import checks
from nexti_sandbox import DockerSandbox

ROOT = Path(__file__).resolve().parents[3]
DESIGN = Design.model_validate_json(
    (ROOT / "target/spring_boot/tests/fixtures/pago_orden/design.json").read_text(encoding="utf-8")
)
# (cloud, database, architecture): every engine of each cloud, and the serverless form of each cloud.
TARGETS = [("aws", "oracle", ""), ("aws", "postgresql", ""), ("aws", "mysql", ""), ("azure", "oracle", ""),
           ("azure", "postgresql", ""), ("azure", "sqlserver", ""), ("azure", "mysql", ""), ("gcp", "postgresql", ""),
           ("gcp", "mysql", ""), ("gcp", "sqlserver", ""), ("aws", "postgresql", "serverless"),
           ("azure", "mysql", "serverless"), ("gcp", "postgresql", "serverless"), ("aws", "mongodb", ""),
           ("azure", "mongodb", "")]  # fmt: skip
FUNCTIONS = ("encryption_at_rest", "db_not_public", "no_secrets_in_code", "tags", "logs")


def target(cloud: str, database: str, architecture: str = "") -> dict[str, str]:
    return {"cloud": cloud, "database": database, "architecture": architecture}


def hcl(cloud: str, database: str, architecture: str = "") -> str:
    files = generate(DESIGN, target(cloud, database, architecture))
    return "\n".join(c for p, c in sorted(files.items()) if p.endswith(".tf"))


def status(found: str) -> dict[str, str]:
    return {c.key: c.status for c in checks(found)}


def test_the_iac_follows_the_design_and_the_target() -> None:
    files = generate(DESIGN, {"cloud": "aws", "database": "oracle"})
    assert set(files) == {"infra/aws/main.tf", "infra/aws/variables.tf", "infra/aws/outputs.tf", "infra/aws/README.md"}
    main = files["infra/aws/main.tf"]
    assert 'engine                    = "oracle-se2"' in main
    assert 'name = "payments"' in main
    readme = files["infra/aws/README.md"]
    assert "| Table db_pagos..pg_orden | Table payment_order in Amazon RDS (oracle) |" in readme
    assert "dbo.sp_pago_orden" in readme
    assert generate(DESIGN, {"cloud": "kubernetes"}) == {}  # no generator yet: nothing, never another cloud


def test_gcp_runs_on_cloud_run_with_cloud_sql_private_and_labels() -> None:
    files = generate(DESIGN, {"cloud": "gcp", "database": "mysql"})
    assert set(files) == {"infra/gcp/main.tf", "infra/gcp/variables.tf", "infra/gcp/outputs.tf", "infra/gcp/README.md"}
    main = files["infra/gcp/main.tf"]
    assert 'database_version    = "MYSQL_8_4"' in main
    assert "ipv4_enabled    = false" in main
    assert "default_labels = local.labels" in main
    assert "min_instance_count = 1" in main
    assert "| Table db_pagos..pg_orden | Table payment_order in Cloud SQL (mysql) |" in files["infra/gcp/README.md"]
    assert 'database_version    = "POSTGRES_16"' in hcl("gcp", "postgresql")


def test_a_database_the_cloud_does_not_support_gets_no_iac_and_a_reason() -> None:
    assert generate(DESIGN, {"cloud": "gcp", "database": "oracle"}) == {}
    reason = "No IaC: the oracle database is not supported on GCP by the deployment pack"
    assert unsupported({"cloud": "gcp", "database": "oracle"}) == reason
    assert unsupported({"cloud": "gcp", "database": "mysql"}) == unsupported({"backend": "spring-boot"}) == ""


def test_serverless_is_lambda_on_aws_and_scale_to_zero_on_azure_and_gcp() -> None:
    files = generate(DESIGN, target("aws", "postgresql", "serverless"))
    main = files["infra/aws/main.tf"]
    assert 'resource "aws_lambda_function" "app"' in main
    assert 'resource "aws_apigatewayv2_api" "main"' in main
    assert "aws_ecs_service" not in main
    assert "aws_lb" not in main
    assert "subnet_ids         = aws_subnet.private[*].id" in main
    assert "publicly_accessible       = false" in main
    assert "certificate_arn" not in files["infra/aws/variables.tf"]
    assert "## Serverless" in files["infra/aws/README.md"]
    assert "AWS Lambda" in files["infra/aws/README.md"]
    assert "min_replicas = 0" in hcl("azure", "postgresql", "serverless")
    assert "min_replicas = 1" in hcl("azure", "postgresql")
    assert "min_instance_count = 0" in hcl("gcp", "postgresql", "serverless")
    assert "## Serverless" not in generate(DESIGN, target("gcp", "postgresql"))["infra/gcp/README.md"]


def test_azure_mysql_is_a_flexible_server_with_private_access() -> None:
    main = hcl("azure", "mysql")
    assert 'resource "azurerm_mysql_flexible_server" "main"' in main
    assert 'name = "Microsoft.DBforMySQL/flexibleServers"' in main
    assert ".mysql.database.azure.com" in main
    assert "delegated_subnet_id    = azurerm_subnet.db.id" in main


def test_mongodb_is_documentdb_on_aws_and_cosmos_db_on_azure() -> None:
    files = generate(DESIGN, target("aws", "mongodb"))
    main = files["infra/aws/main.tf"]
    assert 'resource "aws_docdb_cluster" "main"' in main
    assert 'resource "aws_docdb_cluster_instance" "main"' in main
    assert "aws_db_instance" not in main
    assert "storage_encrypted               = true" in main
    assert "db_subnet_group_name            = aws_docdb_subnet_group.main.name" in main
    assert "master_password                 = random_password.db.result" in main
    assert 'enabled_cloudwatch_logs_exports = ["audit", "profiler"]' in main
    assert "from_port       = 27017" in main
    assert 'DB_HOST", value = aws_docdb_cluster.main.endpoint' in main
    assert "value = aws_docdb_cluster.main.endpoint" in files["infra/aws/outputs.tf"]
    readme = files["infra/aws/README.md"]
    assert "| Table db_pagos..pg_orden | Collection payment_order in Amazon DocumentDB (mongodb) |" in readme
    azure = generate(DESIGN, target("azure", "mongodb"))
    main = azure["infra/azure/main.tf"]
    assert 'kind                          = "MongoDB"' in main
    assert "public_network_access_enabled = false" in main
    assert 'subresource_names              = ["MongoDB"]' in main
    assert 'resource "azurerm_cosmosdb_mongo_database" "main"' in main
    assert "value        = azurerm_cosmosdb_account.main.primary_mongodb_connection_string" in main
    assert "random_password" not in main
    assert "target_resource_id         = azurerm_cosmosdb_account.main.id" in main
    assert "Collection payment_order in Azure Cosmos DB for MongoDB (mongodb)" in azure["infra/azure/README.md"]


def test_gcp_has_no_mongodb_iac_and_says_why() -> None:
    assert generate(DESIGN, target("gcp", "mongodb")) == {}
    reason = unsupported({"cloud": "gcp", "database": "mongodb"})
    assert reason.startswith("No IaC: the mongodb database is not supported on GCP by the deployment pack: ")
    assert "no managed MongoDB-compatible service" in reason
    assert (
        unsupported({"cloud": "aws", "database": "mongodb"})
        == unsupported({"cloud": "azure", "database": "mongodb"})
        == ""
    )


def test_each_fitness_function_catches_its_break_on_documentdb_and_cosmos_db() -> None:
    docdb = hcl("aws", "mongodb")
    assert status(docdb.replace("storage_encrypted               = true", "storage_encrypted               = false")
                  )["encryption_at_rest"] == "failed"  # fmt: skip
    private = "  db_subnet_group_name            = aws_docdb_subnet_group.main.name\n"
    assert status(docdb.replace(private, ""))["db_not_public"] == "failed"
    literal = docdb.replace("master_password                 = random_password.db.result",
                            'master_password                 = "P4ssw0rd!"')  # fmt: skip
    assert status(literal)["no_secrets_in_code"] == "failed"
    no_exports = {c.key: c for c in checks(docdb.replace("  enabled_cloudwatch_logs_exports", "  other_exports"))}
    assert no_exports["logs"].status == "failed"
    assert "aws_docdb_cluster.main" in no_exports["logs"].detail
    cosmos = hcl("azure", "mongodb")
    public = cosmos.replace("public_network_access_enabled = false", "public_network_access_enabled = true")
    assert status(public)["db_not_public"] == "failed"
    undiagnosed = {c.key: c for c in checks(cosmos.replace("target_resource_id         = azurerm_cosmosdb_account",
                                                           "target_resource_id         = azurerm_other"))}  # fmt: skip
    assert undiagnosed["logs"].status == "failed"
    assert "azurerm_cosmosdb_account.main has no diagnostic setting" in undiagnosed["logs"].detail
    untagged = {c.key: c for c in checks(cosmos.replace('  tags                          = local.tags\n  capabilities {',
                                                        "  capabilities {"))}  # fmt: skip
    assert untagged["tags"].status == "failed"
    assert "azurerm_cosmosdb_account.main" in untagged["tags"].detail
    found = {c.key: c for c in checks(cosmos)}
    assert "Azure encrypts its managed databases" in found["encryption_at_rest"].detail


@pytest.mark.parametrize(("cloud", "database", "architecture"), TARGETS)
def test_the_generated_iac_meets_the_fitness_functions(cloud: str, database: str, architecture: str) -> None:
    found = {c.key: c for c in checks(hcl(cloud, database, architecture))}
    assert {k: c.status for k, c in found.items()} == dict.fromkeys(FUNCTIONS, "passed"), found


def test_each_fitness_function_catches_its_break() -> None:
    broken = (hcl("aws", "postgresql")
              .replace("storage_encrypted         = true", "storage_encrypted         = false")
              .replace("publicly_accessible       = false", "publicly_accessible       = true")
              .replace("password                  = random_password.db.result", 'password                  = "P4ssw0rd!"')
              .replace("  default_tags {", "  other {")
              .replace("retention_in_days = 30", "skip = true"))  # fmt: skip
    found = {c.key: c for c in checks(broken)}
    assert {k: c.status for k, c in found.items()} == dict.fromkeys(found, "failed"), found
    assert "aws_db_instance.main" in found["db_not_public"].detail
    untagged = checks(hcl("azure", "postgresql").replace("  tags                       = local.tags\n", "", 1))
    assert next(c for c in untagged if c.key == "tags").status == "failed"


def test_each_gcp_fitness_function_catches_its_break() -> None:
    sound = hcl("gcp", "postgresql")
    assert status(sound.replace("ipv4_enabled    = false", "ipv4_enabled    = true"))["db_not_public"] == "failed"
    no_vpc = sound.replace("      private_network = google_compute_network.main.id\n", "")
    assert status(no_vpc)["db_not_public"] == "failed"
    literal = sound.replace("password = random_password.db.result", 'password = "P4ssw0rd!"')
    assert status(literal)["no_secrets_in_code"] == "failed"
    literal = sound.replace("secret_data = random_password.db.result", 'secret_data = "P4ssw0rd!"')
    assert status(literal)["no_secrets_in_code"] == "failed"
    assert status(sound.replace("  default_labels = local.labels\n", ""))["tags"] == "failed"
    assert status(sound.replace("    user_labels       = local.labels\n", ""))["tags"] == "failed"
    assert status(sound.replace("retention_days = 30", "skip = true"))["logs"] == "failed"
    no_sink = sound.replace('resource "google_logging_project_sink"', 'resource "google_other"')
    assert status(no_sink)["logs"] == "failed"
    found = {c.key: c for c in checks(sound)}
    assert "GCP encrypts Cloud SQL" in found["encryption_at_rest"].detail


def test_a_lambda_without_its_log_group_breaks_the_logs_function() -> None:
    sound = hcl("aws", "postgresql", "serverless")
    found = {c.key: c for c in checks(sound.replace("  logging_config {", "  other_config {"))}
    assert found["logs"].status == "failed"
    assert "aws_lambda_function.app" in found["logs"].detail
    assert status(sound.replace("retention_in_days = 30", "skip = true", 1))["logs"] == "failed"


def _image_available() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


@pytest.fixture(scope="module")
def iac_sandbox() -> DockerSandbox:
    box = DockerSandbox(image=IMAGE)
    if not asyncio.run(box.available()) or not _image_available():
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    return box


@pytest.mark.parametrize(("cloud", "database", "architecture"), TARGETS)
def test_the_iac_validates_in_the_sandbox_without_credentials(iac_sandbox: DockerSandbox, cloud: str, database: str,
                                                              architecture: str) -> None:  # fmt: skip
    result = asyncio.run(verdict(iac_sandbox, generate(DESIGN, target(cloud, database, architecture)), cloud))
    assert result.module == f"iac-{cloud}"
    assert result.verdict == "PROVEN", [(c.key, c.detail) for c in result.checks if c.status != "passed"]


def test_an_invalid_iac_is_not_proven(iac_sandbox: DockerSandbox) -> None:
    files = generate(DESIGN, {"cloud": "aws", "database": "postgresql"})
    files["infra/aws/main.tf"] = files["infra/aws/main.tf"].replace('  engine                    = "postgres"\n',
                                                                    '  engine_typo               = "postgres"\n')  # fmt: skip
    result = asyncio.run(verdict(iac_sandbox, files, "aws"))
    assert result.verdict == "NOT PROVEN"
    assert next(c for c in result.checks if c.key == "validates").status == "failed"
