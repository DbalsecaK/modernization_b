"""Prototypes (spec 7.4, ADR-0013): a generated screen may only use React and the NexTI design system, never the
network, storage, cookies or the page around it; it builds in the web sandbox into one script and one stylesheet
served inline. The build tests skip without Docker or the image nexti-sandbox-web:1."""

import asyncio
import subprocess

import pytest

from nexti_sandbox import DockerSandbox
from nexti_ui import IMAGE, base_tokens, build, page, problems

SCREEN = """import { useState } from 'react'
import { Screen, Card, Grid, TextField, KeyBar, Alert } from '@nexti/ds'

export default function PayOrder({ navigate }: { navigate: (to: string) => void }) {
  const [order, setOrder] = useState('')
  const [error, setError] = useState('')
  const pay = () => setError(/^\\d{1,7}$/.test(order) ? '' : 'NUMERO DE ORDEN INVALIDO')
  return (
    <Screen title="Pago de ordenes" code="PAGOORD"
      keys={<KeyBar actions={[{ key: 'ENTER', label: 'Pagar', primary: true, onPress: pay },
                              { key: 'PF3', label: 'Volver', onPress: () => navigate('SCR-PAGOMEN') }]} />}>
      <Card title="Orden">
        <Grid>
          <div data-field="ORDEN"><TextField label="Numero de orden" required numeric maxLength={7}
            value={order} onChange={(e) => setOrder(e.target.value)} error={error || undefined} /></div>
        </Grid>
      </Card>
      {error && <Alert tone="error">{error}</Alert>}
    </Screen>
  )
}
"""


@pytest.mark.parametrize(
    ("snippet", "reason"),
    [
        ("import axios from 'axios'", "import from 'axios' is not allowed"),
        ("const r = fetch('/api/v1/projects')", "network access"),
        ("new WebSocket('wss://x')", "network access"),
        ("const c = document.cookie", "cookies or storage"),
        ("localStorage.setItem('a', 'b')", "cookies or storage"),
        ("window.parent.document.title = 'x'", "the page around the prototype"),
        ("window.top", "the page around the prototype"),
        ("eval('1 + 1')", "code evaluation"),
        ("const m = await import('./x')", "dynamic imports"),
        ("location.href = '/logout'", "navigation away"),
        ("const logo = 'https://evil.example/x.png'", "external URLs"),
        ("<div dangerouslySetInnerHTML={{ __html: x }} />", "raw HTML"),
        ("<iframe src='x' />", "raw HTML"),
    ],
)
def test_a_screen_cannot_reach_outside_its_frame(snippet: str, reason: str) -> None:
    found = problems(SCREEN + "\n" + snippet)
    assert any(reason in p for p in found), found


def test_a_screen_with_react_and_the_design_system_passes_the_checks() -> None:
    assert problems(SCREEN) == []
    assert "the screen must be the default export" in problems(SCREEN.replace("export default", "export"))[0]


def test_the_page_carries_the_bundle_inline_and_escapes_closing_tags() -> None:
    from nexti_ui import PrototypeBuild

    html = page(PrototypeBuild(True, js="a('</script>')", css="b{}</style>"), 'Pago <b>"x"</b>')
    assert "<title>Pago bx/b</title>" in html
    assert "<\\/script>" in html
    assert "<\\/style>" in html
    assert html.count("<script>") == 1


def test_the_base_tokens_come_from_the_design_system_package() -> None:
    tokens = base_tokens()
    assert tokens["color"]["primary"] == "#052158"
    assert set(tokens) == {"color", "font", "space", "radius", "shadow"}


def _image_available() -> bool:
    try:
        found = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False, timeout=30)  # noqa: S603, S607
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


@pytest.fixture(scope="module")
def web_sandbox() -> DockerSandbox:
    box = DockerSandbox(image=IMAGE)
    if not asyncio.run(box.available()) or not _image_available():
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    return box


async def test_a_screen_builds_into_one_script_and_one_stylesheet(web_sandbox: DockerSandbox) -> None:
    built = await build(web_sandbox, SCREEN)
    assert built.ok, built.errors
    assert "PAGOORD" in built.js
    assert "nexti-prototype" in built.js  # the platform's entry, with its postMessage protocol
    assert ".nx-screen" in built.css


async def test_a_screen_that_does_not_compile_comes_back_with_the_error(web_sandbox: DockerSandbox) -> None:
    broken = SCREEN.replace("</Screen>", "</Screen")
    built = await build(web_sandbox, broken)
    assert not built.ok
    assert any("prototype/Screen.tsx" in e for e in built.errors), built.errors


async def test_a_forbidden_screen_is_never_built(web_sandbox: DockerSandbox) -> None:
    built = await build(web_sandbox, SCREEN + "\nfetch('x')")
    assert not built.ok
    assert "network access" in built.errors[0]
