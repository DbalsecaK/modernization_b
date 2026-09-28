import { expect, test, type Page } from '@playwright/test'
import { devSignIn, expectAccessible, signOut } from './support'

// Usage and costs against the real API (M1): budgets CRUD, and money hidden from who lacks cost.view.
const ORIGIN = 'http://localhost:5173'

async function csrf(page: Page) {
  const me = await (await page.request.get('/api/v1/me')).json()
  return { 'X-CSRF-Token': me.csrfToken as string, Origin: ORIGIN }
}

test('a tenant administrator sees costs and manages budgets', async ({ page }) => {
  await devSignIn(page, 'María Torres')
  // A budget left by an interrupted run would make the creation below a 409.
  const headers = await csrf(page)
  for (const b of await (await page.request.get('/api/v1/budgets')).json()) {
    if (String(b.projectName).startsWith('Branch Portal'))
      await page.request.delete(`/api/v1/budgets/${b.id}`, { headers })
  }
  await page.goto('/usage')
  await expect(page.getByText('Spend', { exact: true })).toBeVisible()
  await expect(page.getByText(/amounts in money need/)).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Budgets' })).toBeVisible()

  await page.getByRole('button', { name: 'New budget' }).click()
  const dialog = page.getByRole('dialog', { name: 'New budget' })
  await dialog.getByLabel('Scope').selectOption({ label: 'Branch Portal — ASPX to React + .NET 10' })
  await dialog.getByLabel('Period').selectOption('total')
  await dialog.getByLabel('Amount (USD)').fill('25')
  await expectAccessible(page, '[role="dialog"]')
  await dialog.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Budget saved.' })).toBeVisible()

  const row = page.getByRole('row').filter({ hasText: 'Branch Portal' })
  await expect(row).toContainText('$25.00')
  await row.getByRole('button', { name: /Edit budget of/ }).click()
  await page.getByRole('dialog', { name: 'Edit budget' }).getByLabel('Amount (USD)').fill('30')
  await page.getByRole('dialog', { name: 'Edit budget' }).getByRole('button', { name: 'Save changes' }).click()
  await expect(row).toContainText('$30.00')
  await expectAccessible(page, 'main')

  page.once('dialog', (confirm) => void confirm.accept())
  await row.getByRole('button', { name: /Delete budget of/ }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Budget deleted.' })).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: 'Branch Portal' })).toHaveCount(0)
})

test('without cost.view the page shows tokens and no money', async ({ page }) => {
  // María gives Luis (architect of one project) the tenant role "auditor": usage.view without cost.view.
  await devSignIn(page, 'María Torres')
  const headers = await csrf(page)
  const users = await (await page.request.get('/api/v1/users')).json()
  const roles = await (await page.request.get('/api/v1/roles')).json()
  const luis = users.find((u: { email: string }) => u.email === 'landrade@andesbank.example')
  const auditor = roles.find((r: { key: string }) => r.key === 'auditor')
  const granted = await page.request.post('/api/v1/role-assignments', {
    data: { userId: luis.id, roleId: auditor.id },
    headers,
  })
  expect(granted.status()).toBe(201)
  const assignmentId = (await granted.json()).id as string

  try {
    await signOut(page)
    await devSignIn(page, 'Luis Andrade')
    await page.goto('/usage')
    await expect(page.getByText(/amounts in money need/)).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Daily tokens' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Budgets' })).toHaveCount(0)
    const summary = await (await page.request.get('/api/v1/usage/summary?groupBy=model')).json()
    expect(summary.costVisible).toBe(false)
    expect(summary.total.costUsd).toBeNull()
    expect((await page.request.get('/api/v1/budgets')).status()).toBe(403)
    await expectAccessible(page, 'main')
  } finally {
    await signOut(page)
    await devSignIn(page, 'María Torres')
    const removed = await page.request.delete(`/api/v1/role-assignments/${assignmentId}`, {
      headers: await csrf(page),
    })
    expect(removed.status()).toBe(204)
  }
})
