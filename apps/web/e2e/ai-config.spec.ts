import { expect, test } from '@playwright/test'
import { devSignIn, expectAccessible } from './support'

// AI configuration against the real API (M1). No model is called here: the connection test only checks the key
// with the provider, and a made-up key is rejected (or the provider is unreachable), so it always ends in "Failed".
test.beforeEach(async ({ page }) => {
  await devSignIn(page, 'María Torres')
})

test('a connection keeps its API key out of the browser and can be tested and deleted', async ({ page }) => {
  await page.goto('/ai-config?tab=connections')
  const name = `E2E OpenRouter ${Date.now()}`
  const key = `sk-or-v1-e2e-${Date.now()}-not-a-real-key`

  await page.getByRole('button', { name: 'Add connection' }).click()
  const dialog = page.getByRole('dialog', { name: 'Add connection' })
  await dialog.getByLabel('Connection name').fill(name)
  await dialog.getByLabel('API key').fill(key)
  await expect(dialog.getByLabel('API key')).toHaveAttribute('type', 'password')
  await expectAccessible(page, '[role="dialog"]')
  await dialog.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByRole('status').filter({ hasText: name })).toBeVisible()

  const card = page.locator('div.rounded-lg', { hasText: name }).last()
  await expect(card.getByText('Stored in the secrets store')).toBeVisible()
  await expect(card.getByText('Not tested')).toBeVisible()
  const listed = await (await page.request.get('/api/v1/ai/connections')).text()
  expect(listed).not.toContain(key)
  expect(await page.content()).not.toContain(key)

  await card.getByRole('button', { name: 'Test connection' }).click()
  await expect(card.getByText('Failed')).toBeVisible({ timeout: 20_000 })
  await expectAccessible(page, 'main')

  page.once('dialog', (confirm) => void confirm.accept())
  await card.getByRole('button', { name: `Delete connection ${name}` }).click()
  await expect(page.getByRole('status').filter({ hasText: `Connection "${name}" deleted.` })).toBeVisible()
  await expect(page.getByText(name, { exact: true })).toHaveCount(0)
})

test('the policy is saved and survives a reload', async ({ page }) => {
  await page.goto('/ai-config?tab=policies')
  const zdr = page.getByRole('switch', { name: 'Require zero data retention (ZDR)' })
  const before = await zdr.getAttribute('aria-checked')
  await zdr.click()
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Policies saved.' })).toBeVisible()
  await page.reload()
  await expect(zdr).not.toHaveAttribute('aria-checked', before ?? '')
  await expectAccessible(page, 'main')

  // Leave the tenant as it was.
  await zdr.click()
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Policies saved.' }).last()).toBeVisible()
})

test('the assignment matrix lists every phase and agent role', async ({ page }) => {
  await page.goto('/ai-config?tab=assignment')
  await expect(page.getByRole('cell', { name: 'Rule extraction' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Profile · Verification' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Default profile of the customer' })).toBeVisible()
  await page.getByRole('button', { name: 'Resolve' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Profile used:' })).toBeVisible()
  await expectAccessible(page, 'main')
})

test('the catalog and pricing tabs render against the API', async ({ page }) => {
  await page.goto('/ai-config?tab=catalog')
  await expect(page.getByRole('button', { name: 'Sync with OpenRouter' })).toBeVisible()
  await expect(page.getByRole('switch', { name: 'Only models with providers loaded' })).toBeVisible()
  await expectAccessible(page, 'main')
  await page.getByRole('tab', { name: 'Profiles' }).click()
  await expect(page.getByRole('button', { name: 'New profile' })).toBeVisible()
  await expectAccessible(page, 'main')
})
