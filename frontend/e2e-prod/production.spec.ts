import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { ConvexHttpClient } from 'convex/browser'

const H = { 'X-CuraLink-Client': 'web' }
const CONVEX_URL = process.env.PROD_CONVEX_URL ?? 'https://fantastic-porpoise-318.convex.cloud'
const ok = async (r: Awaited<ReturnType<APIRequestContext['post']>>) => { expect(r.ok(), `${r.url()} ${r.status()} ${await r.text()}`).toBeTruthy(); return r.json() }

async function signIn(page: Page, role: 'student' | 'clinician', email: string) {
  await page.goto(role === 'student' ? '/student/sign-in' : '/clinician/sign-in')
  await page.getByLabel(role === 'student' ? 'Student email' : 'Professional email').fill(email)
  await page.getByLabel('Password').fill('curalink-demo')
  await page.getByRole('button', { name: role === 'student' ? /Sign in to student portal/ : /Sign in to clinician portal/ }).click()
  await expect(page).toHaveURL(new RegExp(`${role}/(dashboard|onboarding)`))
}
async function convexAs(page: Page) {
  const { token } = await (await page.request.get('/api/v1/convex/token', { headers: H })).json()
  const c = new ConvexHttpClient(CONVEX_URL); c.setAuth(token); return c
}

