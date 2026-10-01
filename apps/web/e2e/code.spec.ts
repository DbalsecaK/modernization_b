import { spawnSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'
import { capture, devSignIn, expectAccessible } from './support'

// The Code tab against the real API (P2): the file browser of the newest generation, one file with the rules it
// implements, and the zip. Generated files only come from the pipeline (there is no API to write them), so the test
// seeds them with the helpers of the API's integration tests (seed_spec, seed_validation): one generated Java file
// tracing RULE-001, plus a design document that, being working material of the pipeline, the tab must not show.

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
                "INSERT INTO generated_artifact (tenant_id, project_id, run_id, layer, path, object_key, sha256, "
                "size_bytes) SELECT tenant_id, project_id, run_id, 'docs', 'design/design.json', object_key, sha256, "
                "size_bytes FROM generated_artifact WHERE project_id = :p"), {"p": project_id})
    finally:
        await engine.dispose()

asyncio.run(main(sys.argv[1]))
`

function seedCode(projectId: string) {
  const result = spawnSync('uv', ['run', '--no-sync', 'python', '-', projectId], {
    cwd: new URL('../../..', import.meta.url),
    input: SEED,
    encoding: 'utf8',
    shell: process.platform === 'win32',
  })
  expect(result.status, `seeding the generated code failed (is the local stack up?)\n${result.stderr}`).toBe(0)
}

async function csrf(page: Page) {
  const me = await (await page.request.get('/api/v1/me')).json()
  return { 'X-CSRF-Token': me.csrfToken as string, Origin: 'http://localhost:5173' }
}

async function createProject(page: Page) {
  const created = await page.request.post('/api/v1/projects', {
    data: {
      name: `E2E Code ${Date.now()}`,
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

/** Drops some permissions from the project the web reads, as if the user's role lacked them. */
async function withoutPermissions(page: Page, projectId: string, dropped: string[]) {
  await page.route(`**/api/v1/projects/${projectId}`, async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    await route.fulfill({
      response,
      json: { ...body, permissions: (body.permissions as string[]).filter((p) => !dropped.includes(p)) },
    })
  })
}

test('the code tab browses the generated files, links their rules and downloads the zip', async ({ page }) => {
  test.setTimeout(120_000)
  await devSignIn(page, 'María Torres')
  const projectId = await createProject(page)

  // Before the pipeline: nothing generated yet, and the way to the runs.
  await page.goto(`/projects/${projectId}?tab=code`)
  await expect(page.getByText('Code appears in the generation phase')).toBeVisible()

  seedCode(projectId)
  await page.reload()

  // The tree shows the delivered project only, folders joined as in an IDE; the first file opens by itself.
  const files = page.getByRole('list', { name: 'Generated files' })
  await expect(files.getByText('src/main/java/demo/')).toBeVisible()
  await expect(files.getByRole('button')).toHaveCount(1)
  await expect(files.getByText('design/')).toHaveCount(0)
  await expect(files.getByRole('button', { name: 'PayOrderService.java' })).toHaveAttribute('aria-current', 'true')
  await expect(page.getByText('// RULE-001: only current, savings and virtual accounts')).toBeVisible()
  await expect(page.getByText('domain', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Push to Git' })).toBeDisabled()
  await expectAccessible(page, 'main')
  await capture(page, 'code')

  const download = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Download zip' }).click()
  expect((await download).suggestedFilename()).toMatch(/^code-.+\.zip$/)

  // The rule a file implements leads to its side-by-side comparison.
  await page.getByRole('link', { name: 'RULE-001' }).click()
  await expect(page).toHaveURL(/tab=traceability/)
  await expect(page.getByRole('heading', { name: /RULE-001 · Rule 1/ })).toBeVisible()

  // Without code.download there is no zip; without code.view the tab does not ask for code at all.
  await withoutPermissions(page, projectId, ['code.download'])
  await page.goto(`/projects/${projectId}?tab=code`)
  await expect(page.getByText('Downloading needs the code.download permission')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Download zip' })).toHaveCount(0)
  let codeCalls = 0
  page.on('request', (r) => {
    if (r.url().includes(`/api/v1/projects/${projectId}/code`)) codeCalls += 1
  })
  await page.unroute(`**/api/v1/projects/${projectId}`)
  await withoutPermissions(page, projectId, ['code.view', 'code.download'])
  await page.reload()
  await expect(page.getByText('Seeing code needs the code.view permission')).toBeVisible()
  expect(codeCalls).toBe(0)
})
