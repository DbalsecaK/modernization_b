"""A reference kit (ADR-0011): a local folder outside the repository, pointed to by `NEXTI_REFERENCE_DIR`, with one
folder per application:

    <app>/kit.json                  {"name": "...", "program": "dbo.sp_x", "written_blind": false}
    <app>/source/...                the legacy code
    <app>/reference_spec.json       the reference spec (spec model of rules), or
    <app>/BUSINESS_RULES.md         the reference spec as rule cards
    <app>/characterization.json     optional: a characterization suite

Nothing of a kit is copied into the repository, fixtures, logs or captures: evaluations keep its name and hash."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from nexti_core.adapters import SourceFile
from nexti_core.spec.characterization import Suite
from nexti_verification.evaluation import Reference, load_reference

ENVIRONMENT = "NEXTI_REFERENCE_DIR"
SPEC_FILES = ("reference_spec.json", "BUSINESS_RULES.md")
MAX_SOURCE_BYTES = 5 * 1024 * 1024


class KitError(ValueError):
    """The folder is not a reference kit."""


@dataclass(frozen=True)
class Kit:
    name: str
    program: str | None
    reference: Reference
    sources: list[SourceFile]
    suite: Suite | None


def kits_root() -> Path | None:
    value = os.environ.get(ENVIRONMENT, "").strip()
    return Path(value) if value else None


def load_kit(folder: Path) -> Kit:
    manifest_path = folder / "kit.json"
    if not manifest_path.is_file():
        raise KitError(f"{folder.name}: kit.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    spec = next((folder / name for name in SPEC_FILES if (folder / name).is_file()), None)
    if spec is None:
        raise KitError(f"{folder.name}: no reference spec ({' or '.join(SPEC_FILES)})")
    name = str(manifest.get("name") or folder.name)
    reference = load_reference(spec, name, bool(manifest.get("written_blind", True)))
    sources = []
    total = 0
    for path in sorted((folder / "source").rglob("*")) if (folder / "source").is_dir() else []:
        if path.is_file():
            total += path.stat().st_size
            if total > MAX_SOURCE_BYTES:
                raise KitError(f"{folder.name}: the source is larger than {MAX_SOURCE_BYTES} bytes")
            text = path.read_bytes().decode("utf-8", errors="replace")
            sources.append(SourceFile(path.relative_to(folder / "source").as_posix(), text))
    suite_path = folder / "characterization.json"
    suite = Suite.model_validate_json(suite_path.read_text(encoding="utf-8")) if suite_path.is_file() else None
    return Kit(name, manifest.get("program"), reference, sources, suite)
