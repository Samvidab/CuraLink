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

/** Dr. Rivera, Mon Oct 26 10:30–11:00 AM local: free in the sample calendar (see backend tests' RIVERA_MON_1030). */
export const RIVERA_MON_1030 = 'demo-clinician-1|2026-10-26T14:30Z|general_consultation'

export async function loginClinician(page: Page, email: string) {
  expect((await page.request.post('/api/v1/auth/login', { headers: H, data: { email, password: 'curalink-demo', expected_role: 'clinician' } })).ok()).toBeTruthy()
}
