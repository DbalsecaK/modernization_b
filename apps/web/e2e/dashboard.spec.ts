import { spawnSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'
import { capture, devSignIn, expectAccessible } from './support'

// The dashboard against the real API (P2): the executive, delivery and administrator views of the active tenant.
// Verdicts, usage and escalations only come from the pipeline and the model gateway, so the test seeds one project
// with the helpers of the API's integration tests (seed_spec, seed_validation: three rules and a PARTLY PROVEN verdict
// that verified one), usage against a project budget with its 80% alert, and its run escalated to a person.

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
        async with engine.begin() as conn:
            params = {"t": tenant, "p": project_id}
            await conn.execute(text(
                "INSERT INTO usage_ledger (tenant_id, project_id, phase, model, outcome, input_tokens, output_tokens, "
                "cost_usd) VALUES (:t, :p, 'generation', 'openai/gpt-4o-mini', 'success', 1000, 200, 0.45)"), params)
            budget = (await conn.execute(text(
                "INSERT INTO budget (tenant_id, project_id, period, amount_usd) VALUES (:t, :p, 'total', 0.5) "
                "RETURNING id"), params)).scalar_one()
            await conn.execute(text(
                "INSERT INTO budget_alert (tenant_id, budget_id, level, period_key, spent_usd) "
                "VALUES (:t, :b, 80, 'total', 0.45)"), {"t": tenant, "b": budget})
            await conn.execute(text(
                "UPDATE run SET status = 'waiting', waiting_reason = 'escalation', current_phase = 'generation' "
                "WHERE project_id = :p"), params)
    finally:
        await engine.dispose()

asyncio.run(main(sys.argv[1]))
`

function seedDashboard(projectId: string) {
  const result = spawnSync('uv', ['run', '--no-sync', 'python', '-', projectId], {
    cwd: new URL('../../..', import.meta.url),
    input: SEED,
    encoding: 'utf8',
    shell: process.platform === 'win32',
  })
  expect(result.status, `seeding the dashboard failed (is the local stack up?)\n${result.stderr}`).toBe(0)
}

async function csrf(page: Page) {
  const me = await (await page.request.get('/api/v1/me')).json()
  return { 'X-CSRF-Token': me.csrfToken as string, Origin: 'http://localhost:5173' }
}

async function createProject(page: Page, name: string) {
  const created = await page.request.post('/api/v1/projects', {
    data: {
      name,
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

test('the dashboard shows progress, risks, delivery and administration from real data', async ({ page }) => {
  test.setTimeout(120_000)
  await devSignIn(page, 'María Torres')
  const name = `E2E Dashboard ${Date.now()}`
  const projectId = await createProject(page, name)
  seedDashboard(projectId)

  // Executive: the project with its phase and verdict, and the risks it raises (most recently active first; the
  // full rules of the list are unit-tested in features/dashboard/model.test.ts).
  await page.goto('/')
  const row = page.getByRole('link', { name: new RegExp(name) })
  await expect(row).toContainText('PARTLY PROVEN')
  await expect(page.getByText(`${name} escalated to a person: the agents ran out of attempts.`)).toBeVisible()
  await expect(page.getByText(`${name} has used 90% of its budget.`)).toBeVisible()
  await expect(page.getByText('Monthly AI spend')).toBeVisible()
  await expectAccessible(page, 'main')
  await capture(page, 'dashboard-executive')

  // Delivery: the counters of the runs.
  await page.getByRole('button', { name: 'Delivery' }).click()
  await expect(page.getByText('Escalations to humans')).toBeVisible()
  await expect(page.getByText('Pending approvals')).toBeVisible()
  await expectAccessible(page, 'main')

  // Administrator: users, connections and the budget alert.
  await page.getByRole('button', { name: 'Administrator' }).click()
  await expect(page.getByText('Active users')).toBeVisible()
  await expect(page.getByText(`${name} crossed 80% of its budget.`)).toBeVisible()
  await expectAccessible(page, 'main')
  await capture(page, 'dashboard-admin')
})
