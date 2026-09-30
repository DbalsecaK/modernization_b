import { spawnSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'
import { capture, devSignIn, expectAccessible } from './support'

// The Diseño UI tab against the real API (M5): the screens of the fictitious BMS application, the legacy terminal
// screen next to the prototype running in an isolated frame (fields linked both ways, navigation between screens),
// comments anchored to a field and the change chat with its proposals. Screens and prototypes only come from the
// pipeline, so the test seeds them with the helpers of the API's integration tests (seed_screens, seed_proposal)
// and compiles a real prototype of SCR-PAGOORD in the web sandbox (nexti-sandbox-web:1), the same way the UI phase
// does. The worker does not run here: a change asked in the chat stays pending.

// Reads MIGRATION_DATABASE_URL and the object store settings from apps/api/.env through the API's own settings
// (never printed).
const SEED = String.raw`
import asyncio, io, sys, uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from nexti_api.settings import Settings
from nexti_core.object_store import ObjectStore, ObjectStoreConfig
from nexti_sandbox import DockerSandbox
from nexti_ui import IMAGE, build, page

sys.path.insert(0, "apps/api/tests/integration")
from run_support import BMS_SOURCE, seed_proposal, seed_screens
from nexti_adapter_bms import BmsAdapter
from nexti_core.adapters import SourceFile

def prototype(screen) -> str:
    items = "\n".join(
        f'        <TextField data-field="{f.name}" label="{(f.label or f.name).title()}" defaultValue="" />'
        for f in screen.fields if f.kind != "literal"
    )
    return f"""import {{ Screen, Card, Stack, TextField, Button }} from '@nexti/ds'

export default function Prototype({{ navigate }}: {{ navigate: (to: string) => void }}) {{
  return (
    <Screen title="Orden de pago" code="PAGOORD">
      <Card title="Datos de la orden">
        <Stack>
{items}
        </Stack>
      </Card>
      <Button onClick={{() => navigate('SCR-PAGOMEN')}}>Volver al menu</Button>
    </Screen>
  )
}}
"""

async def main(project_id: str, what: str) -> None:
    settings = Settings()
    store = ObjectStore(ObjectStoreConfig(settings.object_store_url, settings.object_store_access_key,
                                          settings.object_store_secret_key.get_secret_value(),
                                          settings.object_store_bucket))
    engine = create_async_engine(settings.migration_database_url.get_secret_value())
    try:
        async with engine.begin() as conn:
            tenant = (await conn.execute(text("SELECT tenant_id FROM project WHERE id = :p"), {"p": project_id})).scalar_one()
        project = uuid.UUID(project_id)
        if what == "proposal":
            await seed_proposal(engine, tenant, project)
            return
        await seed_screens(engine, store, tenant, project)
        screens = BmsAdapter().screens([SourceFile("maps/PAGOSET.bms", BMS_SOURCE.read_text(encoding="utf-8"))])
        screen = next(s for s in screens if s.id == "SCR-PAGOORD")
        source = prototype(screen)
        built = await build(DockerSandbox(image=IMAGE), source)
        if not built.ok:
            raise SystemExit("the prototype did not compile: " + "; ".join(built.errors))
        prefix = f"tenants/{tenant}/projects/{project}/prototypes/SCR-PAGOORD/v1"
        for key, content, media in ((f"{prefix}/Screen.tsx", source, "text/plain"),
                                    (f"{prefix}/index.html", page(built, "SCR-PAGOORD"), "text/html")):
            data = content.encode("utf-8")
            await store.put(key, io.BytesIO(data), len(data), media)
    finally:
        await engine.dispose()

asyncio.run(main(sys.argv[1], sys.argv[2]))
`

function seed(projectId: string, what: 'screens' | 'proposal') {
  const result = spawnSync('uv', ['run', '--no-sync', 'python', '-', projectId, what], {
    cwd: new URL('../../..', import.meta.url),
    input: SEED,
    encoding: 'utf8',
    shell: process.platform === 'win32',
  })
  expect(result.status, `seeding the screens failed (local stack and nexti-sandbox-web:1?)\n${result.stderr}`).toBe(0)
}

async function csrf(page: Page) {
  const me = await (await page.request.get('/api/v1/me')).json()
  return { 'X-CSRF-Token': me.csrfToken as string, Origin: 'http://localhost:5173' }
}

async function createProject(page: Page) {
  const created = await page.request.post('/api/v1/projects', {
    data: {
      name: `E2E UI design ${Date.now()}`,
      flow: 'modernization',
      sources: ['cobol-cics', 'bms'],
      target: {
        architecture: 'modular-monolith',
        backend: 'spring-boot',
        frontend: 'react',
        database: 'postgresql',
        cloud: 'aws',
      },
      pipelineTemplate: 'internalAgile',
    },
    headers: await csrf(page),
  })
  expect(created.status(), await created.text()).toBe(201)
  const projectId = (await created.json()).id as string
  await expect
    .poll(async () => (await page.request.get(`/api/v1/projects/${projectId}`)).status(), { timeout: 30_000 })
    .toBe(200)
  return projectId
}

test('the UI design tab links the legacy screen with the isolated prototype, comments and the change chat', async ({
  page,
}) => {
  test.setTimeout(180_000)
  await devSignIn(page, 'María Torres')
  const projectId = await createProject(page)

  await page.goto(`/projects/${projectId}?tab=uiDesign`)
  await expect(page.getByText('No screens yet')).toBeVisible()

  seed(projectId, 'screens')
  await page.reload()

  // The catalog: the three maps of PAGOSET, each with its fields.
  const catalog = page.getByRole('group', { name: 'Screen catalog' })
  const current = catalog.getByRole('button', { pressed: true })
  await expect(catalog.getByRole('button', { name: /SCR-PAGOMEN/ })).toBeVisible()
  await expect(catalog.getByRole('button', { name: /SCR-PAGORES/ })).toBeVisible()
  await catalog.getByRole('button', { name: /SCR-PAGOORD/ }).click()
  await expect(current).toContainText('SCR-PAGOORD')

  // The spec fields with the position, length and attributes read from the map.
  const fields = page.getByRole('table')
  await expect(fields.getByRole('row', { name: /ORDEN/ })).toContainText('4,26')
  await expect(fields.getByRole('row', { name: /ORDEN/ })).toContainText('unprotected, numeric, cursor, modified')

  // The prototype runs in a frame with an opaque origin and no same-origin access.
  const frameElement = page.locator('iframe[title^="Prototype of"]')
  await expect(frameElement).toHaveAttribute('sandbox', 'allow-scripts')
  await expect(frameElement).toHaveAttribute('data-ready', '1', { timeout: 30_000 })
  const frame = page.frameLocator('iframe[title^="Prototype of"]')
  await expect(frame.locator('[data-field="ORDEN"]').first()).toBeVisible()
  await expectAccessible(page, 'main')
  await capture(page, 'ui-design')

  // A field clicked in the prototype is linked with the legacy screen and becomes the comment's anchor.
  await frame.locator('[data-field="VALOR"]').first().click()
  await expect(page.getByRole('combobox', { name: 'Comment field' })).toHaveValue('VALOR')
  await expect(page.locator('[data-legacy-field="VALOR"]')).toHaveClass(/bg-\[#05e194\]/)
  await page.getByRole('textbox', { name: 'Write a comment' }).fill('El valor debe mostrar dos decimales')
  await page.getByRole('button', { name: 'Comment', exact: true }).click()
  const comment = page.getByText('El valor debe mostrar dos decimales')
  await expect(comment).toBeVisible()
  await page.getByRole('button', { name: 'Resolve' }).click()
  await expect(page.getByRole('button', { name: 'Reopen' })).toBeVisible()

  // A field clicked on the legacy screen is linked the other way.
  await page.locator('[data-legacy-field="ORDEN"]').click()
  await expect(page.getByRole('combobox', { name: 'Comment field' })).toHaveValue('ORDEN')

  // The change chat: the request is enqueued for the worker (it stays pending here).
  await page.getByRole('textbox', { name: /Describe the change/ }).fill('Mostrar el valor con dos decimales')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByText('Mostrar el valor con dos decimales')).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: 'updating the prototype' })).toBeVisible()

  // A proposal to change the spec (a field EMAIL): a person accepts it; spec and prototype get a new version.
  seed(projectId, 'proposal')
  await page.reload()
  await catalog.getByRole('button', { name: /SCR-PAGOORD/ }).click()
  await page.getByRole('button', { name: 'Accept' }).click()
  await expect(page.getByText('New prototype version v2')).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Version' })).toContainText('v2 · chat')
  await expect(fields.getByRole('row', { name: /EMAIL/ })).toBeVisible()

  // The prototype navigates: its button opens the menu screen in the catalog.
  await page.getByRole('combobox', { name: 'Version' }).selectOption('1')
  await frame.getByRole('button', { name: 'Volver al menu' }).click()
  await expect(current).toContainText('SCR-PAGOMEN')
})
