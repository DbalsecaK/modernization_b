import { expect, test } from '@playwright/test'
import { ACCOUNT, devPassword, expectAccessible, signOut } from './support'

// M0 acceptance: sign in with a local Keycloak account and sign out; no token ever reaches the browser.
const JWT = /eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\./
const TOKEN_FIELD = /"(access_token|refresh_token|id_token)"/

test('sign in with Keycloak, no token in the browser, sign out', async ({ page, context }) => {
  const exposed: string[] = []
  page.on('response', async (response) => {
    if (!response.url().startsWith('http://localhost:5173')) return
    const headers = JSON.stringify(await response.allHeaders())
    const body = response.request().resourceType() === 'fetch' ? await response.text().catch(() => '') : ''
    if (JWT.test(headers + body) || TOKEN_FIELD.test(body)) exposed.push(response.url())
  })

  await page.goto('/admin')
  await expect(page).toHaveURL(/\/login/)
  await expectAccessible(page)
  // Email first (M0b): without an identity provider for the domain, the BFF sends the person to Keycloak's page.
  await page.getByLabel('Work email').fill('landrade@andesbank.example')
  await page.getByRole('button', { name: 'Continue' }).click()

  await expect(page).toHaveURL(/localhost:8180\/realms\/nexti/)
  await page
    .getByLabel(/email|username/i)
    .first()
    .fill('landrade@andesbank.example')
  await page.getByLabel('Password', { exact: true }).fill(devPassword())
  await page.getByRole('button', { name: /sign in/i }).click()

  await expect(page).toHaveURL('http://localhost:5173/')
  await page.getByRole('button', { name: ACCOUNT }).click()
  await expect(page.getByText('landrade@andesbank.example')).toBeVisible()
  await expect(page.getByText('Signed in with your platform account')).toBeVisible()

  // Storage and JavaScript-visible cookies hold nothing; the session cookie is httpOnly and opaque.
  const storage = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }) + document.cookie)
  expect(storage).not.toMatch(JWT)
  expect(await page.evaluate(() => document.cookie)).not.toContain('nexti_session')
  const session = (await context.cookies()).find((c) => c.name === '__Host-nexti_session')
  expect(session?.httpOnly).toBe(true)
  expect(session?.secure).toBe(true)
  expect(session?.value).not.toMatch(JWT)

  await signOut(page)
  expect((await page.request.get('/api/v1/me')).status()).toBe(401)
  expect(exposed).toEqual([])
})

test('a Keycloak account without platform access is told so', async ({ page }) => {
  await page.goto('/login?error=no_platform_access')
  await expect(page.getByRole('alert')).toContainText('no access to the platform')
})
