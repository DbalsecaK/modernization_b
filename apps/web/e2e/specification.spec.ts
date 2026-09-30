import { spawnSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'
import { capture, devSignIn, expectAccessible } from './support'

// The Specification tab against the real API (M4): the rules the agents extracted, the user stories, and the live
// Gherkin validation of the server while a person edits a story. Rules only come from the pipeline (there is no API
// to write them), so the test seeds two rule cards and plan version 1 directly in the local database with the schema
// owner, the way the API's integration tests do; the stories are created through the real API.

const VALID = 'Scenario: Pay a pending order\n  Given a pending order\n  When it is paid\n  Then it is marked A'

// Reads MIGRATION_DATABASE_URL from apps/api/.env through the API's own settings (never printed).
const SEED = String.raw`
import asyncio, json, sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from nexti_api.settings import Settings

RULES = [
    {"id": "RULE-001", "name": "Only pending orders can be paid", "domain": "payments", "category": "validation",
     "priority": "P0", "statement": "An order can be paid only while its status is pending.",
     "scenarios": ["Scenario: Pay a pending order\n  Given an order with status P\n  When it is paid\n  Then its status is A"],
     "confidence": "high", "sme_question": "Can a cancelled order be paid again?",
     "sources": [{"file": "sp_pago_orden.sp", "line_start": 40, "line_end": 42}]},
    {"id": "RULE-002", "name": "Payment amount must match the order", "domain": "payments", "category": "validation",
     "priority": "P1", "statement": "The amount paid must equal the order total.",
     "suspected_defect": "Rounding is done with FLOAT", "confidence": "medium",
     "sources": [{"file": "sp_pago_orden.sp", "line_start": 55, "line_end": 60}]},
]

async def main(project_id: str) -> None:
    engine = create_async_engine(Settings().migration_database_url.get_secret_value())
    try:
        async with engine.begin() as conn:
            tenant = (await conn.execute(text("SELECT tenant_id FROM project WHERE id = :p"), {"p": project_id})).scalar_one()
            for rule in RULES:
                await conn.execute(
                    text("INSERT INTO spec_element (tenant_id, project_id, element_type, key, version, status, data) "
                         "VALUES (:t, :p, 'rule', :k, 1, 'review', CAST(:d AS jsonb))"),
                    {"t": tenant, "p": project_id, "k": rule["id"], "d": json.dumps(rule)},
                )
            await conn.execute(
                text("INSERT INTO migration_plan (tenant_id, project_id, version, waves, suggested) "
                     "VALUES (:t, :p, 1, CAST('[]' AS jsonb), CAST('[]' AS jsonb))"),
                {"t": tenant, "p": project_id},
            )
    finally:
        await engine.dispose()

asyncio.run(main(sys.argv[1]))
`

function seedSpec(projectId: string) {
  const result = spawnSync('uv', ['run', '--no-sync', 'python', '-', projectId], {
    cwd: new URL('../../..', import.meta.url),
    input: SEED,
    encoding: 'utf8',
    shell: process.platform === 'win32',
  })
  expect(result.status, 'seeding the spec rows failed (is the local stack up?)').toBe(0)
}

async function csrf(page: Page) {
  const me = await (await page.request.get('/api/v1/me')).json()
  return { 'X-CSRF-Token': me.csrfToken as string, Origin: 'http://localhost:5173' }
}

test('the specification tab shows the rules and stories and validates Gherkin live on the server', async ({ page }) => {
  test.setTimeout(120_000)
  await devSignIn(page, 'María Torres')
  const headers = await csrf(page)
  const created = await page.request.post('/api/v1/projects', {
    data: {
      name: `E2E Spec ${Date.now()}`,
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
    headers,
  })
  expect(created.status()).toBe(201)
  const projectId = (await created.json()).id as string
  // Authorization tuples are published by the OpenFGA relay a moment after the commit.
  await expect
    .poll(async () => (await page.request.get(`/api/v1/projects/${projectId}`)).status(), { timeout: 30_000 })
    .toBe(200)

  // Before the pipeline: the empty state points to the runs.
  await page.goto(`/projects/${projectId}?tab=specification`)
  await expect(page.getByText('No business rules yet')).toBeVisible()

  seedSpec(projectId)
  for (const [title, link] of [
    ['Pay a pending order', 'RULE-001'],
    ['Check the amount paid', 'RULE-002'],
  ]) {
    const story = await page.request.post(`/api/v1/projects/${projectId}/stories`, {
      data: {
        title,
        feature: 'Payments',
        narrative: 'As a cashier, I want to pay orders.',
        criteria: [VALID],
        links: [link],
      },
      headers,
    })
    expect(story.status()).toBe(201)
  }

  // Rules: list and detail with the citation, the scenarios and the question for the SME.
  await page.reload()
  await expect(page.getByRole('tab', { name: /Rules/ })).toHaveAttribute('aria-selected', 'true')
  const detail = page.getByRole('heading', { name: /RULE-001 · Only pending orders can be paid/ })
  await expect(detail).toBeVisible()
  await expect(page.getByText('sp_pago_orden.sp:40-42')).toBeVisible()
  await expect(page.getByText('Can a cancelled order be paid again?')).toBeVisible()
  await expectAccessible(page, 'main')
  await capture(page, 'spec-rules')
  await page.getByRole('button', { name: /Payment amount must match the order/ }).click()
  await expect(page.getByText('Rounding is done with FLOAT')).toBeVisible()

  // Stories: list and detail, then the editor with the server's live Gherkin validation.
  await page.getByRole('tab', { name: /User stories/ }).click()
  await expect(page.getByRole('heading', { name: /US-001.*Pay a pending order/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Check the amount paid/ })).toBeVisible()
  await expectAccessible(page, 'main')
  await capture(page, 'spec-stories')

  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  const drawer = page.getByRole('dialog', { name: 'Edit US-001' })
  await expect(drawer).toBeVisible()
  const criteria = drawer.getByRole('textbox', { name: /Acceptance criteria/ })
  const validated = page.waitForResponse(
    (r) => r.url().endsWith('/api/v1/gherkin:validate') && r.request().method() === 'POST',
  )
  await criteria.fill('Scenario: Broken\n  When it is paid\n  Then it is marked A')
  const response = await validated
  expect(response.status()).toBe(200)
  await expect(drawer.getByText('Missing a Given step (the starting situation).')).toBeVisible()
  await expect(drawer.getByRole('button', { name: 'Save' })).toBeDisabled()
  await expectAccessible(page, '[role="dialog"]')
  await capture(page, 'spec-gherkin-live')

  await criteria.fill(VALID)
  await expect(drawer.getByText('1 scenario, valid Gherkin')).toBeVisible()
  await drawer.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByText('Story saved', { exact: true })).toBeVisible()
  await expect(page.getByText('v2', { exact: true })).toBeVisible()

  // Plan: the stories the server placed in the plan's waves. US-002 depends hard on US-001: moving US-001 after it
  // is rejected by the server, with the reason.
  const dependency = await page.request.post(`/api/v1/projects/${projectId}/stories/US-002/dependencies`, {
    data: { on: 'US-001', strength: 'hard', reason: 'reads the payment row' },
    headers,
  })
  expect(dependency.status()).toBe(201)
  await page.getByRole('tab', { name: /Migration plan/ }).click()
  await expect(page.getByRole('region', { name: 'Wave 1' }).getByText('US-001')).toBeVisible()
  await expectAccessible(page, 'main')
  await capture(page, 'spec-plan')
  await page.getByRole('button', { name: 'Move US-001 to the next wave' }).click()
  await expect(page.getByText('Move of US-001 rejected: it would come before a hard dependency')).toBeVisible()
  await expect(page.getByText('US-002 cannot come before US-001.').first()).toBeVisible()
  await page.getByRole('button', { name: 'Move US-002 to the next wave' }).click()
  await expect(page.getByText('Plan saved (version 2)', { exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Wave 2' }).getByText('US-002')).toBeVisible()
})
