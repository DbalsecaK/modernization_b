import { defineConfig, devices } from '@playwright/test'

// End-to-end tests against the real API, Keycloak and OpenFGA (docker compose up + pnpm db:seed first).
// Servers already running (pnpm api:dev, pnpm web:dev) are reused; otherwise they are started here.
const API = 'http://127.0.0.1:8100'
const WEB = 'http://localhost:5173'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  timeout: 60_000,
  use: {
    baseURL: WEB,
    trace: 'retain-on-failure',
    locale: 'en-US',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'uv run uvicorn --factory nexti_api.main:create_app --host 127.0.0.1 --port 8100',
      cwd: '../..',
      url: `${API}/api/v1/health/live`,
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: 'pnpm dev --port 5173 --strictPort',
      url: WEB,
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
})
