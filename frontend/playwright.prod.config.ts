import { defineConfig } from '@playwright/test'

// Read-mostly checks against the PUBLIC deployment: no demo resets; only adds fictional records.
// Run: PROD_URL=https://curalink-rose.vercel.app npx playwright test -c playwright.prod.config.ts
export default defineConfig({
  testDir: './e2e-prod',
  timeout: 300_000,
  expect: { timeout: 30_000 },
  workers: 1,
  reporter: 'list',
  use: { baseURL: process.env.PROD_URL, channel: 'chrome', trace: 'retain-on-failure' },
})
