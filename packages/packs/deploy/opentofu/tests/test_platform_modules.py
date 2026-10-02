"""The platform's own modules (infra/terraform, ADR-0024) meet the same fitness functions as the IaC the platform
generates for its customers, and validate in the sandbox without credentials. Sandbox tests skip without Docker or the
image nexti-sandbox-iac:2."""

import asyncio
import subprocess
from pathlib import Path

import pytest

from nexti_pack_iac import IMAGE, validate
from nexti_pack_iac.fitness import checks
from nexti_sandbox import DockerSandbox

MODULES = Path(__file__).resolve().parents[5] / "infra" / "terraform"
CLOUDS = ("aws", "azure")


def module(cloud: str) -> dict[str, str]:
    return {f"infra/{cloud}/{p.name}": p.read_text(encoding="utf-8") for p in sorted((MODULES / cloud).glob("*.tf"))}


@pytest.mark.parametrize("cloud", CLOUDS)
def test_the_platform_module_meets_the_fitness_functions(cloud: str) -> None:
    files = module(cloud)
    assert {"main.tf", "variables.tf", "outputs.tf"} <= {p.rsplit("/", 1)[1] for p in files}
    found = {c.key: c for c in checks("\n".join(files.values()))}
    assert {k: c.status for k, c in found.items()} == dict.fromkeys(
        ("encryption_at_rest", "db_not_public", "no_secrets_in_code", "tags", "logs"), "passed"), found  # fmt: skip


def _image_available() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


@pytest.mark.parametrize("cloud", CLOUDS)
def test_the_platform_module_validates_without_credentials(cloud: str) -> None:
    box = DockerSandbox(image=IMAGE)
    if not asyncio.run(box.available()) or not _image_available():
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    result = asyncio.run(validate(box, module(cloud)))
    assert result.status == "passed", result.detail
