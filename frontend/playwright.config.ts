/**
 * The confirm-flow end-to-end suite (Session T). Drives the real, built app
 * against the real backend — a real chore claimed, a real week, a real PIN —
 * because the defect this exists to guard against (the commit affordance
 * for a staged batch not being reachable from the section that stages it)
 * was invisible to every unit test in tests/, all of which call the
 * endpoint directly and never render the screen a parent actually uses.
 *
 * `webServer` runs e2e/start-server.mjs, which builds the bundle, seeds a
 * fresh scratch database, and starts uvicorn against it — everything in one
 * script, in shell order, because Playwright's own globalSetup/webServer
 * ordering turned out not to guarantee the database exists before the
 * server tries to open it.
 */

import { defineConfig, devices } from '@playwright/test'

import { BASE_URL } from './e2e/paths.mjs'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'node e2e/start-server.mjs',
    url: `${BASE_URL}/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
})
