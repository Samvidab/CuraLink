import { expect, test } from '@playwright/test'
import { H, loginClinician, resetDemo, studentWithCalendar } from './helpers'

test.beforeEach(async ({ page }) => { await resetDemo(page) })

test('two conversations → separate approved summaries → book Dr. Rivera from chat → Rivera sees history; Hale cannot', async ({ page, browser }) => {
  test.setTimeout(300_000)
  await studentWithCalendar(page) // Sam Lee + fictional Fall 2026 UniTime calendar
  await page.goto('/student/voice')
  const send = async (t: string) => { await page.getByLabel('Message').fill(t); await page.getByRole('button', { name: 'Send' }).click() }
  const bot = page.locator('div.border-slate-200.bg-white.text-slate-700')
  const knows = page.locator('section', { has: page.getByRole('heading', { name: 'What CuraLink knows' }) })
  const confirmAll = async () => { for (const box of await knows.getByRole('checkbox').all()) if (!(await box.isChecked())) await box.check() }

  // ---- Session 1: skin concern + HEIC photo, approved before any booking
  await page.getByRole('button', { name: 'Start new conversation' }).first().click()
  await send('I have a rash on my arm')
  const photoCard = page.getByRole('group', { name: 'Optional photo' })
  await expect(photoCard).toBeVisible()
  await expect(page.getByRole('group', { name: 'Temperature entry' })).toHaveCount(0)
  await photoCard.getByRole('button', { name: 'Add a photo' }).click()
  const drawer = page.getByRole('dialog')
  await drawer.getByLabel(/I agree to have this photo analyzed/).check()
  await drawer.getByLabel('Choose a photo from your files or photo library').setInputFiles('../sample_data/demo_images/synthetic_red_area.heic')
  await expect(drawer.getByAltText(/Your uploaded photo/)).toBeVisible()
  await drawer.getByRole('button', { name: 'Cancel' }).click()
  await confirmAll()
  await knows.getByRole('button', { name: 'Review your pre-visit summary' }).click()
  let dialog = page.getByRole('dialog')
  await dialog.getByLabel(/Share this photo/).check()
  await dialog.getByLabel(/I authorize sharing/).check()
  await dialog.getByRole('button', { name: 'Submit pre-visit summary' }).click()
  await expect(dialog).toContainText('shared with the clinician you book your next appointment with')
  await dialog.getByRole('button', { name: 'Done' }).click()

  // ---- Session 2: fever + absence request; nothing from session 1 carries over
  await page.getByRole('button', { name: 'Start new conversation' }).first().click()
  await expect(bot).toHaveCount(1)
  await expect(knows.getByText('Nothing yet.')).toBeVisible()
  await send("I've had a fever and headache since yesterday. I missed class and want to discuss an absence note.")
  const temp = page.getByRole('group', { name: 'Temperature entry' })
  await expect(temp).toBeVisible()
  await expect(page.getByRole('group', { name: 'Optional photo' })).toHaveCount(0)
  await temp.getByLabel('Measured temperature').fill('100.8')
  await temp.getByRole('button', { name: 'Save temperature' }).click()
  await expect(knows.getByText('100.8°F')).toBeVisible()
  await expect(knows.getByText(/rash/i)).toHaveCount(0)
  await confirmAll()
  await knows.getByRole('button', { name: 'Review your pre-visit summary' }).click()
  dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Photos: none provided')
  await expect(dialog.getByLabel(/absence documentation/i).first()).toBeChecked()
  await dialog.getByLabel(/I authorize sharing/).check()
  await dialog.getByRole('button', { name: 'Submit pre-visit summary' }).click()
  await expect(dialog).toContainText('Pre-visit summary submitted')
  await dialog.getByRole('button', { name: 'Done' }).click()

  await send('Which doctors are available?')
  const all = page.getByLabel('Appointment options').last()
  await expect(all.getByRole('heading', { name: /Dr\. Avery Rivera/ })).toBeVisible()
  await expect(all.getByRole('heading', { name: /Dr\. Morgan Hale/ })).toBeVisible()
  await send('Can I see Dr. Rivera?')
  await expect(page.getByLabel('Appointment options')).toHaveCount(2)
  const rivera = page.getByLabel('Appointment options').last()
  await expect(rivera.getByRole('heading', { name: /Dr\. Morgan Hale/ })).toHaveCount(0)
  await rivera.getByRole('button', { name: /^Dr\. Avery Rivera, / }).first().click()
  dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Sam Lee')
  await expect(dialog.getByLabel(/discuss absence documentation/)).toBeChecked()
  await dialog.getByLabel(/I want to book this simulated appointment/).check()
  await dialog.getByRole('button', { name: 'Confirm appointment' }).click()
  await expect(page.getByText(/Booked \(demo\): Dr\. Avery Rivera/)).toBeVisible()
  const sessions = (await (await page.request.get('/api/v1/students/me/previsit-summaries', { headers: H })).json()) as { session_id: string; encounter_id: string | null }[]
  expect(new Set(sessions.map(s => s.session_id)).size).toBe(2)
  expect(new Set(sessions.map(s => s.encounter_id)).size).toBe(1) // both attached to the same booked case
  await page.request.post('/api/v1/auth/logout', { headers: H })

  // ---- Dr. Rivera: new session, sees the appointment, latest summary and per-session history
  const doc = await browser.newPage()
  await loginClinician(doc, 'dr.rivera@clinic.example.com')
  await doc.goto('/clinician/dashboard')
  await doc.getByText('Sam Lee').first().click()
  const caseUrl = doc.url()
  await expect(doc.getByRole('heading', { name: 'AI-Assisted Pre-Visit Summary — Student-Reported Information' })).toBeVisible()
  const summary = doc.locator('section[aria-labelledby="pvs-title"]')
  await expect(summary.getByText('100.8°F').first()).toBeVisible()
  await expect(summary.getByText('Requested — not medically approved').first()).toBeVisible()
  await expect(summary.getByText(/rash/i)).toHaveCount(0)
  await expect(doc.getByRole('heading', { name: 'AI-Assisted Pre-Visit Notes', exact: true })).toBeVisible()
  const history = doc.locator('section[aria-labelledby="history-title"]')
  await expect(history.getByRole('button', { name: /Session 2/ })).toBeVisible()
  await expect(history.getByText('Latest approved')).toBeVisible()
  await history.getByRole('button', { name: /Session 1/ }).click()
  await expect(history.getByText(/rash on my arm/i).first()).toBeVisible()
  await expect(history.getByAltText(/Student-approved photo/)).toBeVisible()
  await expect(history.getByRole('heading', { level: 4 })).toHaveCount(1) // same day: one date group, two separate sessions
  await expect(doc.getByRole('heading', { name: 'Absence determination', exact: true })).toBeVisible() // the clinician decides independently
  await doc.close()

  // ---- Dr. Hale: no access to Sam's case
  const hale = await browser.newPage()
  await loginClinician(hale, 'dr.hale@clinic.example.com')
  await hale.goto('/clinician/dashboard')
  await expect(hale.getByText('Jordan Kim').first()).toBeVisible()
  await expect(hale.getByText('Sam Lee')).toHaveCount(0)
  const encId = caseUrl.split('/').pop()
  expect((await hale.request.get(`/api/v1/clinician/encounters/${encId}/previsit-history`, { headers: H })).status()).toBe(403)
  await hale.close()
})
