import { spawnSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'
import { capture, devSignIn, expectAccessible } from './support'

// The top bar against the real API (P2): the global search finds a project, its rules and catalog agents, and the
// notifications list what happened in the projects the user may see. Rules, verdicts and escalations only come from
// the pipeline, so the test seeds one project with the helpers of the API's integration tests (seed_spec,
// seed_validation) and escalates its run.

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
            await conn.execute(text(
                "UPDATE run SET status = 'waiting', waiting_reason = 'escalation', current_phase = 'generation' "
                "WHERE project_id = :p"), {"p": project_id})
    finally:
        await engine.dispose()

asyncio.run(main(sys.argv[1]))
`

function seedProject(projectId: string) {
  const result = spawnSync('uv', ['run', '--no-sync', 'python', '-', projectId], {
    cwd: new URL('../../..', import.meta.url),
    input: SEED,
    encoding: 'utf8',
    shell: process.platform === 'win32',
  })
  expect(result.status, `seeding the project failed (is the local stack up?)\n${result.stderr}`).toBe(0)
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

test('the global search and the notifications come from the real data of the tenant', async ({ page }) => {
  test.setTimeout(120_000)
  await devSignIn(page, 'María Torres')
  const stamp = String(Date.now())
  const name = `E2E Topbar ${stamp}`
  const projectId = await createProject(page, name)
  seedProject(projectId)
  await page.goto('/')

  // The project by part of its name.
  const search = page.getByRole('combobox', { name: 'Search' })
  await search.fill(stamp)
  const results = page.getByRole('listbox', { name: 'Search' })
  await expect(results.getByRole('option', { name: new RegExp(name) })).toBeVisible()
  await expectAccessible(page, 'header')
  await capture(page, 'search')
  await search.press('Enter')
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}`))

  // A catalog agent, searched in the catalog the web already has.
  await search.fill('architect')
  await expect(results.getByRole('option', { name: /Agent/ }).first()).toBeVisible()
  await search.press('Escape')

  // The notifications of the project: its escalation and its new verdict.
  await page.getByRole('button', { name: /notifications/i }).click()
  const list = page.getByRole('list', { name: 'Notifications' })
  await expect(list.getByText(`${name} escalated to a person in Generation`)).toBeVisible()
  await expect(list.getByText(`New verdict in ${name}: PayOrder · PARTLY PROVEN`)).toBeVisible()
  await expectAccessible(page, 'header')
  await capture(page, 'notifications')
  await page.getByRole('button', { name: 'Mark all as read' }).click()
  await expect(page.getByRole('button', { name: 'Mark all as read' })).toHaveCount(0)
  await list.getByText(`New verdict in ${name}: PayOrder · PARTLY PROVEN`).click()
  await expect(page).toHaveURL(/tab=validation/)
})
