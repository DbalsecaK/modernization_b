"""The deterministic part of a frontend project (ADR-0016): the fixed files come from the pack's templates
(`templates/<pack>/`), with the screen registry, the start screen and the title filled in; the contract, the typed
client and the manifests are generated per project."""

import json
from collections.abc import Callable, Sequence
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Any

from nexti_pack_frontend.client import RUNTIME, runtime, typescript_client
from nexti_pack_frontend.contract import ScreenContract


def _walk(folder: Traversable, prefix: str = "") -> dict[str, str]:
    found: dict[str, str] = {}
    for item in folder.iterdir():
        path = f"{prefix}{item.name}"
        if item.is_dir():
            found.update(_walk(item, f"{path}/"))
        else:
            found[path] = item.read_text(encoding="utf-8")
    return found


def templates(pack: str) -> dict[str, str]:
    return _walk(resources.files("nexti_pack_frontend").joinpath("templates", pack))


def render(
    pack: str, contract: dict[str, Any], screens: Sequence[ScreenContract], title: str,
    import_line: Callable[[ScreenContract], str], manifests: dict[str, Any],
) -> dict[str, str]:  # fmt: skip
    values = {
        "{{START}}": screens[0].id if screens else "",
        "{{TITLE}}": title,
        "{{IMPORTS}}": "\n".join(import_line(s) for s in screens),
        "{{REGISTRY}}": "\n".join(f"  '{s.id}': {s.component}," for s in screens),
    }
    files = {}
    for path, text in templates(pack).items():
        for key, value in values.items():
            text = text.replace(key, value)
        files[path] = text
    files.update({name: json.dumps(value, indent=2) + "\n" for name, value in manifests.items()})
    files["openapi.json"] = json.dumps(contract, indent=2) + "\n"
    files[f"src/api/{RUNTIME}"] = runtime()
    files["src/api/client.ts"] = typescript_client(contract)
    return files


def project_name(title: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in title.lower()).strip("-") + "-web"
