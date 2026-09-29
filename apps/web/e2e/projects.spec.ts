import { expect, test } from '@playwright/test'
import { devSignIn, expectAccessible, zipOf } from './support'

// Catalog and new-project wizard against the real API (M2): the deterministic proposal for CICS + BMS → Spring Boot
// + Angular + PostgreSQL + AWS, Control agents that cannot be removed, and a project created with its UI references.

// A 1×1 PNG (the upload goes through the real validation: type, header, ClamAV, hash).
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC',
  'base64',
)

test.beforeEach(async ({ page }) => {
  await devSignIn(page, 'María Torres')
})

test('the catalog shows the agents, the mandatory Control team and the skill files', async ({ page }) => {
  await page.goto('/catalog')
  await expect(page.getByText('Rules verifier')).toBeVisible()
  await expect(page.getByText('Mandatory')).toHaveCount(3)
  await expectAccessible(page, 'main')
  await page.getByRole('tab', { name: 'Skills' }).click()
  await page.getByRole('button', { name: 'BMS map parsing' }).click()
  const drawer = page.getByRole('dialog', { name: 'BMS map parsing' })
  await expect(drawer.getByText(/DFHMDF/).first()).toBeVisible()
  await expectAccessible(page, '[role="dialog"]')
})

test('the wizard proposes the team, keeps Control agents and creates the project', async ({ page }) => {
  await page.goto('/projects/new')
  const name = `E2E Cards ${Date.now()}`
  await page.getByLabel(/^Project name/).fill(name)
  await page.getByRole('button', { name: 'Next' }).click()

  // Source: CICS + BMS are preselected; a screenshot and a Figma link as UI references.
  await expect(page.getByRole('button', { name: 'COBOL CICS' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('button', { name: 'BMS maps' })).toHaveAttribute('aria-pressed', 'true')
  await page.getByLabel('Screenshots').setInputFiles({ name: 'login.png', mimeType: 'image/png', buffer: PNG })
  await page.getByPlaceholder(/figma\.com\/design/).fill('https://www.figma.com/design/AbCdEf1234567890/Card-Portal')
  await page.getByRole('button', { name: 'Add' }).first().click()
  await expectAccessible(page, 'main')
  await page.getByRole('button', { name: 'Next' }).click()

  // Target: the defaults are Spring Boot + Angular + PostgreSQL + AWS, with no compatibility issue.
  await expect(page.getByText('No compatibility issues for this combination.')).toBeVisible()
  await page.getByRole('button', { name: 'Next' }).click()

  // Agents: the deterministic proposal, with its reasons; Control agents cannot be unchecked.
  await expect(page.getByText('17 agents selected')).toBeVisible()
  await expect(page.getByRole('checkbox', { name: 'UI analyst' })).toHaveAttribute('aria-checked', 'true')
  await expect(page.getByRole('checkbox', { name: 'Functional analyst' })).toHaveAttribute('aria-checked', 'false')
  const judge = page.getByRole('checkbox', { name: 'Acceptance judge' })
  await expect(judge).toHaveAttribute('aria-disabled', 'true')
  await judge.click({ force: true })
  await expect(judge).toHaveAttribute('aria-checked', 'true')
  await expectAccessible(page, 'main')
  await page.getByRole('button', { name: 'Next' }).click()

  // Skills: the ones the source needs are recommended and active.
  await expect(page.getByRole('button', { name: /BMS map parsing/ })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('button', { name: /EXEC CICS commands/ }).first()).toHaveAttribute('aria-pressed', 'true')

  await page.getByRole('button', { name: /Review/ }).click()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await page.getByRole('button', { name: 'Create project' }).click()
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/, { timeout: 30_000 })

  const id = page.url().split('/').pop()!
  const project = await (await page.request.get(`/api/v1/projects/${id}`)).json()
  expect(project.name).toBe(name)
  expect(project.agents.map((a: { key: string }) => a.key)).toContain('acceptance-judge')
  const inputs = await (await page.request.get(`/api/v1/projects/${id}/inputs`)).json()
  expect(inputs.map((i: { kind: string; status: string }) => `${i.kind}:${i.status}`).sort()).toEqual([
    'figma_link:accepted',
    'screenshot:accepted',
  ])
})

test('the workspace shows the inputs with their validation and versions the configuration', async ({ page }) => {
  // A project from the API (the wizard itself is covered above).
  const me = await (await page.request.get('/api/v1/me')).json()
  const created = await page.request.post('/api/v1/projects', {
    data: {
      name: `E2E Workspace ${Date.now()}`,
      flow: 'modernization',
      sources: ['cobol-cics', 'bms'],
      target: {
        architecture: 'microservices-hexagonal',
        backend: 'spring-boot',
        frontend: 'angular',
        database: 'postgresql',
        cloud: 'aws',
      },
      pipelineTemplate: 'bankStandard',
    },
    headers: { 'X-CSRF-Token': me.csrfToken, Origin: 'http://localhost:5173' },
  })
  expect(created.status()).toBe(201)
  const id = (await created.json()).id as string

  await page.goto(`/projects/${id}`)
  await expect(page.getByText('Add the code, documents or UI references of the project.')).toBeVisible()
  await expectAccessible(page, 'main')

  // Inputs: a zip with path traversal is rejected with its reason; a clean one is accepted and versioned.
  await page.getByRole('tab', { name: 'Inputs' }).click()
  for (const [name, entries] of [
    ['evil.zip', { 'ok.cbl': 'MOVE 1 TO X.', '../../etc/passwd': 'x' }],
    ['card-system.zip', { 'src/CARD01.cbl': 'MOVE 1 TO X.' }],
  ] as const) {
    await page.getByRole('button', { name: 'Add input' }).click()
    const drawer = page.getByRole('dialog', { name: 'Add input' })
    await drawer.getByLabel('Drop files here or click to choose').setInputFiles({
      name,
      mimeType: 'application/zip',
      buffer: zipOf(entries),
    })
    await drawer.getByRole('button', { name: 'Start' }).click()
    if (name === 'evil.zip') {
      await expect(drawer.getByText('The zip has an entry that could escape its folder.')).toBeVisible()
      await drawer.getByRole('button', { name: 'Cancel' }).click()
    } else {
      await expect(drawer).toBeHidden()
    }
  }
  const evil = page.getByRole('row').filter({ hasText: 'evil.zip' })
  await expect(evil.getByText('Rejected')).toBeVisible()
  const good = page.getByRole('row').filter({ hasText: 'card-system.zip' })
  await expect(good.getByText('Accepted')).toBeVisible()
  await expect(good.getByText('v1')).toBeVisible()
  await expectAccessible(page, 'main')

  // Configuration: Control agents stay locked; a change is a new version.
  await page.getByRole('tab', { name: 'Settings' }).click()
  await page.getByRole('button', { name: 'Edit configuration' }).click()
  const drawer = page.getByRole('dialog', { name: 'Edit configuration' })
  await expect(drawer.getByRole('button', { name: 'Acceptance judge' })).toBeDisabled()
  await drawer.getByLabel(/^Autonomy/).selectOption('guided')
  await drawer.getByLabel(/^Reason for the change/).fill('Guided mode for the first wave')
  await expectAccessible(page, '[role="dialog"]')
  await drawer.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'New configuration version saved.' })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Guided mode for the first wave' })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'v2' })).toBeVisible()
})
