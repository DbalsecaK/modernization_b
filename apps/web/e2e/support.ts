import { readFileSync } from 'node:fs'
import { expect, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

// Password of the fictitious users of the dev realm: from the environment (CI) or the local Compose .env.
export function devPassword(): string {
  if (process.env.KC_DEV_USER_PASSWORD) return process.env.KC_DEV_USER_PASSWORD
  const env = readFileSync(new URL('../../../infra/docker-compose/.env', import.meta.url), 'utf8')
  const line = env.split(/\r?\n/).find((l) => l.startsWith('KC_DEV_USER_PASSWORD='))
  if (!line) throw new Error('KC_DEV_USER_PASSWORD not found')
  return line.slice('KC_DEV_USER_PASSWORD='.length)
}

// The user menu button, by its exact name in English or Spanish (the login page also mentions "account").
export const ACCOUNT = /^(Account & security|Cuenta y seguridad)$/

/** dev-auth: sign in as a seeded user from the login page (development and test only). */
export async function devSignIn(page: Page, name: string) {
  await page.goto('/login')
  await page.getByRole('button', { name: new RegExp(name) }).click()
  await expect(page.getByRole('button', { name: ACCOUNT })).toBeVisible()
}

export async function signOut(page: Page) {
  const button = page.getByRole('button', { name: /sign out|cerrar sesión/i })
  if (!(await button.isVisible())) await page.getByRole('button', { name: ACCOUNT }).click()
  await button.click()
  await expect(page).toHaveURL(/\/login/)
}

/** axe (WCAG 2.1 A/AA): no serious or critical violation inside `selector`. */
export async function expectAccessible(page: Page, selector?: string) {
  let builder = new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
  if (selector) builder = builder.include(selector)
  const { violations } = await builder.analyze()
  const serious = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  expect(serious.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(' ')).join(', ')})`)).toEqual([])
}
