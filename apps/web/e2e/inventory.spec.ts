import { spawnSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'
import { capture, devSignIn, expectAccessible } from './support'

// The Inventario tab against the real API and Neo4j (M6): the knowledge graph of the fictitious CICS application as
// the inventory phase writes it (the COBOL adapter), with the reference rules as the project's rules. The graph only
// comes from the pipeline, so the test seeds it with the helper of the API's integration tests (seed_graph).

// Reads MIGRATION_DATABASE_URL and the graph settings from apps/api/.env through the API's own settings (never
// printed).
const SEED = String.raw`
import asyncio, sys, uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from nexti_api.settings import Settings

sys.path.insert(0, "apps/api/tests/integration")
from run_support import seed_graph

async def main(project_id: str) -> None:
    settings = Settings()
    engine = create_async_engine(settings.migration_database_url.get_secret_value())
    try:
        async with engine.begin() as conn:
            tenant = (await conn.execute(text("SELECT tenant_id FROM project WHERE id = :p"), {"p": project_id})).scalar_one()
        await seed_graph(engine, settings, tenant, uuid.UUID(project_id))
    finally:
        await engine.dispose()

asyncio.run(main(sys.argv[1]))
`

function seedGraph(projectId: string) {
  const result = spawnSync('uv', ['run', '--no-sync', 'python', '-', projectId], {
    cwd: new URL('../../..', import.meta.url),
    input: SEED,
    encoding: 'utf8',
    shell: process.platform === 'win32',
  })
  expect(result.status, `seeding the graph failed (local stack and Neo4j up?)\n${result.stderr}`).toBe(0)
}

async function csrf(page: Page) {
  const me = await (await page.request.get('/api/v1/me')).json()
  return { 'X-CSRF-Token': me.csrfToken as string, Origin: 'http://localhost:5173' }
}

async function createProject(page: Page) {
  const created = await page.request.post('/api/v1/projects', {
    data: {
      name: `E2E Inventory ${Date.now()}`,
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

test('the inventory tab shows the CICS graph, walks a business flow and focuses a rule', async ({ page }) => {
  test.setTimeout(120_000)
  await devSignIn(page, 'María Torres')
  const projectId = await createProject(page)

  await page.goto(`/projects/${projectId}?tab=inventory`)
  await expect(page.getByText('No inventory yet')).toBeVisible()

  seedGraph(projectId)
  await page.reload()

  // The counts by type and the graph with its units.
  await expect(page.getByRole('button', { name: 'PAGOORD · program' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'PGOR · transaction' })).toBeVisible()
  await expectAccessible(page, 'main')
  await capture(page, 'inventory')

  // The business flow of transaction PGOR, walked in the order of the code with the rule of each step.
  await page.getByRole('combobox', { name: 'Business flow walkthrough' }).selectOption({ label: 'PGOR' })
  await expect(page.getByText('PGOR starts PAGOORD', { exact: true })).toBeVisible()
  await expect(page.getByText('PAGOORD calls PAGODEB', { exact: true })).toBeVisible()
  await expect(page.getByText('PAGODEB reads CUENTAS', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'RULE-004' }).first()).toBeVisible()
  await page.getByRole('button', { name: 'Next' }).click()
  await capture(page, 'inventory-flow')

  // Rule focus: the programs that implement it.
  await page.getByRole('combobox', { name: 'Business rule' }).selectOption('RULE-007')
  await expect(page.getByRole('button', { name: 'PAGODEB', exact: true })).toBeVisible()

  // The detail of a copybook and its impact, computed by the server.
  await page.getByRole('combobox', { name: 'Business rule' }).selectOption('')
  await page.getByRole('button', { name: 'ORDREG · copybook' }).click()
  await page.getByRole('button', { name: 'Show impact' }).click()
  const impact = page.getByText(/items depend on it:/)
  await expect(impact).toContainText('PAGOORD')
  await expect(impact).toContainText('PGOR')

  // A rule opens the Source ↔ target view on it.
  await page.getByRole('button', { name: 'PAGOORD · program' }).click()
  await page.getByRole('button', { name: 'RULE-004', exact: true }).click()
  await expect(page).toHaveURL(/tab=traceability/)
  await expect(page).toHaveURL(/rule=RULE-004/)
})
