"""Figma as citable text (spec 7.1, ADR-0018). The file is read with Figma's REST API (read only, the tenant's token);
its node tree becomes one line per node, so rules, stories and screens cite `figma/<file key>:<line>` like any other
input:

    FRAME "Simulador" #1:2
      TEXT "Monto" #1:3 text="Monto del crédito"
      INSTANCE "Botón Calcular" #1:7 -> "Resultado"

Invisible nodes are left out; the tree is cut at a fixed depth and size. Buttons of the prototype that navigate
nowhere are found here, by code (a gap of 7.3)."""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

API = "https://api.figma.com/v1"
MAX_DEPTH = 12
MAX_NODES = 5_000
_KEY = re.compile(r"figma\.com/(?:file|design|proto|board)/([A-Za-z0-9]{10,64})")
_BUTTON = re.compile(r"(?i)\b(button|bot[oó]n|btn|cta)\b")


class FigmaError(RuntimeError):
    """Figma could not be read (no token, no access, not found): said in the run, never with the token."""


def file_key(url: str) -> str | None:
    match = _KEY.search(url)
    return match.group(1) if match else None


def citable_path(key: str) -> str:
    return f"figma/{key}"


@dataclass(frozen=True)
class FigmaNode:
    line: int
    id: str
    type: str
    name: str
    depth: int
    frame: str  # the top frame it belongs to ("" for the frames themselves and the pages)
    text: str = ""
    navigates_to: str = ""


def _destination(node: dict[str, Any]) -> str | None:
    if node.get("transitionNodeID"):
        return str(node["transitionNodeID"])
    for interaction in node.get("interactions") or []:
        for action in interaction.get("actions") or ([interaction.get("action")] if interaction.get("action") else []):
            if isinstance(action, dict) and action.get("destinationId"):
                return str(action["destinationId"])
    return None


def _walk(document: dict[str, Any]) -> Iterator[tuple[dict[str, Any], int, str]]:
    stack: list[tuple[dict[str, Any], int, str]] = [(c, 0, "") for c in reversed(document.get("children") or [])]
    while stack:
        node, depth, frame = stack.pop()
        if node.get("visible") is False:
            continue
        yield node, depth, frame
        if depth >= MAX_DEPTH:
            continue
        top = frame or (node.get("name", "") if node.get("type") in ("FRAME", "COMPONENT", "SECTION") and depth == 1
                        else "")  # fmt: skip
        stack += [(c, depth + 1, top) for c in reversed(node.get("children") or [])]


def nodes(data: dict[str, Any]) -> list[FigmaNode]:
    """The visible nodes of the file, numbered as the lines of `render`."""
    document = data.get("document") or {}
    names = {str(n.get("id")): str(n.get("name", "")) for n, _, _ in _walk(document)}
    found: list[FigmaNode] = []
    for node, depth, frame in _walk(document):
        if len(found) >= MAX_NODES:
            break
        destination = _destination(node)
        text = str(node.get("characters") or "") if node.get("type") == "TEXT" else ""
        found.append(FigmaNode(
            line=len(found) + 2, id=str(node.get("id", "")), type=str(node.get("type", "")),
            name=str(node.get("name", "")), depth=depth, frame=frame, text=" ".join(text.split())[:500],
            navigates_to=names.get(destination, destination) if destination else "",
        ))  # fmt: skip
    return found


def render(key: str, data: dict[str, Any]) -> str:
    """The file as text: a title line, then one line per node (line 2 is the first node)."""
    lines = [f'# Figma file "{data.get("name", key)}" ({key})']
    for node in nodes(data):
        line = f'{"  " * node.depth}{node.type} "{node.name}" #{node.id}'
        if node.text:
            line += f' text="{node.text}"'
        if node.navigates_to:
            line += f' -> "{node.navigates_to}"'
        lines.append(line)
    if len(lines) - 1 >= MAX_NODES:
        lines.append(f"# cut at {MAX_NODES} nodes")
    return "\n".join(lines)


def dead_buttons(data: dict[str, Any]) -> list[FigmaNode]:
    """Buttons of the prototype that navigate nowhere (by name: button, botón, btn, cta), neither they nor a child."""
    found = nodes(data)
    navigating = {n.id for n in found if n.navigates_to}
    children: dict[str, list[str]] = {}
    for node, _, _ in _walk(data.get("document") or {}):
        children[str(node.get("id"))] = [str(c.get("id")) for c in node.get("children") or []]

    def navigates(node_id: str, depth: int = 0) -> bool:
        return node_id in navigating or (depth < 4 and any(navigates(c, depth + 1) for c in children.get(node_id, [])))

    return [n for n in found if n.type in ("INSTANCE", "COMPONENT", "FRAME", "GROUP") and n.frame
            and _BUTTON.search(n.name) and not navigates(n.id)]  # fmt: skip


class FigmaReader(Protocol):
    async def file(self, key: str) -> dict[str, Any]: ...


class FigmaClient:
    """The REST API with the tenant's personal access token (header X-Figma-Token)."""

    def __init__(self, http: httpx.AsyncClient, token: str, base_url: str = API) -> None:
        self.http = http
        self.token = token
        self.base_url = base_url.rstrip("/")

    async def file(self, key: str) -> dict[str, Any]:
        try:
            response = await self.http.get(f"{self.base_url}/files/{key}", headers={"X-Figma-Token": self.token},
                                           params={"geometry": "omit"}, timeout=60)  # fmt: skip
        except httpx.HTTPError as exc:
            raise FigmaError(f"Figma could not be reached: {type(exc).__name__}") from exc
        if response.status_code in (401, 403):
            raise FigmaError("Figma refused the token of the integration (check it in Administration → Integrations)")
        if response.status_code == 404:
            raise FigmaError(f"Figma file {key} was not found or the token cannot see it")
        if response.status_code >= 400:
            raise FigmaError(f"Figma answered {response.status_code}")
        data: dict[str, Any] = response.json()
        return data

    async def me(self) -> str:
        """Who the token belongs to (the integration test): their handle, never the token."""
        try:
            response = await self.http.get(f"{self.base_url}/me", headers={"X-Figma-Token": self.token}, timeout=30)
        except httpx.HTTPError as exc:
            raise FigmaError(f"Figma could not be reached: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise FigmaError(f"Figma refused the token ({response.status_code})")
        return str(response.json().get("handle") or response.json().get("email") or "")


class RecordedFigma:
    """Figma answers recorded as `<key>.json` (tests and the local demo, ADR-0012): no network, no token."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    async def file(self, key: str) -> dict[str, Any]:
        path = self.directory / f"{key}.json"
        if not path.exists():
            raise FigmaError(f"Figma file {key} was not found or the token cannot see it")
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data
