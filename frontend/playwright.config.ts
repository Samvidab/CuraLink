import { defineConfig } from '@playwright/test'

// Expects the API (port 8000) and Vite (port 8443) to be running.
// Uses the locally installed Google Chrome; set PW_CHANNEL= to use bundled Chromium.
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  workers: 1,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8443',
    channel: process.env.PW_CHANNEL ?? 'chrome',
    headless: true,
    trace: 'retain-on-failure',
  },
})
