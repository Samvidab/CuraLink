import { expect, type Page } from '@playwright/test'

export const H = { 'X-CuraLink-Client': 'web' }

export async function resetDemo(page: Page) {
  expect((await page.request.post('/api/v1/demo/reset', { headers: H })).ok()).toBeTruthy()
}

/** Signs in as the demo student via the API (shares the browser's cookies) and loads the sample calendar. */
export async function studentWithCalendar(page: Page) {
  expect((await page.request.post('/api/v1/auth/demo/login', { headers: H, data: { persona: 'student' } })).ok()).toBeTruthy()
  expect((await page.request.post('/api/v1/calendars/import-sample', { headers: H })).ok()).toBeTruthy()
}
