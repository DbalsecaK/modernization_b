import { expect, test } from '@playwright/test'
import { devSignIn, expectAccessible } from './support'

// Administration against the real API, and accessibility of the migrated primitives (Drawer on Radix Dialog,
// Toggle on Radix Switch, Toast on Radix Toast, keyboard tabs) with axe (M0 acceptance, ADR-0003).
test.beforeEach(async ({ page }) => {
  await devSignIn(page, 'María Torres')
  await page.goto('/admin?tab=users')
})

test('the menu and the tabs follow the permissions', async ({ page }) => {
  await expect(page.getByRole('link', { name: 'Administration' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Platform operations' })).toHaveCount(0)
  await expect(page.getByRole('tab', { name: 'Customers' })).toHaveCount(0)
  await expect(page.getByRole('cell', { name: /cruiz@nexti.example/ })).toBeVisible()
  await expectAccessible(page, 'main')
})

test('tabs are reachable and movable with the keyboard', async ({ page }) => {
  const users = page.getByRole('tab', { name: 'Users' })
  await users.focus()
  await page.keyboard.press('ArrowRight')
  await expect(page.getByRole('tab', { name: 'Roles & permissions' })).toBeFocused()
  await expect(page.getByRole('tab', { name: 'Roles & permissions' })).toHaveAttribute('aria-selected', 'true')
  await expect(page).toHaveURL(/tab=roles/)
  await expectAccessible(page, '[role="tablist"]')
})

test('the drawer traps focus, closes with Escape and returns focus', async ({ page }) => {
  const invite = page.getByRole('button', { name: 'Invite user' })
  await invite.click()
  const dialog = page.getByRole('dialog', { name: 'Invite user' })
  await expect(dialog).toBeVisible()
  await expect(dialog)
    .toBeFocused({ timeout: 2000 })
    .catch(async () => {
      await expect(dialog.locator(':focus')).toHaveCount(1)
    })
  for (let i = 0; i < 12; i++) await page.keyboard.press('Tab')
  await expect(dialog.locator(':focus')).toHaveCount(1)
  await expectAccessible(page, '[role="dialog"]')
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(invite).toBeFocused()
})

test('creating a role shows an accessible toast and the matrix saves', async ({ page }) => {
  await page.getByRole('tab', { name: 'Roles & permissions' }).click()
  await page.getByRole('button', { name: 'New role' }).click()
  const name = `E2E reviewer ${Date.now()}`
  await page.getByLabel('Role name').fill(name)
  await page.getByRole('dialog').getByRole('button', { name: 'Create role' }).click()
  const toast = page.getByRole('status').filter({ hasText: name })
  await expect(toast).toBeVisible()
  await expectAccessible(page, 'ol, [role="region"]')

  const cell = page.getByRole('button', { name: `code.view · ${name}` })
  await cell.click()
  await expect(cell).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByRole('status').filter({ hasText: /saved/i })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('button', { name: `code.view · ${name}` })).toHaveAttribute('aria-pressed', 'true')
})

test('switches toggle with the keyboard and pass axe', async ({ page }) => {
  await page.getByRole('tab', { name: 'Authentication' }).click()
  // The tenant's sign-in settings come from the API (M0b); toggling does not save until "Save".
  const mfa = page.getByRole('switch', { name: 'Require MFA for every user' })
  const before = await mfa.getAttribute('aria-checked')
  await mfa.focus()
  await page.keyboard.press('Space')
  await expect(mfa).not.toHaveAttribute('aria-checked', before ?? '')
  await expectAccessible(page, 'main')
})

test('the audit log lists the actions and verifies the chain', async ({ page }) => {
  // An auditable action in the tenant (sign-in events go to the platform chain, not the tenant's).
  const me = await (await page.request.get('/api/v1/me')).json()
  const switched = await page.request.put('/api/v1/session/tenant', {
    data: { tenantId: me.activeTenant.id },
    headers: { 'X-CSRF-Token': me.csrfToken, Origin: 'http://localhost:5173' },
  })
  expect(switched.status()).toBe(200)
  await page.getByRole('tab', { name: 'Audit log' }).click()
  await expect(page.getByRole('cell', { name: /session\.tenant_switch/ }).first()).toBeVisible()
  await page.getByRole('button', { name: 'Verify chain' }).click()
  await expect(page.getByText(/The chain is intact/)).toBeVisible()
})

test('a member gets a project role and loses it again', async ({ page }) => {
  await page.getByRole('button', { name: 'Assign role Carlos Ruiz' }).click()
  const dialog = page.getByRole('dialog', { name: 'Assign a role to Carlos Ruiz' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('combobox').first().selectOption({ label: 'Business reviewer' })
  await dialog.getByRole('combobox').nth(1).selectOption({ index: 1 }) // the project, once the role is per project
  await expectAccessible(page, '[role="dialog"]')
  await dialog.getByRole('button', { name: 'Assign role' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Role assigned to Carlos Ruiz.' })).toBeVisible()

  const remove = page.getByRole('button', { name: /^Remove the role Business reviewer · .+ from Carlos Ruiz$/ }).first()
  page.once('dialog', (confirm) => void confirm.accept())
  await remove.click()
  await expect(page.getByRole('status').filter({ hasText: 'Role removed.' })).toBeVisible()
})
