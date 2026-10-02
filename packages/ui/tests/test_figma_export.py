"""Export of the screens to Figma as a generated plugin (ADR-0030, plan M15 step 5): a valid development manifest, a
deterministic code.js that carries every screen, field, action and state and nothing that reaches the network, and,
run with node against a fake Figma API in the frontend sandbox, one frame per screen with its fields, actions and
states. The run is skipped without Docker or the image nexti-sandbox-frontend:2."""

import asyncio
import io
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest

from nexti_adapter_bms import BmsAdapter
from nexti_core.adapters import SourceFile
from nexti_core.spec.screens import ScreenSpec
from nexti_sandbox import DockerSandbox, Limits
from nexti_ui import base_tokens
from nexti_ui.figma_export import DEFAULT_MODULE, STATES, code_js, export_zip, manifest, plugin_data, styles

ROOT = Path(__file__).resolve().parents[3]
BMS = ROOT / "packages/adapters/source/bms/tests/fixtures/pagos/PAGOSET.bms"
HARNESS = Path(__file__).with_name("figma_harness.mjs")
IMAGE = "nexti-sandbox-frontend:2"
LIMITS = Limits(cpus=1.0, memory_mb=512, pids=64, timeout_seconds=60, work_mb=16, max_output_bytes=2 * 1024 * 1024)

LOGIN = ScreenSpec.model_validate({
    "id": "SCR-LOGIN",
    "name": "Sign in",
    "fields": [
        {"name": "USER", "kind": "input", "label": "User", "length": 8, "type": "text(var,8)", "required": True,
         "format": "X(8)", "validation": "not blank", "message": "ENTER THE USER"},
        {"name": "AMOUNT", "kind": "output", "label": "Balance", "length": 9, "type": "decimal(9,2)"},
    ],
    "actions": [{"key": "ENTER", "label": "Sign in"}, {"key": "PF3", "label": "Exit"}],
    "states": ["error", "loading"],
})  # fmt: skip


def screens() -> list[dict[str, Any]]:
    bms = BmsAdapter().screens([SourceFile("maps/PAGOSET.bms", BMS.read_text(encoding="utf-8"))])
    return [s.model_dump(mode="json") for s in [*bms, LOGIN]]


def unzip(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name).decode("utf-8") for name in archive.namelist()}


def test_the_zip_holds_a_valid_development_manifest_and_the_script() -> None:
    files = unzip(export_zip(screens()))
    assert list(files) == ["manifest.json", "code.js"]
    found = json.loads(files["manifest.json"])
    assert found == manifest()
    assert (found["api"], found["main"], found["editorType"]) == ("1.0.0", "code.js", ["figma"])
    assert found["name"]
    assert found["id"]
    assert found["networkAccess"] == {"allowedDomains": ["none"]}


def test_the_export_is_deterministic_and_never_reaches_the_network() -> None:
    data = screens()
    assert export_zip(data) == export_zip(list(reversed(data)))
    code = code_js(data)
    for forbidden in ("fetch(", "XMLHttpRequest", "eval(", "Function(", "http://", "https://", "Date", "Math.random",
                      "import(", "require("):  # fmt: skip
        assert forbidden not in code, forbidden
    assert code.rstrip().endswith(");")
    assert "figma.closePlugin(" in code


def test_every_screen_field_action_and_state_is_in_the_data_without_the_legacy_sources() -> None:
    data = screens()
    inlined = plugin_data(data)
    by_id = {s["id"]: s for m in inlined["modules"] for s in m["screens"]}
    assert set(by_id) == {s["id"] for s in data}
    for original in data:
        screen = by_id[original["id"]]
        assert [f["name"] for f in screen["fields"]] == [f["name"] for f in original["fields"]]
        assert [a["key"] for a in screen["actions"]] == [a["key"] for a in original["actions"]]
        assert screen["states"] == ([s for s in STATES if s in original["states"]] or list(STATES))
    user = by_id["SCR-LOGIN"]["fields"][0]
    assert (user["required"], user["format"], user["validation"], user["message"]) == (
        True, "X(8)", "not blank", "ENTER THE USER")  # fmt: skip
    assert by_id["SCR-LOGIN"]["states"] == ["loading", "error"]
    assert [m["name"] for m in inlined["modules"]] == sorted({s["mapset"] or DEFAULT_MODULE for s in data})
    assert "source" not in json.dumps(inlined)
    assert "PAGOSET.bms" not in code_js(data)


