"""Signed update bundle for air-gapped installations (ADR-0030, guide: docs/guias/air-gapped.md).

Run with the workspace Python (the logic lives in nexti_core.update_bundle, which the tests
cover; only this script starts docker and helm):

    .venv/Scripts/python scripts/airgap/bundle.py build --key nexti-license.key --out nexti-0.9.0.tar
    .venv/Scripts/python scripts/airgap/bundle.py verify --public-key nexti-license.pub nexti-0.9.0.tar
    .venv/Scripts/python scripts/airgap/bundle.py load --public-key nexti-license.pub nexti-0.9.0.tar \
        --registry registry.local:5000 --push
"""

import subprocess  # fixed docker/helm commands with argument lists, never a shell
import sys
from collections.abc import Sequence

from nexti_core.update_bundle import CommandError, main


def run(args: Sequence[str]) -> str:
    done = subprocess.run(list(args), capture_output=True, text=True, check=False)  # noqa: S603
    if done.returncode != 0:
        raise CommandError(f"{' '.join(args)} (exit {done.returncode}): {done.stderr.strip()[-500:]}")
    return done.stdout


if __name__ == "__main__":
    sys.exit(main(run))
