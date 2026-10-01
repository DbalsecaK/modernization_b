import { spawnSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'
import { capture, devSignIn, expectAccessible } from './support'

// The Architecture tab and the Screens and Contracts views of the specification against the real API (P2): the
// design approved at C3, its decisions, the OpenAPI contract and the checks of the newest verdict; the operations
// with their rules; and the screen specs. Designs, verdicts and screens only come from the pipeline (there is no API
// to write them), so the test seeds them with the helpers of the API's integration tests: the design of the
// fictitious payments application with its OpenAPI document (seed_architecture), a verdict (seed_validation) and
// the screens of the fictitious BMS map set (seed_screens).

// Reads MIGRATION_DATABASE_URL and the object store settings from apps/api/.env through the API's own settings
// (never printed).
const SEED = String.raw`
import asyncio, sys, uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from nexti_api.settings import Settings
from nexti_core.object_store import ObjectStore, ObjectStoreConfig

sys.path.insert(0, "apps/api/tests/integration")
from run_support import seed_architecture, seed_screens, seed_spec, seed_validation

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
        await seed_architecture(engine, store, tenant, project)
        await seed_screens(engine, store, tenant, project)
    finally:
        await engine.dispose()

asyncio.run(main(sys.argv[1]))
`

function seedArchitecture(projectId: string) {
  const result = spawnSync('uv', ['run', '--no-sync', 'python', '-', projectId], {
    cwd: new URL('../../..', import.meta.url),
    input: SEED,
    encoding: 'utf8',
    shell: process.platform === 'win32',
  })
  expect(result.status, `seeding the architecture failed (is the local stack up?)\n${result.stderr}`).toBe(0)
}

async function csrf(page: Page) {
  const me = await (await page.request.get('/api/v1/me')).json()
  return { 'X-CSRF-Token': me.csrfToken as string, Origin: 'http://localhost:5173' }
}

async function createProject(page: Page) {
  const created = await page.request.post('/api/v1/projects', {
    data: {
      name: `E2E Architecture ${Date.now()}`,
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
  expect(created.status()).toBe(201)
  const projectId = (await created.json()).id as string
  // Authorization tuples are published by the OpenFGA relay a moment after the commit.
  await expect
    .poll(async () => (await page.request.get(`/api/v1/projects/${projectId}`)).status(), { timeout: 30_000 })
    .toBe(200)
  return projectId
}

test('the architecture tab shows the approved design, its contract and checks; the specification its operations and screens', async ({
  page,
}) => {
  test.setTimeout(120_000)
  await devSignIn(page, 'María Torres')
  const projectId = await createProject(page)

  // Before the design phase.
  await page.goto(`/projects/${projectId}?tab=architecture`)
  await expect(page.getByText('The architecture appears in the design phase')).toBeVisible()

  seedArchitecture(projectId)
  await page.reload()

  // The bounded context with its service, the entities, ports and decisions of the design.
  await expect(page.getByRole('cell', { name: 'payments', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: /PayOrderService/ }).first()).toBeVisible()
  await expect(
    page.getByRole('cell', { name: /Debits the account of the company for one payment order/ }),
  ).toBeVisible()
  for (const entity of ['PaymentOrder', 'Tariff', 'Account', 'ServiceTariff']) {
    await expect(page.getByRole('cell', { name: new RegExp(`^${entity}`) }).first()).toBeVisible()
  }
  await expect(page.getByText('DebitGateway', { exact: true })).toBeVisible()
  await page.getByText('The payment is one transaction in the service').click()
  await expect(page.getByText('Decision', { exact: true })).toBeVisible()
  // The contract and, as fitness functions, the checks of the newest verdict.
  await expect(page.getByText('openapi.json · OpenAPI 3.1')).toBeVisible()
  await expect(page.getByText('"openapi": "3.1.0"')).toBeVisible()
  const checks = page.getByRole('list', { name: 'Checks of PayOrder' }).getByRole('listitem')
  await expect(checks).toHaveCount(6)
  await expect(checks.nth(0)).toContainText('Tests ran')
  await expectAccessible(page, 'main')
  await capture(page, 'architecture')

  // The operations, each with the rules it serves.
  await page.getByRole('link', { name: 'See operations' }).click()
  await expect(page).toHaveURL(/view=contracts/)
  const operation = page.getByRole('row').filter({ hasText: '/api/payments/orders/pay' })
  await expect(operation).toContainText('payOrder')
  await expect(operation.getByRole('link')).toHaveCount(9)
  await expectAccessible(page, 'main')
  await capture(page, 'contracts')

  // The screens, read as a spec.
  await page.getByRole('tab', { name: /Screens/ }).click()
  const screens = page.getByRole('list', { name: 'Screens' })
  await expect(screens.getByRole('button', { name: /SCR-PAGOORD/ })).toBeVisible()
  await screens.getByRole('button', { name: /SCR-PAGOORD/ }).click()
  await expect(page.getByRole('columnheader', { name: 'Length' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open in UI design' })).toBeVisible()
  await expectAccessible(page, 'main')
  await capture(page, 'screens')
})
