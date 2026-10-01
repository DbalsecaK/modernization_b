import { spawnSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'
import { capture, devSignIn, expectAccessible } from './support'

// The Costs tab against the real API (P2): what the project consumed by phase, agent and model against its budget,
// and the self-correction retries. Usage only comes from the model gateway (there is no API to write it), so the test
// writes ledger rows and a project budget straight into the database.

// Reads MIGRATION_DATABASE_URL from apps/api/.env through the API's own settings (never printed).
const SEED = String.raw`
import asyncio, sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from nexti_api.settings import Settings

CALLS = [("design", "architect", 1, "0.10"), ("design", "architect", 2, "0.05"), ("generation", "developer", 1, "0.30")]

async def main(project_id: str) -> None:
    engine = create_async_engine(Settings().migration_database_url.get_secret_value())
    try:
        async with engine.begin() as conn:
            tenant = (await conn.execute(text("SELECT tenant_id FROM project WHERE id = :p"), {"p": project_id})).scalar_one()
            for phase, agent, iteration, cost in CALLS:
                await conn.execute(text(
                    "INSERT INTO usage_ledger (tenant_id, project_id, phase, agent_role, iteration, model, outcome, "
                    "input_tokens, output_tokens, cost_usd) VALUES (:t, :p, :ph, :a, :i, 'openai/gpt-4o-mini', "
                    "'success', 1000, 100, CAST(:c AS numeric))"),
                    {"t": tenant, "p": project_id, "ph": phase, "a": agent, "i": iteration, "c": cost})
            await conn.execute(text(
                "INSERT INTO budget (tenant_id, project_id, period, amount_usd) VALUES (:t, :p, 'total', 5)"),
                {"t": tenant, "p": project_id})
    finally:
        await engine.dispose()

asyncio.run(main(sys.argv[1]))
`

function seedUsage(projectId: string) {
  const result = spawnSync('uv', ['run', '--no-sync', 'python', '-', projectId], {
    cwd: new URL('../../..', import.meta.url),
    input: SEED,
    encoding: 'utf8',
    shell: process.platform === 'win32',
  })
  expect(result.status, `seeding the usage failed (is the local stack up?)\n${result.stderr}`).toBe(0)
}

async function csrf(page: Page) {
  const me = await (await page.request.get('/api/v1/me')).json()
  return { 'X-CSRF-Token': me.csrfToken as string, Origin: 'http://localhost:5173' }
}

async function createProject(page: Page) {
  const created = await page.request.post('/api/v1/projects', {
    data: {
      name: `E2E Costs ${Date.now()}`,
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

test('the costs tab shows the project usage by phase, agent and model against its budget', async ({ page }) => {
  test.setTimeout(120_000)
  await devSignIn(page, 'María Torres')
  const projectId = await createProject(page)

  await page.goto(`/projects/${projectId}?tab=costs`)
  await expect(page.getByText('Costs appear with the first model calls of the pipeline', { exact: true })).toBeVisible()

  seedUsage(projectId)
  await page.reload()

  // Spent against the budget, tokens and the self-correction retries.
  await expect(page.getByText('$0.45').first()).toBeVisible()
  await expect(page.getByText('$5.00').first()).toBeVisible()
  await expect(page.getByText('9% used')).toBeVisible()
  await expect(page.getByText('3 calls')).toBeVisible()
  await expect(page.getByText('$0.05').first()).toBeVisible()
  await expect(page.getByText(/Self-correction retries cost \$0\.05 \(11% of the total\)/)).toBeVisible()
  // By phase and by model.
  await expect(page.getByText('$0.30').first()).toBeVisible()
  await expect(page.getByRole('row', { name: /openai\/gpt-4o-mini/ })).toContainText('3,000')
  await expectAccessible(page, 'main')
  await capture(page, 'costs')

  // Without cost.view the API sends no money: the same view in tokens.
  await page.route(`**/api/v1/projects/${projectId}/usage`, async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    const strip = (r: Record<string, unknown>) => ({ ...r, costUsd: null, providerCostUsd: null })
    await route.fulfill({
      response,
      json: {
        ...body,
        costVisible: false,
        budgetUsd: null,
        total: strip(body.total),
        selfCorrection: strip(body.selfCorrection),
        byPhase: body.byPhase.map(strip),
        byAgent: body.byAgent.map(strip),
        byModel: body.byModel.map(strip),
      },
    })
  })
  await page.reload()
  await expect(page.getByText('You see tokens only: money needs the cost.view permission.')).toBeVisible()
  await expect(page.getByText('Tokens by phase')).toBeVisible()
  await expect(page.getByText('$0.45')).toHaveCount(0)
})
