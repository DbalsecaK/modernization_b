"""The prototype change chat in the worker (spec 7.4, D-24; plan M5 step 9) on the real services and the web sandbox:
a change within the spec becomes a new prototype version, one that adds a field the spec does not have is only
proposed (its prototype built and stored), and one the designer cannot get right fails with its reason. The model is a
stand-in: the chat's contract is what code checks, not what a model writes. Skipped without nexti-sandbox-web:1."""

import subprocess
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from nexti_adapter_bms import BmsAdapter
from nexti_core.adapters import SourceFile
from nexti_sandbox import DockerSandbox
from nexti_ui import IMAGE
from nexti_worker.ui_chat import apply_ui_change

from .conftest import World
from .run_support import BMS_SOURCE, fetch, make_project, seed_screens
from .test_validation_api import store

SCREEN = next(
    s
    for s in BmsAdapter().screens([SourceFile("maps/PAGOSET.bms", BMS_SOURCE.read_text(encoding="utf-8"))])
    if s.id == "SCR-PAGOORD"
)


def _image(name: str) -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", name], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


@pytest.fixture(scope="module")
def web_sandbox() -> None:
    if not _image(IMAGE):
        pytest.skip(f"the image {IMAGE} is not built")


def prototype(extra: str = "", skip: str = "") -> str:
    names = [f.name for f in SCREEN.fields if f.kind != "literal" and f.name != skip] + ([extra] if extra else [])
    items = "\n".join(
        f'      <div data-field="{n}"><TextField label="{n.title()}" defaultValue="" /></div>' for n in names
    )
    return f"""```tsx
import {{ Screen, TextField }} from '@nexti/ds'

export default function Prototype() {{
  return (
    <Screen title="Orden de pago" code="PAGOORD">
{items}
    </Screen>
  )
}}
```"""


class Gateway:
    """Answers by the change asked: EMAIL adds a field, OLVIDAR always forgets VALOR, anything else stays in spec."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, ctx: Any, messages: list[dict[str, str]]) -> Any:
        self.calls += 1
        request = messages[1]["content"]
        content = prototype("EMAIL") if "EMAIL" in request else prototype(skip="VALOR" if "OLVIDAR" in request else "")
        usage = SimpleNamespace(input_tokens=10, output_tokens=10)
        return SimpleNamespace(content=content, usage=usage, cost_usd=0, model="stand-in")


async def ask(owner: AsyncEngine, tenant_id: uuid.UUID, project_id: uuid.UUID, body: str) -> uuid.UUID:
    (row,) = await fetch(
        owner,
        "INSERT INTO ui_chat_message (tenant_id, project_id, screen_key, role, body, status) "
        "VALUES (:t, :p, 'SCR-PAGOORD', 'user', :b, 'pending') RETURNING id",
        t=tenant_id, p=project_id, b=body,
    )  # fmt: skip
    return uuid.UUID(str(row["id"]))


async def test_a_change_becomes_a_version_a_proposal_or_a_failure(
    web_sandbox: None, app_engine: AsyncEngine, owner_engine: AsyncEngine, world: World
) -> None:
    objects = store()
    project_id = await make_project(owner_engine, world.tenant_a)
    await seed_screens(owner_engine, objects, world.tenant_a, project_id)
    gateway = Gateway()

    def sandboxes(image: str) -> DockerSandbox:
        return DockerSandbox(image=image)

    async def apply(body: str) -> str:
        message = await ask(owner_engine, world.tenant_a, project_id, body)
        return await apply_ui_change(app_engine, gateway, objects, sandboxes, message, world.tenant_a)  # type: ignore[arg-type]

    assert await apply("Agrupar los datos en una tarjeta") == "version"
    assert await apply("Agregar el EMAIL del cliente") == "proposal"
    assert await apply("OLVIDAR el valor") == "failed"
    assert gateway.calls == 1 + 1 + 3  # the failure went back to the designer until the limit

    versions = await fetch(owner_engine, "SELECT version, origin, source_key, bundle_key FROM prototype "
                           "WHERE project_id = :p ORDER BY version", p=project_id)  # fmt: skip
    assert [(v["version"], v["origin"]) for v in versions] == [(1, "generated"), (2, "chat")]
    source = b"".join(await objects.read(versions[1]["source_key"])).decode("utf-8")
    assert 'data-field="VALOR"' in source
    assert b"".join(await objects.read(versions[1]["bundle_key"])).startswith(b"<!doctype html>")

    messages = await fetch(owner_engine, "SELECT role, status, proposal, prototype_version FROM ui_chat_message "
                           "WHERE project_id = :p ORDER BY created_at, role DESC", p=project_id)  # fmt: skip
    assert [(m["role"], m["status"]) for m in messages] == [
        ("user", "done"), ("agent", "done"), ("user", "done"), ("agent", "proposal"), ("user", "failed"),
        ("agent", "failed"),
    ]  # fmt: skip
    assert messages[1]["prototype_version"] == 2
    proposal = messages[3]["proposal"]
    assert proposal["fields"] == ["EMAIL"]
    assert 'data-field="EMAIL"' in b"".join(await objects.read(proposal["source_key"])).decode("utf-8")

    again = await apply_ui_change(app_engine, gateway, objects, sandboxes, uuid.uuid4(), world.tenant_a)  # type: ignore[arg-type]
    assert again == "nothing to do"