def test_styles_come_from_the_project_tokens_over_the_base_ones() -> None:
    base = styles()
    assert base["colors"]["primary"] == base_tokens()["color"]["primary"]
    assert base["family"] == "Inter"
    assert base["text"]["title"] == {"size": 24, "style": "Bold"}
    custom = styles({"color": {"primary": "#123456", "bad": "red"}, "font": {"family": "Roboto, sans-serif"}})
    assert custom["colors"]["primary"] == "#123456"
    assert "bad" not in custom["colors"]
    assert custom["colors"]["danger"] == base["colors"]["danger"]
    assert custom["family"] == "Roboto"
    assert custom["text"]["body"]["size"] == 16


def test_no_screens_is_an_error() -> None:
    with pytest.raises(ValueError, match="no screens"):
        export_zip([])


def _image() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


@pytest.fixture(scope="module")
def sandbox() -> DockerSandbox:
    box = DockerSandbox(image=IMAGE)
    if not asyncio.run(box.available()) or not _image():
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    return box


def _named(node: dict[str, Any], name: str) -> dict[str, Any]:
    return next(c for c in node["children"] if c["name"] == name)


def _names(frame: dict[str, Any], group: str) -> list[str]:
    return [c["name"] for c in _named(frame, group)["children"]]


def _texts(node: dict[str, Any]) -> list[str]:
    own = [node["characters"]] if node["type"] == "TEXT" else []
    return own + [t for c in node["children"] for t in _texts(c)]


async def test_the_plugin_creates_a_frame_per_screen_with_its_fields_actions_and_states(sandbox: DockerSandbox) -> None:
    data = screens()
    # A font the fake does not have: the plugin falls back to Inter.
    code = code_js(data, {"font": {"family": "Roboto"}})
    files = {"code.js": code.encode("utf-8"), "harness.mjs": HARNESS.read_bytes()}
    result = await sandbox.run(["node", "/input/harness.mjs"], files=files, limits=LIMITS)
    assert result.ok, result.stderr[-2000:]
    out = json.loads(result.stdout)
    modules = {s["mapset"] or DEFAULT_MODULE for s in data}
    assert out["message"] == f"NexTI: {len(data)} screens exported to {len(modules)} pages"
    pages = {p["name"]: p for p in out["root"]["children"] if p["type"] == "PAGE"}
    assert set(pages) == {"Page 1", *modules}
    assert pages["Page 1"]["children"] == []
    style_ids = {s["id"] for s in out["styles"]}
    assert {s["name"] for s in out["styles"]} >= {"NexTI/color/primary", "NexTI/text/title", "NexTI/text/hint"}

    frames: dict[str, dict[str, Any]] = {}
    for page in pages.values():
        for frame in page["children"]:
            assert frame["type"] == "FRAME"
            frames[frame["name"].split(" — ")[0]] = frame
    assert set(frames) == {s["id"] for s in data}
    positions = [(f["x"], f["y"]) for f in frames.values()]
    assert len(set(positions)) == len(positions) or len(pages) > 1

    for screen in data:
        frame = frames[screen["id"]]
        assert frame["name"] == f"{screen['id']} — {screen['name']}"
        assert frame["fillStyleId"] in style_ids
        assert _named(frame, "title")["characters"] == screen["name"]
        assert _names(frame, "fields") == [f"field:{f['name']}" for f in screen["fields"]]
        assert _names(frame, "actions") == [f"action:{a['key']}" for a in screen["actions"]]
        expected = [s for s in STATES if s in screen["states"]] or list(STATES)
        assert _names(frame, "states") == [f"state:{s}" for s in expected]
        for node in _texts(frame):
            assert node, "every text has characters"

    login = frames["SCR-LOGIN"]
    user = _named(_named(login, "fields"), "field:USER")
    assert _named(user, "label")["characters"] == "User *"
    assert _named(_named(user, "input"), "type")["characters"] == f"{LOGIN.fields[0].type} (8)"
    assert _named(user, "required")["characters"] == "Required"
    assert _named(user, "hint")["characters"] == "Format: X(8) · Validation: not blank · Error: ENTER THE USER"
    assert _texts(_named(login, "actions")) == ["Sign in (ENTER)", "Exit (PF3)"]
    error = _named(_named(login, "states"), "state:error")
    assert _texts(error) == ["ERROR", "ENTER THE USER"]
