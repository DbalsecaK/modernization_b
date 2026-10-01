import { spawnSync } from 'node:child_process'
import { expect, test } from '@playwright/test'
import { capture, devSignIn, expectAccessible } from './support'

// Platform operations against the real API (P2), NexTI only: the workers with their heartbeat, the queues and the
// jobs that failed. Workers and jobs are Procrastinate's tables, so the test writes a live worker with a job, a queued
// job and a failed one (in a queue of its own, removed at the end).

// Reads MIGRATION_DATABASE_URL from apps/api/.env through the API's own settings (never printed).
const SEED = String.raw`
import asyncio, sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from nexti_api.settings import Settings

async def main(queue: str, action: str) -> None:
    engine = create_async_engine(Settings().migration_database_url.get_secret_value())
    try:
        async with engine.begin() as conn:
            if action == "clean":
                await conn.execute(text("DELETE FROM procrastinate_jobs WHERE queue_name = :q"), {"q": queue})
                return
            worker = (await conn.execute(text(
                "INSERT INTO procrastinate_workers (last_heartbeat) VALUES (now()) RETURNING id"))).scalar_one()
            await conn.execute(text(
                "INSERT INTO procrastinate_jobs (queue_name, task_name, args, status, worker_id) VALUES "
                "(:q, 'run_pipeline', '{}', 'doing', :w), (:q, 'run_pipeline', '{}', 'todo', NULL)"),
                {"q": queue, "w": worker})
            failed = (await conn.execute(text(
                "INSERT INTO procrastinate_jobs (queue_name, task_name, args, status, attempts) "
                "VALUES (:q, 'ui_change', '{}', 'failed', 3) RETURNING id"), {"q": queue})).scalar_one()
            await conn.execute(text("INSERT INTO procrastinate_events (job_id, type) VALUES (:j, 'failed')"),
                               {"j": failed})
    finally:
        await engine.dispose()

asyncio.run(main(sys.argv[1], sys.argv[2]))
`

function seed(queue: string, action: 'seed' | 'clean') {
  const result = spawnSync('uv', ['run', '--no-sync', 'python', '-', queue, action], {
    cwd: new URL('../../..', import.meta.url),
    input: SEED,
    encoding: 'utf8',
    shell: process.platform === 'win32',
  })
  expect(result.status, `seeding the queue failed (is the local stack up?)\n${result.stderr}`).toBe(0)
}

test('platform operations show workers, queues and failed jobs to NexTI operators only', async ({ page }) => {
  test.setTimeout(90_000)
  const queue = `e2e-${Date.now()}`
  seed(queue, 'seed')
  try {
    await devSignIn(page, 'Platform Admin')
    await page.goto('/platform')
    await expect(page.getByRole('heading', { name: 'Platform operations' })).toBeVisible()
    await expect(page.getByRole('row', { name: `${queue} 1 1` })).toBeVisible()
    await expect(page.getByRole('row', { name: /ui_change/ }).first()).toBeVisible()
    await expect(page.getByText('Busy').first()).toBeVisible()
    await expectAccessible(page, 'main')
    await capture(page, 'platform')
  } finally {
    seed(queue, 'clean')
  }
})
