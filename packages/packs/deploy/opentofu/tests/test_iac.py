# ruff: noqa: E501 - the HCL lines are replaced as OpenTofu formats them
"""The deployment pack (spec 8.4, ADR-0021): the IaC of the fictitious application for AWS and Azure, with each
database engine, validates in the sandbox without network or credentials and meets the fitness functions; a break of
each function is caught. Sandbox tests skip without Docker or the image nexti-sandbox-iac:1."""

import asyncio
import subprocess
from pathlib import Path

import pytest

from nexti_core.spec.design import Design
from nexti_pack_iac import IMAGE, generate, verdict
from nexti_pack_iac.fitness import checks
from nexti_sandbox import DockerSandbox

ROOT = Path(__file__).resolve().parents[3]
DESIGN = Design.model_validate_json(
    (ROOT / "target/spring_boot/tests/fixtures/pago_orden/design.json").read_text(encoding="utf-8")
)
TARGETS = [("aws", "oracle"), ("aws", "postgresql"), ("azure", "oracle"), ("azure", "postgresql"),
           ("azure", "sqlserver")]  # fmt: skip


def hcl(cloud: str, database: str) -> str:
    files = generate(DESIGN, {"cloud": cloud, "database": database})
    return "\n".join(c for p, c in sorted(files.items()) if p.endswith(".tf"))


def test_the_iac_follows_the_design_and_the_target() -> None:
    files = generate(DESIGN, {"cloud": "aws", "database": "oracle"})
    assert set(files) == {"infra/aws/main.tf", "infra/aws/variables.tf", "infra/aws/outputs.tf", "infra/aws/README.md"}
    main = files["infra/aws/main.tf"]
    assert 'engine                    = "oracle-se2"' in main
    assert 'name = "payments"' in main
    readme = files["infra/aws/README.md"]
    assert "| Table db_pagos..pg_orden | Table payment_order in Amazon RDS (oracle) |" in readme
    assert "dbo.sp_pago_orden" in readme
    assert generate(DESIGN, {"cloud": "gcp"}) == {}  # no generator yet: nothing, never another cloud


@pytest.mark.parametrize(("cloud", "database"), TARGETS)
def test_the_generated_iac_meets_the_fitness_functions(cloud: str, database: str) -> None:
    found = {c.key: c for c in checks(hcl(cloud, database))}
    assert {k: c.status for k, c in found.items()} == dict.fromkeys(
        ("encryption_at_rest", "db_not_public", "no_secrets_in_code", "tags", "logs"), "passed"), found  # fmt: skip


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


@pytest.mark.parametrize(("cloud", "database"), TARGETS)
def test_the_iac_validates_in_the_sandbox_without_credentials(iac_sandbox: DockerSandbox, cloud: str,
                                                              database: str) -> None:  # fmt: skip
    result = asyncio.run(verdict(iac_sandbox, generate(DESIGN, {"cloud": cloud, "database": database}), cloud))
    assert result.module == f"iac-{cloud}"
    assert result.verdict == "PROVEN", [(c.key, c.detail) for c in result.checks if c.status != "passed"]


def test_an_invalid_iac_is_not_proven(iac_sandbox: DockerSandbox) -> None:
    files = generate(DESIGN, {"cloud": "aws", "database": "postgresql"})
    files["infra/aws/main.tf"] = files["infra/aws/main.tf"].replace('  engine                    = "postgres"\n',
                                                                    '  engine_typo               = "postgres"\n')  # fmt: skip
    result = asyncio.run(verdict(iac_sandbox, files, "aws"))
    assert result.verdict == "NOT PROVEN"
    assert next(c for c in result.checks if c.key == "validates").status == "failed"
