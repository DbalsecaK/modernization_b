import { expect, test } from '@playwright/test'
import { devSignIn, expectAccessible } from './support'

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
