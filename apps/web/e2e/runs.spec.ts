import { spawn, type ChildProcess } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'
import { devSignIn, expectAccessible, signOut } from './support'

// Runs against the real API and a real worker (M3): the tenant admin launches the demo pipeline from the Runs tab,
// cannot decide its gates (segregation of duties), another project owner approves them from My tasks, and the run
// finishes live, with the activity panel fed by the event stream. The worker uses apps/worker/.env and the local
// Docker sandbox.

let worker: ChildProcess | undefined

test.beforeAll(() => {
  worker = spawn('uv', ['run', '--no-sync', 'python', '-m', 'nexti_worker', 'e2e-worker'], {
    cwd: new URL('../../..', import.meta.url),
    stdio: 'ignore',
    shell: process.platform === 'win32',
  })
})

test.afterAll(() => {
  if (!worker?.pid) return
  if (process.platform === 'win32') spawn('taskkill', ['/pid', String(worker.pid), '/t', '/f'])
  else worker.kill('SIGKILL')
})

async function csrf(page: Page) {
  const me = await (await page.request.get('/api/v1/me')).json()
  return { 'X-CSRF-Token': me.csrfToken as string, Origin: 'http://localhost:5173' }
}

test('a run stops at its gates until another person approves them and then finishes', async ({ page }) => {
  test.setTimeout(240_000)
  await devSignIn(page, 'María Torres')
  const headers = await csrf(page)
  const name = `E2E Run ${Date.now()}`
  const created = await page.request.post('/api/v1/projects', {
    data: {
      name,
      flow: 'modernization',
      sources: ['cobol-cics', 'bms'],
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
  // Luis Andrade also owns the project: he may decide its gates.
  const roles = (await (await page.request.get('/api/v1/roles')).json()) as { id: string; key: string }[]
  const users = (await (await page.request.get('/api/v1/users')).json()) as { id: string; email: string }[]
  const assigned = await page.request.post('/api/v1/role-assignments', {
    data: {
      userId: users.find((u) => u.email === 'landrade@andesbank.example')!.id,
      roleId: roles.find((r) => r.key === 'projectOwner')!.id,
      projectId,
    },
    headers,
  })
  expect(assigned.status()).toBe(201)

  // Authorization tuples are published by the OpenFGA relay a moment after the commit.
  await expect
    .poll(async () => (await page.request.get(`/api/v1/projects/${projectId}`)).status(), { timeout: 30_000 })
    .toBe(200)
  await expect
    .poll(
      async () =>
        (
          (await (await page.request.get(`/api/v1/projects/${projectId}`)).json()) as {
            team: { email?: string; displayName: string }[]
          }
        ).team
          .map((m) => m.displayName)
          .includes('Luis Andrade'),
      { timeout: 30_000 },
    )
    .toBe(true)
  await page.goto(`/projects/${projectId}?tab=runs`)
  await page.getByRole('button', { name: 'Run demo pipeline' }).click()
  await expect(page.getByText('Waiting for the approval of a gate after Rule review.')).toBeVisible({ timeout: 90_000 })
  await expect(page.getByRole('heading', { name: 'Gate C1' })).toBeVisible()
  await expect(page.getByText(/someone else must decide its gates/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve' })).toBeDisabled()
  await expectAccessible(page, 'main')

  // The live panel shows the run's events.
  await page.getByRole('button', { name: 'Open agent activity' }).click()
  const panel = page.getByRole('dialog', { name: 'Agent activity' })
  await expect(panel.getByText('Gate C1 waiting for approval').first()).toBeVisible()
  await panel.getByRole('button', { name: 'Minimize' }).click()

  await signOut(page)
  await devSignIn(page, 'Luis Andrade')
  await page.goto('/tasks?tab=approvals')
  const task = page.getByRole('link').filter({ hasText: name }).filter({ hasText: 'Gate C1' })
  await expect(task).toBeVisible({ timeout: 30_000 })
  await task.click()
  await expect(page.getByRole('heading', { name: 'Gate C1' })).toBeVisible()
  await page.getByRole('button', { name: 'Approve' }).click()

  await expect(page.getByRole('heading', { name: 'Gate C4' })).toBeVisible({ timeout: 120_000 })
  await page.getByRole('textbox', { name: 'Comment (required to reject)' }).fill('Signed off in the E2E run')
  await page.getByRole('button', { name: 'Approve' }).click()
  await expect(page.getByText('Finished').first()).toBeVisible({ timeout: 60_000 })
  await expect(page.getByRole('row').filter({ hasText: 'module_a' }).first()).toBeVisible()
})
