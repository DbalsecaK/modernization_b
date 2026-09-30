import { spawnSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'
import { capture, devSignIn, expectAccessible } from './support'

// The Validation and Source ↔ target tabs against the real API (M4): the verdict the worker computed with its checks
// and proof pack, and rule by rule the legacy lines next to the generated file and the golden cases. Verdicts, rules
// and generated files only come from the pipeline (there is no API to write them), so the test seeds them with the
// helpers of the API's integration tests (seed_spec, seed_validation): three rules, the legacy archive and the
// generated file in the object store, and a PARTLY PROVEN verdict of module PayOrder with its proof pack.

// Reads MIGRATION_DATABASE_URL and the object store settings from apps/api/.env through the API's own settings
// (never printed).
const SEED = String.raw`
import asyncio, sys, uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from nexti_api.settings import Settings
from nexti_core.object_store import ObjectStore, ObjectStoreConfig

sys.path.insert(0, "apps/api/tests/integration")
from run_support import seed_spec, seed_validation

async def main(project_id: str) -> None:
    settings = Settings()
    store = ObjectStore(ObjectStoreConfig(settings.object_store_url, settings.object_store_access_key,
                                          settings.object_store_secret_key.get_secret_value(),
                                          settings.object_store_bucket))
    engine = create_async_engine(settings.migration_database_url.get_secret_value())
    try:
        async with engine.begin() as conn:
            tenant = (await conn.execute(text("SELECT tenant_id FROM project WHERE id = :p"), {"p": project_id})).scalar_one()
        project = uuid.UUID(project_id)
        await seed_spec(engine, tenant, project)
        await seed_validation(engine, store, tenant, project)
    finally:
        await engine.dispose()

asyncio.run(main(sys.argv[1]))
`

function seedValidation(projectId: string) {
  const result = spawnSync('uv', ['run', '--no-sync', 'python', '-', projectId], {
    cwd: new URL('../../..', import.meta.url),
    input: SEED,
    encoding: 'utf8',
    shell: process.platform === 'win32',
  })
  expect(result.status, `seeding the verification failed (is the local stack up?)\n${result.stderr}`).toBe(0)
}

async function csrf(page: Page) {
  const me = await (await page.request.get('/api/v1/me')).json()
  return { 'X-CSRF-Token': me.csrfToken as string, Origin: 'http://localhost:5173' }
}

async function createProject(page: Page) {
  const created = await page.request.post('/api/v1/projects', {
    data: {
      name: `E2E Validation ${Date.now()}`,
      flow: 'modernization',
      sources: ['sybase-sp'],
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
  expect(created.status()).toBe(201)
  const projectId = (await created.json()).id as string
  // Authorization tuples are published by the OpenFGA relay a moment after the commit.
  await expect
    .poll(async () => (await page.request.get(`/api/v1/projects/${projectId}`)).status(), { timeout: 30_000 })
    .toBe(200)
  return projectId
}

test('the validation and traceability tabs show the verdict, its proof pack and rule by rule the comparison', async ({
  page,
}) => {
  test.setTimeout(120_000)
  await devSignIn(page, 'María Torres')
  const projectId = await createProject(page)

  // Before the pipeline: both tabs say there is nothing yet and point to the runs.
  await page.goto(`/projects/${projectId}?tab=validation`)
  await expect(page.getByText('No verification yet')).toBeVisible()
  await page.goto(`/projects/${projectId}?tab=traceability`)
  await expect(page.getByText('Nothing to trace yet')).toBeVisible()

  seedValidation(projectId)

  // Validation: the newest verdict of the module, its six checks, what it does not prove and the proof pack.
  await page.goto(`/projects/${projectId}?tab=validation`)
  const payOrder = page.getByRole('region', { name: 'Verdict of PayOrder' })
  await expect(payOrder.getByText('PARTLY PROVEN')).toBeVisible()
  const checks = payOrder.getByRole('list', { name: 'Checks of PayOrder' }).getByRole('listitem')
  await expect(checks).toHaveCount(6)
  await expect(checks.nth(0)).toContainText('Tests ran')
  await expect(checks.nth(0)).toContainText('7 test(s) passed in a clean build (JUnit XML)')
  await expect(checks.nth(0)).toContainText('Passed')
  await expect(checks.nth(1)).toContainText('Rules traced')
  await expect(checks.nth(1)).toContainText('Not checked')
  await expect(checks.nth(2)).toContainText('1 golden case(s) reproduced')
  await expect(payOrder.getByText('a note', { exact: true })).toBeVisible()
  await expectAccessible(page, 'main')
  await capture(page, 'validation')

  const download = page.waitForEvent('download')
  await payOrder.getByRole('link', { name: 'Download proof pack' }).click()
  expect((await download).suggestedFilename()).toMatch(/^proof-pack-.+\.zip$/)

  // PROVEN is evidence, not approval: the sign-off is at gate C4, in the Runs tab.
  await page.getByRole('button', { name: 'Go to runs' }).click()
  await expect(page).toHaveURL(/tab=runs/)

  // Source ↔ target: the rules with their verification state, and RULE-001 side by side.
  await page.goto(`/projects/${projectId}?tab=traceability`)
  const rules = page.getByRole('list', { name: 'Rules' })
  await expect(rules.getByRole('button')).toHaveCount(3)
  await expect(rules.getByRole('button', { name: /RULE-001/ })).toContainText('Verified')
  await expect(rules.getByRole('button', { name: /RULE-002/ })).toContainText('Pending')
  await expect(page.getByRole('heading', { name: /RULE-001 · Rule 1/ })).toBeVisible()
  const legacy = page.getByRole('region', { name: 'Legacy', exact: true })
  await expect(legacy.getByText('sp/sp_pago_orden.sp:37-45')).toBeVisible()
  await expect(legacy.getByText('3 lines of the rule highlighted')).toBeVisible()
  const target = page.getByRole('region', { name: 'Target', exact: true })
  await expect(target.getByText(/src\/main\/java\/demo\/PayOrderService\.java/)).toBeVisible()
  await expect(target.getByText('// RULE-001: only current, savings and virtual accounts')).toBeVisible()
  const behaviour = page.getByRole('table')
  await expect(behaviour.getByRole('row', { name: /case_one/ })).toContainText('Same')
  await expect(page.getByText('All cases match')).toBeVisible()
  await expectAccessible(page, 'main')
  await capture(page, 'traceability')

  // A rule no verification has looked at yet, and the filter.
  await rules.getByRole('button', { name: /RULE-002/ }).click()
  await expect(page.getByText('No generated file implements this rule yet.')).toBeVisible()
  await expect(page.getByText('No golden or fresh case exercises this rule yet.')).toBeVisible()
  await page.getByRole('combobox', { name: 'Filter by verification' }).selectOption('verified')
  await expect(rules.getByRole('button')).toHaveCount(1)
  await expect(page.getByRole('heading', { name: /RULE-001/ })).toBeVisible()

  // Without code.view the tab does not ask for code (it would be refused).
  let traceCalls = 0
  page.on('request', (r) => {
    if (r.url().includes('/traceability')) traceCalls += 1
  })
  await page.route(`**/api/v1/projects/${projectId}`, async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    await route.fulfill({
      response,
      json: { ...body, permissions: (body.permissions as string[]).filter((p) => p !== 'code.view') },
    })
  })
  await page.reload()
  await expect(page.getByText('You need the code.view permission to see code')).toBeVisible()
  expect(traceCalls).toBe(0)
  await page.goto(`/projects/${projectId}?tab=validation`)
  await expect(page.getByText('You need the code.view permission to download the proof pack.')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Download proof pack' })).toHaveCount(0)
})
