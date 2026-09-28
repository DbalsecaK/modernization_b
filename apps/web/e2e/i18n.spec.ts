import { expect, test } from '@playwright/test'
import { devSignIn, signOut } from './support'

// M0 acceptance: the web starts in English; switching to Spanish persists across sessions (server-side).
test('starts in English and the Spanish preference follows the user', async ({ page, browser }) => {
  await page.goto('/login')
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()

  await devSignIn(page, 'Carlos Ruiz')
  await page.getByRole('group', { name: 'Language' }).getByRole('button', { name: 'es' }).click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'es')
  await expect(page.getByRole('link', { name: 'Proyectos' })).toBeVisible()
  // The preference is saved on the server before signing out.
  await expect.poll(async () => (await (await page.request.get('/api/v1/me')).json()).user.locale).toBe('es')
  await signOut(page)

  // Another browser (no local storage): after signing in, Spanish comes from the server.
  const other = await browser.newContext({ locale: 'en-US' })
  const fresh = await other.newPage()
  await devSignIn(fresh, 'Carlos Ruiz')
  await expect(fresh.locator('html')).toHaveAttribute('lang', 'es')
  await expect(fresh.getByRole('link', { name: 'Proyectos' })).toBeVisible()

  // Back to English for the next runs.
  await fresh.getByRole('group', { name: 'Idioma' }).getByRole('button', { name: 'en' }).click()
  await expect.poll(async () => (await (await fresh.request.get('/api/v1/me')).json()).user.locale).toBe('en')
  await other.close()
})