test('public deployment: Sam intake + summary + booking with Dr. Rivera → Rivera notes, decision, signing, simulated delivery', async ({ browser, baseURL }) => {
  expect(baseURL, 'set PROD_URL').toMatch(/^https:\/\//)
  const sam = await (await browser.newContext()).newPage()
  const rivera = await (await browser.newContext()).newPage()
  const hale = await (await browser.newContext()).newPage()

  // ---- public site, HTTPS, honest labelling, logo
  await sam.goto('/')
  await expect(sam.getByRole('heading', { name: 'Welcome to CuraLink' })).toBeVisible()
  expect(await sam.title()).toBe('CuraLink')
  expect(await sam.locator('link[rel=icon]').getAttribute('href')).toBe('/CuraLinkLogo2.png')
  expect(await sam.getByAltText('CuraLink logo').first().evaluate((i: HTMLImageElement) => i.naturalWidth)).toBe(960)
  await expect(sam.getByText(/fictional demo/i).first()).toBeVisible()
  const health = await (await sam.request.get('/api/v1/health')).json()
  expect(health.integrations.llm).toBe('live'); expect(health.integrations.voice).toBe('live'); expect(health.convex.enabled).toBe(true)

  // ---- Sam: login, calendar, intake with contextual temperature input (live Claude)
  await signIn(sam, 'student', 'sam.lee@students.example.com')
  await ok(await sam.request.post('/api/v1/calendars/import-sample', { headers: H }))
  await sam.goto('/student/voice')
  await sam.getByRole('button', { name: 'Start new conversation' }).first().click()
  await sam.getByLabel('Message').fill("I've had a fever and headache since yesterday. I missed class and want to discuss an absence note.")
  await sam.getByRole('button', { name: 'Send' }).click()
  const temp = sam.getByRole('group', { name: 'Temperature entry' })
  await expect(temp).toBeVisible({ timeout: 90_000 })
  await expect(sam.getByText('Claude · live')).toBeVisible()
  await temp.getByLabel('Measured temperature').fill('100.8')
  await temp.getByRole('button', { name: 'Save temperature' }).click()
  const knows = sam.locator('section', { has: sam.getByRole('heading', { name: 'What CuraLink knows' }) })
  await expect(knows.getByText('100.8°F')).toBeVisible({ timeout: 90_000 })
  for (const box of await knows.getByRole('checkbox').all()) if (!(await box.isChecked())) await box.check()
  await knows.getByRole('button', { name: 'Review your pre-visit summary' }).click()
  let dialog = sam.getByRole('dialog')
  await dialog.getByLabel(/I authorize sharing/).check()
  await dialog.getByRole('button', { name: 'Submit pre-visit summary' }).click()
  await expect(dialog).toContainText('Pre-visit summary submitted')
  await dialog.getByRole('button', { name: 'Done' }).click()

  // ---- Sam: book Dr. Rivera from the assistant; scheduler excludes class conflicts
  await sam.getByLabel('Message').fill('Can I see Dr. Rivera?')
  await sam.getByRole('button', { name: 'Send' }).click()
  const opts = sam.getByLabel('Appointment options').last()
  await expect(opts.getByRole('heading', { name: /Dr\. Avery Rivera/ })).toBeVisible({ timeout: 90_000 })
  await expect(opts.getByRole('heading', { name: /Dr\. Morgan Hale/ })).toHaveCount(0)
  const search = await ok(await sam.request.post('/api/v1/schedule/search', { headers: H, data: { appointment_type: 'general_consultation', clinician_id: 'demo-clinician-1', days: 5 } }))
  const events = (await (await sam.request.get(`/api/v1/calendar/events?start=${search.start}&end=2026-11-02`, { headers: H })).json()).events ?? []
  const classes = events.filter((e: { kind?: string; all_day?: boolean }) => e.kind === 'class' && !e.all_day)
  for (const s of search.clinicians[0].slots) for (const e of classes)
    expect(new Date(s.starts_at) < new Date(e.end_at ?? e.ends_at) && new Date(e.start_at ?? e.starts_at) < new Date(s.ends_at), `slot ${s.starts_at} overlaps ${e.summary ?? e.title}`).toBe(false)
  await opts.getByRole('button', { name: /^Dr\. Avery Rivera, / }).first().click()
  dialog = sam.getByRole('dialog')
  await expect(dialog).toContainText('Sam Lee')
  await expect(dialog.getByLabel(/discuss absence documentation/)).toBeChecked()
  await dialog.getByLabel(/I want to book this simulated appointment/).check()
  const booked = sam.waitForResponse(r => r.url().endsWith('/api/v1/appointments/confirm') && r.request().method() === 'POST')
  await dialog.getByRole('button', { name: 'Confirm appointment' }).click()
  const appt = await (await booked).json()
  await expect(sam.getByText(/Booked \(demo\): Dr\. Avery Rivera/)).toBeVisible()
  expect(appt.purpose ?? '').not.toMatch(/whatever/i)
  expect(appt.absence_requested).toBe(true)
  const caseId = appt.case_id as string

  // ---- Sam: survives refresh; absence request (no date choice) + confirms instructor contacts (fictional test addresses)
  await sam.reload(); await expect(sam).toHaveURL(/student\/voice/)
  await sam.goto('/student/cases')
  await sam.getByRole('button', { name: 'Request absence documentation review' }).click()
  await expect(sam.getByLabel(/First date you may miss/)).toHaveCount(0)
  const dash = await (await sam.request.get('/api/v1/students/me/dashboard', { headers: H })).json()
  for (const c of dash.courses as { id: string; code: string; instructor_email: string | null }[])
    await ok(await sam.request.patch(`/api/v1/courses/${c.id}/contact`, { headers: H, data: { instructor_email: c.instructor_email?.endsWith('@example.com') ? c.instructor_email : `${c.code.replace(' ', '').toLowerCase()}.demo@example.com`, confirm: true } }))
  const kase = await ok(await sam.request.post('/api/v1/absence-cases', { headers: H, data: { encounter_id: caseId, reported_missed_dates: ['2026-10-26'], disclosure_consent: true } }))
  expect((await sam.request.post('/api/v1/absence-cases', { headers: H, data: { encounter_id: caseId, requested_start: '2026-10-27', requested_end: '2026-10-30' } })).status()).toBe(422)

  // ---- Convex (production): authorized, synchronized copies
  const samCx = await convexAs(sam)
  const mineSummaries = await samCx.query('records:list' as never, { table: 'previsitSummaries' } as never) as { data: { caseId: string | null; summary: { measurements: { display: string }[] } | null } }[]
  expect(mineSummaries.some(r => r.data.caseId === caseId && r.data.summary?.measurements?.[0]?.display === '100.8°F')).toBe(true)

  // ---- Dr. Rivera (separate session): notes grouped by session, findings, decision, signing, simulated delivery
  await signIn(rivera, 'clinician', 'dr.rivera@clinic.example.com')
  await expect(rivera.getByRole('heading', { name: 'AI-Assisted Pre-Visit Notes' })).toBeVisible()
  await rivera.goto(`/clinician/encounters/${caseId}`)
  await expect(rivera.getByRole('heading', { name: 'AI-Assisted Pre-Visit Notes', exact: true })).toBeVisible()
  const summary = rivera.locator('section[aria-labelledby="pvs-title"]')
  await expect(summary.getByText('100.8°F').first()).toBeVisible()
  await expect(summary.getByText('Requested — not medically approved').first()).toBeVisible()
  await expect(rivera.locator('section[aria-labelledby="history-title"]').getByRole('heading', { level: 4 }).first()).toBeVisible()
  const rivCx = await convexAs(rivera)
  expect(((await rivCx.query('records:list' as never, { table: 'previsitSummaries' } as never)) as { data: { caseId: string } }[]).some(r => r.data.caseId === caseId)).toBe(true)
  expect(await rivCx.query('records:list' as never, { table: 'intakeSessions' } as never)).toEqual([]) // drafts never visible to clinicians
  const assets = await (await rivera.request.get('/api/v1/clinician/signature-assets', { headers: H })).json()
  if (!(assets as unknown[]).length) await ok(await rivera.request.post('/api/v1/clinician/signature-assets', { headers: H }))
  await rivera.reload()
  await rivera.getByLabel('Examination findings').fill('Clinician-documented findings (fictional test record)')
  await rivera.getByRole('button', { name: 'Save clinician findings' }).click()
  await expect(rivera.getByText('Visible only to clinicians')).toBeVisible()
  await rivera.getByRole('radio', { name: 'Approve an absence period' }).check()
  await expect(rivera.getByLabel('Inclusive first date')).toHaveValue('')
  await rivera.getByLabel('Inclusive first date').fill('2026-10-27')
  await rivera.getByLabel('Inclusive last date').fill('2026-10-28')
  await rivera.getByRole('button', { name: 'Save absence period' }).click()
  await rivera.getByRole('button', { name: 'Generate document' }).click()
  await expect(rivera.getByText(/Version \d+ · unsigned/)).toBeVisible()
  await rivera.getByRole('button', { name: 'Approve & sign this version' }).click()
  const sign = rivera.getByRole('dialog')
  await sign.getByLabel('Re-enter your password').fill('curalink-demo')
  await sign.getByLabel(/I reviewed the full preview/).check()
  await sign.getByRole('button', { name: 'Confirm demo signature' }).click()
  await expect(rivera.getByText(/Version \d+ · signed \(simulated\)/)).toBeVisible()
  const status = rivera.getByRole('region', { name: 'Delivery status' })
  await expect(status).toContainText('Student consent confirmed')
  await rivera.getByRole('button', { name: /Send authorized copies/ }).click()
  await expect(status).toContainText('Simulated delivery completed')
  const inbox = await (await rivera.request.get('/api/v1/demo/test-inbox', { headers: H })).json() as { to: string; body: string; subject: string }[]
  expect(inbox.length).toBeGreaterThan(0)
  expect(inbox.every(m => m.to.endsWith('example.com'))).toBe(true)
  expect(inbox.some(m => /fever|headache|100\.8/i.test(m.body + m.subject))).toBe(false)
  expect((await sam.request.get(`/api/v1/students/me/cases`, { headers: H })).ok()).toBe(true)
  expect(kase.id).toBeTruthy()

  // ---- Dr. Hale: no access to Sam's case (API and Convex)
  await signIn(hale, 'clinician', 'dr.hale@clinic.example.com')
  expect((await hale.request.get(`/api/v1/clinician/encounters/${caseId}/intake`, { headers: H })).status()).toBe(403)
  expect((await hale.request.get(`/api/v1/clinician/encounters/${caseId}/previsit-history`, { headers: H })).status()).toBe(403)
  const haleCx = await convexAs(hale)
  expect(((await haleCx.query('records:list' as never, { table: 'previsitSummaries' } as never)) as { data: { caseId: string } }[]).some(r => r.data.caseId === caseId)).toBe(false)
  // Student can't call clinician endpoints; signed-out can't read Convex records
  expect((await sam.request.post(`/api/v1/clinician/absence-cases/${kase.id}/decision`, { headers: H, data: { decision: 'CERTIFY', start_date: '2026-10-27', end_date: '2026-11-05' } })).status()).toBe(403)
  expect(await new ConvexHttpClient(CONVEX_URL).query('records:list' as never, { table: 'appointments' } as never)).toEqual([])
})

test('public deployment: Cartesia voice over the Vercel WebSocket (live TTS) and Claude reply', async ({ page }) => {
  await signIn(page, 'student', 'sam.lee@students.example.com')
  await ok(await page.request.post('/api/v1/voice/sessions', { headers: H, data: { voice_consent: true } }))
  const result = await page.evaluate(async () => new Promise<{ events: string[]; audioChunks: number; text: string; mode: string }>((resolve) => {
    const ws = new WebSocket(`wss://${location.host}/api/v1/voice/stream`)
    const out = { events: [] as string[], audioChunks: 0, text: '', mode: '' }
    const done = () => { try { ws.close() } catch { /* closing */ } resolve(out) }
    setTimeout(done, 60_000)
    ws.onmessage = e => {
      const m = JSON.parse(e.data)
      out.events.push(m.type)
      if (m.type === 'session.started') ws.send(JSON.stringify({ type: 'text', text: 'Which doctors are available?' }))
      if (m.type === 'assistant.text') { out.text = m.text; out.mode = m.reply?.mode ?? '' }
      if (m.type === 'assistant.audio.chunk') out.audioChunks++
      if (m.type === 'assistant.audio.done') done()
    }
    ws.onclose = done
  }))
  expect(result.events).toContain('session.started')
  expect(result.mode).toBe('claude')
  expect(result.text.length).toBeGreaterThan(10)
  expect(result.audioChunks).toBeGreaterThan(0) // Cartesia synthesized speech streamed back through Vercel
})
