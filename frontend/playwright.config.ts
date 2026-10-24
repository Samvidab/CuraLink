import { defineConfig } from '@playwright/test'

// Tests reset demo data, so run them on the isolated stack: `./run_demo.sh e2e` (ports 8011/8454, separate DB).
// E2E_BASE_URL overrides; never point this at a stack someone is using.
// Uses the locally installed Google Chrome; set PW_CHANNEL= to use bundled Chromium.
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  workers: 1,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8454',
    channel: process.env.PW_CHANNEL ?? 'chrome',
    headless: true,
    trace: 'retain-on-failure',
  },
})
