import asyncio
import subprocess

import pytest

from nexti_pack_frontend import IMAGE
from nexti_sandbox import DockerSandbox


def _image() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


@pytest.fixture(scope="module")
def sandbox() -> DockerSandbox:
    """The frontend sandbox; the pack tests that need it are skipped without Docker or the image."""
    box = DockerSandbox(image=IMAGE)
    if not asyncio.run(box.available()) or not _image():
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    return box
