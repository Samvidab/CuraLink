import { expect, test, type APIRequestContext } from '@playwright/test'
import { H, RIVERA_MON_1030, loginClinician, resetDemo, studentWithCalendar } from './helpers'

test.beforeEach(async ({ page }) => { await resetDemo(page) })

const ok = async (r: Awaited<ReturnType<APIRequestContext['post']>>) => { expect(r.ok(), await r.text()).toBeTruthy(); return r.json() }

test('confirmed real-looking contacts: clear statuses, signed version delivered to the isolated test inbox, same view for both portals', async ({ page, browser }) => {
  test.setTimeout(180_000)
  // --- Student (API setup): booking, real-looking instructor emails confirmed one by one, request with consent.
  await studentWithCalendar(page)
  await ok(await page.request.post('/api/v1/appointments/confirm', { headers: H, data: { slot_id: RIVERA_MON_1030, student_approved: true, idempotency_key: 'e2e-delivery-01' } }))
  const dash = await (await page.request.get('/api/v1/students/me/dashboard', { headers: H })).json()
  for (const c of dash.courses as { id: string; code: string }[])
    await ok(await page.request.patch(`/api/v1/courses/${c.id}/contact`, { headers: H, data: { instructor_email: `${c.code.replace(' ', '').toLowerCase()}@purdue.edu`, confirm: true } }))
  const enc = (await (await page.request.get('/api/v1/students/me/encounters', { headers: H })).json())[0]
  const kase = await ok(await page.request.post('/api/v1/absence-cases', { headers: H, data: { encounter_id: enc.id, disclosure_consent: true } }))

  // --- Clinician (API): decide dates, generate, sign.
  const doc = await browser.newPage()
  await loginClinician(doc, 'dr.rivera@clinic.example.com')
  await ok(await doc.request.post('/api/v1/clinician/signature-assets', { headers: H }))
  await ok(await doc.request.post(`/api/v1/clinician/absence-cases/${kase.id}/decision`, { headers: H, data: { decision: 'CERTIFY', start_date: '2026-10-27', end_date: '2026-10-28' } }))
  const rendered = await ok(await doc.request.post(`/api/v1/clinician/absence-cases/${kase.id}/render`, { headers: H, data: {} }))
  const req = await ok(await doc.request.post(`/api/v1/clinician/documents/${rendered.document.id}/sign-request`, { headers: H }))
  await ok(await doc.request.post(`/api/v1/clinician/documents/${rendered.document.id}/approve-sign`, { headers: H, data: { nonce: req.nonce, document_sha256: req.document_sha256, recipient_courses: req.recipients.map((r: { course_code: string }) => r.course_code), password: 'curalink-demo', confirm: true } }))

  // --- Clinician UI: precise statuses, no "student must confirm" or "sign again".
  await doc.goto(`/clinician/encounters/${enc.id}`)
  const status = doc.getByRole('region', { name: 'Delivery status' })
  await expect(status).toContainText('Clinician approved and signed (version 1)')
  await expect(status).toContainText('Student consent confirmed')
  await expect(status).toContainText('Instructor contacts confirmed')
  await expect(status).toContainText('Demo delivery ready — to the isolated test inbox')
  await expect(status.getByText('Confirmed by student').first()).toBeVisible()
  await expect(status.getByText('Simulated — real address not contacted').first()).toBeVisible()
  await expect(doc.getByText(/student must confirm these contacts/)).toHaveCount(0)
  await doc.getByRole('button', { name: 'Send authorized copies (test inbox)' }).click()
  await expect(status).toContainText('Simulated delivery completed')
  await expect(doc.getByText(/not contacted/).first()).toBeVisible()
  await expect(doc.getByText('Version 1 · signed (simulated)')).toBeVisible() // same signed version; no re-signing
  await doc.goto('/demo/inbox')
  await expect(doc.getByText(/@test-inbox\.example\.com/).first()).toBeVisible()
  await expect(doc.getByText(/Simulated copy for .*@purdue\.edu — that address was not contacted/).first()).toBeVisible()
  await doc.close()

  // --- Student, new session: the same persisted statuses.
  await page.request.post('/api/v1/auth/logout', { headers: H })
  await page.request.post('/api/v1/auth/login', { headers: H, data: { email: 'sam.lee@students.example.com', password: 'curalink-demo', expected_role: 'student' } })
  await page.goto('/student/cases')
  const mine = page.getByRole('region', { name: 'Delivery status' }).first()
  await expect(mine).toContainText('Simulated delivery completed')
  await expect(mine.getByText('Confirmed by student').first()).toBeVisible()
})

test('a missing student confirmation is named precisely, with a fix for the student', async ({ page, browser }) => {
  test.setTimeout(180_000)
  await studentWithCalendar(page) // sample calendar: PHIL 208 (Tue/Thu) has no instructor email
  await ok(await page.request.post('/api/v1/appointments/confirm', { headers: H, data: { slot_id: RIVERA_MON_1030, student_approved: true, idempotency_key: 'e2e-delivery-02' } }))
  const enc = (await (await page.request.get('/api/v1/students/me/encounters', { headers: H })).json())[0]
  const kase = await ok(await page.request.post('/api/v1/absence-cases', { headers: H, data: { encounter_id: enc.id, disclosure_consent: true } }))
  const doc = await browser.newPage()
  await loginClinician(doc, 'dr.rivera@clinic.example.com')
  await ok(await doc.request.post('/api/v1/clinician/signature-assets', { headers: H }))
  await ok(await doc.request.post(`/api/v1/clinician/absence-cases/${kase.id}/decision`, { headers: H, data: { decision: 'CERTIFY', start_date: '2026-10-27', end_date: '2026-10-28' } }))
  const rendered = await ok(await doc.request.post(`/api/v1/clinician/absence-cases/${kase.id}/render`, { headers: H, data: {} }))
  const req = await ok(await doc.request.post(`/api/v1/clinician/documents/${rendered.document.id}/sign-request`, { headers: H }))
  await ok(await doc.request.post(`/api/v1/clinician/documents/${rendered.document.id}/approve-sign`, { headers: H, data: { nonce: req.nonce, document_sha256: req.document_sha256, recipient_courses: req.recipients.map((r: { course_code: string }) => r.course_code), password: 'curalink-demo', confirm: true } }))
  await doc.goto(`/clinician/encounters/${enc.id}`)
  const status = doc.getByRole('region', { name: 'Delivery status' })
  await expect(status).toContainText('Student confirmation missing')
  await expect(status).toContainText('add and confirm an instructor email for PHIL 208')
  await expect(status.getByText('No address on file')).toBeVisible()
  await expect(status.getByText('Simulated — real address not contacted')).toHaveCount(0)
  await expect(doc.getByRole('button', { name: 'Send authorized copies (test inbox)' })).toHaveCount(0)
  await doc.close()

  await page.goto('/student/cases')
  await expect(page.getByText('These instructor emails still need your confirmation:')).toBeVisible()
  await expect(page.getByLabel('Instructor email for PHIL 208')).toBeVisible()
})
