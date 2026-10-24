import { expect, test } from '@playwright/test'

test.beforeEach(async ({ request }) => {
  const r = await request.post('/api/v1/demo/reset', { headers: { 'X-CuraLink-Client': 'web' } })
  expect(r.ok()).toBeTruthy()
})

test('student onboarding imports the sample calendar and lands on a live dashboard', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/select-role/)
  await page.getByRole('button', { name: /I'm a student/ }).click()
  await expect(page).toHaveURL(/student\/sign-in/)
  // Regression: the email/password fields must accept typing (they were effectively read-only before).
  await page.getByLabel('Student email').fill('sam.lee@students.example.com')
  await expect(page.getByLabel('Student email')).toHaveValue('sam.lee@students.example.com')
  await page.getByLabel('Password').fill('not-the-password')
  await page.getByRole('button', { name: /Sign in to student portal/ }).click()
  await expect(page.getByRole('alert')).toContainText('incorrect')
  await page.getByLabel('Password').fill('curalink-demo')
  await page.getByLabel('Password').press('Enter')
  await expect(page.getByRole('heading', { name: 'Tell us about you' })).toBeVisible()
  await expect(page.getByText('sam.lee@students.example.com')).toBeVisible()
  await expect(page.getByLabel('Full name')).toHaveValue('Sam Lee')
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('button', { name: 'Use fictional sample calendar' }).click()
  await expect(page.getByText('DEMO SAMPLE')).toBeVisible()
  await expect(page.getByText('Contact needed', { exact: true })).toBeVisible() // PHIL 208: no invented email
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('button', { name: /Go to dashboard/ }).click()
  await expect(page).toHaveURL(/student\/dashboard/)
  await expect(page.getByText('MONDAY, OCTOBER 26')).toBeVisible()
  for (const code of ['CS 240', 'STAT 350', 'PHIL 208', 'COM 217']) await expect(page.getByText(code, { exact: false }).first()).toBeVisible()
  await expect(page.getByText('9:30 AM–10:20 AM')).toBeVisible()

  await page.getByRole('link', { name: 'Calendar' }).click()
  await page.getByRole('tab', { name: 'week' }).click()
  await expect(page.getByText('Moved')).toBeVisible() // RECURRENCE-ID override on Wed

  // Cross-role: a student can't open clinician screens (server also returns 403).
  await page.goto('/clinician/dashboard')
  await expect(page.getByText('403 · ACCESS DENIED')).toBeVisible()
})

test('clinician signs in with the demo account and sees only assigned encounters', async ({ page }) => {
  await page.goto('/select-role')
  await page.getByRole('button', { name: /healthcare professional/ }).click()
  await page.getByRole('button', { name: /Use demo clinician account/ }).click()
  await page.getByRole('button', { name: /Sign in to clinician portal/ }).click()
  await expect(page).toHaveURL(/clinician\/dashboard/)
  await expect(page.getByRole('heading', { name: /Dr\. Avery Rivera/ })).toBeVisible()
  await expect(page.getByText('Jordan Kim')).toBeVisible()
  await expect(page.getByText('Taylor Brooks')).toBeVisible()
  await page.getByText('Jordan Kim').click()
  await expect(page.getByRole('heading', { name: 'Medical Evaluation & Absence Determination' })).toBeVisible()
  await expect(page.getByRole('radio', { name: 'Approve an absence period' })).not.toBeChecked()
  await page.goto('/student/dashboard')
  await expect(page.getByText('403 · ACCESS DENIED')).toBeVisible()
})

test('a student account cannot enter the clinician portal, and vice versa', async ({ page }) => {
  await page.goto('/clinician/sign-in')
  await page.getByLabel('Professional email').fill('sam.lee@students.example.com')
  await page.getByLabel('Password').fill('curalink-demo')
  await page.getByRole('button', { name: /Sign in to clinician portal/ }).click()
  await expect(page.getByRole('alert')).toContainText("can't use the clinician portal")
  await page.goto('/student/sign-in')
  await page.getByLabel('Student email').fill('dr.rivera@clinic.example.com')
  await page.getByLabel('Password').fill('curalink-demo')
  await page.getByRole('button', { name: /Sign in to student portal/ }).click()
  await expect(page.getByRole('alert')).toContainText("can't use the student portal")
})

test('unverified clinician account is refused', async ({ page }) => {
  await page.goto('/clinician/sign-in')
  await page.getByLabel('Professional email').fill('pending.clinician@clinic.example.com')
  await page.getByLabel('Password').fill('curalink-demo')
  await page.getByRole('button', { name: /Sign in to clinician portal/ }).click()
  await expect(page.getByRole('alert')).toContainText('hasn’t been verified'.replace('’', "'"))
})
