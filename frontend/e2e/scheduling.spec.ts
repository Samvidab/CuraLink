import { expect, test } from '@playwright/test'
import { loginClinician, resetDemo, studentWithCalendar } from './helpers'

test.beforeEach(async ({ page }) => { await resetDemo(page); await studentWithCalendar(page) })

const card = (page: import('@playwright/test').Page, name: string) => page.locator('div.rounded-2xl', { has: page.getByRole('heading', { name: new RegExp(name) }) })

test('browse clinicians with real availability and book only after explicit confirmation', async ({ page }) => {
  await page.goto('/student/appointments')
  await expect(page.getByRole('tab', { name: 'All clinicians' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('heading', { name: /Dr\. Avery Rivera/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: /Dr\. Morgan Hale/ })).toBeVisible()
  await expect(page.getByText('DEMO').first()).toBeVisible()

  await page.getByRole('button', { name: /^Dr\. Avery Rivera, Monday, Oct 26 10:30 AM/ }).click()
  const dialog = page.getByRole('dialog')
  for (const t of ['Sam Lee', 'Dr. Avery Rivera', 'Routine checkup', 'Monday, October 26', '10:30 AM–11:00 AM', 'Demo Student Health Clinic', 'not booked with a real clinic']) await expect(dialog).toContainText(t)
  await expect(dialog.getByRole('button', { name: 'Confirm appointment' })).toBeDisabled()
  await dialog.getByLabel(/I want to book this simulated appointment/).check()
  await dialog.getByRole('button', { name: 'Confirm appointment' }).click()
  await expect(page.getByRole('heading', { name: 'Demo appointment booked' })).toBeVisible()

  await page.goto('/student/dashboard')
  await expect(page.getByText(/10:30 AM · Dr\. Avery Rivera, Demo Student Health Clinic/)).toBeVisible()
})

test('specific clinician and earliest-available views', async ({ page }) => {
  await page.goto('/student/appointments')
  await page.getByRole('tab', { name: 'Specific clinician' }).click()
  await page.getByLabel('Clinician').selectOption({ label: 'Dr. Morgan Hale — General Medicine' })
  await expect(page.getByRole('heading', { name: /Dr\. Morgan Hale/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: /Dr\. Avery Rivera/ })).toHaveCount(0)
  await page.getByRole('tab', { name: 'Earliest available' }).click()
  const list = page.getByRole('list', { name: 'Earliest openings' })
  await expect(list.getByRole('listitem').first()).toBeVisible()
})

test('a slot taken before confirmation is never silently rebooked', async ({ page }) => {
  await page.goto('/student/appointments')
  const chip = page.getByRole('button', { name: /^Dr\. Avery Rivera, Monday, Oct 26 10:30 AM/ })
  await chip.click()
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click()
  await page.getByText('Demo controls').click()
  await page.getByRole('button', { name: 'Mark selected slot as taken' }).click()
  await expect(page.getByRole('alert')).toContainText('another student just booked')
  await chip.click()
  await page.getByRole('dialog').getByLabel(/I want to book this simulated appointment/).check()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm appointment' }).click()
  await expect(page.getByRole('alert')).toContainText('just booked')
  await expect(chip).toHaveCount(0)
})

test('demo: Sam asks the assistant for doctors, books Dr. Rivera, and only Dr. Rivera sees it', async ({ page, browser }) => {
  test.setTimeout(120_000)
  await page.goto('/student/import')
  await page.getByLabel('Upload UniTime .ics file').setInputFiles('../sample_data/unitime_multiterm_sample.ics')
  await page.goto('/student/calendar')
  await expect(page.getByRole('tab', { name: 'Fall 2026' })).toHaveAttribute('aria-selected', 'true')

  await page.goto('/student/voice')
  await page.getByLabel('Message').fill('Which doctors are available?')
  await page.getByRole('button', { name: 'Send' }).click()
  const opts = page.getByLabel('Appointment options').last()
  await expect(opts.getByRole('heading', { name: /Dr\. Avery Rivera/ })).toBeVisible()
  await expect(opts.getByRole('heading', { name: /Dr\. Morgan Hale/ })).toBeVisible()

  await page.getByLabel('Message').fill('Can I see Dr. Rivera?')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByLabel('Appointment options')).toHaveCount(2)
  const rivera = page.getByLabel('Appointment options').last()
  await expect(rivera.getByRole('heading', { name: /Dr\. Morgan Hale/ })).toHaveCount(0)
  await rivera.getByRole('button', { name: /^Dr\. Avery Rivera, / }).first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Sam Lee')
  await dialog.getByLabel(/I want to book this simulated appointment/).check()
  await dialog.getByRole('button', { name: 'Confirm appointment' }).click()
  await expect(page.getByText(/Booked \(demo\): Dr\. Avery Rivera/)).toBeVisible()

  const rivDoc = await browser.newPage()
  await loginClinician(rivDoc, 'dr.rivera@clinic.example.com')
  await rivDoc.goto('/clinician/dashboard')
  await expect(rivDoc.getByText('Sam Lee').first()).toBeVisible()
  await rivDoc.close()

  const haleDoc = await browser.newPage()
  await loginClinician(haleDoc, 'dr.hale@clinic.example.com')
  await haleDoc.goto('/clinician/dashboard')
  await expect(haleDoc.getByText('Jordan Kim').first()).toBeVisible()
  await expect(haleDoc.getByText('Sam Lee')).toHaveCount(0)
  await haleDoc.close()
})
