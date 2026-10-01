import { expect, test, type Page } from '@playwright/test'
import { devSignIn, signOut } from './support'

// The demo projects of the local run (plan P1, `pnpm demo:seed`): every tab of each one has data, and the roles of
// the guide hold (María Torres sees everything; Luis Andrade, analyst, neither downloads code nor sees costs).
// Skipped where the demo data was not reproduced (CI starts from an empty database).

const DEMOS = {
  sybase: 'Demo · Pagos Sybase → Spring Boot',
  cics: 'Demo · Pagos COBOL/CICS → Spring Boot',
  frontend: 'Demo · Pagos frontend React y Angular',
}

async function demoIds(page: Page): Promise<Record<keyof typeof DEMOS, string> | null> {
  const projects = (await (await page.request.get('/api/v1/projects')).json()) as { id: string; name: string }[]
  const ids = Object.fromEntries(
    Object.entries(DEMOS).map(([key, name]) => [key, projects.find((p) => p.name === name)?.id]),
  )
  return Object.values(ids).every(Boolean) ? (ids as Record<keyof typeof DEMOS, string>) : null
}

test('the demo projects of the guide have every tab with data and the roles it describes', async ({ page }) => {
  test.setTimeout(180_000)
  await devSignIn(page, 'María Torres')
  const ids = await demoIds(page)
  test.skip(!ids, 'no demo data here: run pnpm demo:seed')
  if (!ids) return

  // Sybase → Spring Boot: the whole modernization, PROVEN.
  const sybase = `/projects/${ids.sybase}`
  await page.goto(`${sybase}?tab=validation`)
  await expect(
    page.getByRole('region', { name: 'Verdict of PayOrder' }).getByText('PROVEN', { exact: true }),
  ).toBeVisible()
  await page.goto(`${sybase}?tab=code`)
  await expect(page.getByRole('list', { name: 'Generated files' }).getByRole('button').first()).toBeVisible()
  await expect(page.getByRole('link', { name: 'Download zip' })).toBeVisible()
  await page.goto(`${sybase}?tab=architecture`)
  await expect(page.getByText('Application services')).toBeVisible()
  await page.goto(`${sybase}?tab=traceability`)
  await expect(page.getByRole('list', { name: 'Rules' }).getByRole('button').first()).toBeVisible()
  await page.goto(`${sybase}?tab=costs`)
  await expect(page.getByText('Cost by phase')).toBeVisible()
  await page.goto(`${sybase}?tab=runs`)
  await expect(page.getByText('Luis Andrade').first()).toBeVisible()

  // COBOL/CICS: the graph, the screens and prototypes, PARTLY PROVEN.
  const cics = `/projects/${ids.cics}`
  await page.goto(`${cics}?tab=validation`)
  await expect(
    page.getByRole('region', { name: 'Verdict of PayOrder' }).getByText('PARTLY PROVEN', { exact: true }),
  ).toBeVisible()
  await page.goto(`${cics}?tab=inventory`)
  await expect(page.getByRole('button', { name: 'PAGOORD · program' })).toBeVisible()
  await page.goto(`${cics}?tab=specification&view=screens`)
  await expect(page.getByRole('list', { name: 'Screens' }).getByRole('button').first()).toBeVisible()

  // Frontend: React and Angular, both PROVEN.
  await page.goto(`/projects/${ids.frontend}?tab=validation`)
  await expect(
    page.getByRole('region', { name: 'Verdict of frontend-react' }).getByText('PROVEN', { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('region', { name: 'Verdict of frontend-angular' }).getByText('PROVEN', { exact: true }),
  ).toBeVisible()

  // Luis Andrade, analyst: code without the zip, and no costs.
  await signOut(page)
  await devSignIn(page, 'Luis Andrade')
  await page.goto(`${sybase}?tab=code`)
  await expect(page.getByText('Downloading needs the code.download permission')).toBeVisible()
  await page.goto(`${sybase}?tab=costs`)
  await expect(page.getByText('Seeing usage needs the usage.view permission')).toBeVisible()
})
