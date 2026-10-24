import { expect, test, type Page } from '@playwright/test'
import { H, resetDemo, studentWithCalendar } from './helpers'

const STUDENT = ['/student/dashboard', '/student/voice', '/student/calendar', '/student/appointments', '/student/cases', '/student/settings']
const CLINICIAN = ['/clinician/dashboard', '/clinician/intake', '/clinician/absence-cases', '/clinician/documents', '/clinician/signatures', '/clinician/activity']

async function audit(page: Page, path: string) {
  await page.goto(path)
  await page.waitForLoadState('networkidle')
  return page.evaluate(() => {
    const problems: string[] = []
    if (document.documentElement.scrollWidth > window.innerWidth + 1) problems.push(`horizontal overflow ${document.documentElement.scrollWidth}px > ${window.innerWidth}px`)
    const visible = (el: Element) => { const r = (el as HTMLElement).getBoundingClientRect(); return r.width > 0 && r.height > 0 && (el as HTMLElement).checkVisibility({ contentVisibilityAuto: true }) && !el.closest('details:not([open]) > :not(summary)') }
    const named = (el: Element) => !!((el as HTMLElement).innerText?.trim() || el.getAttribute('aria-label') || el.getAttribute('title') || el.querySelector('img[alt]:not([alt=""])'))
    document.querySelectorAll('button, a[href]').forEach(el => { if (visible(el) && !named(el)) problems.push(`unnamed ${el.tagName.toLowerCase()}: ${el.outerHTML.slice(0, 80)}`) })
    document.querySelectorAll('img').forEach(el => { if (!el.hasAttribute('alt')) problems.push(`img without alt: ${el.outerHTML.slice(0, 80)}`) })
    document.querySelectorAll('input:not([type=hidden]), select, textarea').forEach(el => {
      const id = el.id
      const ok = el.closest('label') || el.getAttribute('aria-label') || (id && document.querySelector(`label[for="${id}"]`))
      if (!ok && visible(el)) problems.push(`unlabelled control: ${el.outerHTML.slice(0, 80)}`)
    })
    return problems
  })
}

for (const width of [390, 1280]) {
  test(`student screens have no overflow or unnamed controls at ${width}px`, async ({ page }) => {
    test.setTimeout(120_000)
    await page.setViewportSize({ width, height: 900 })
    await resetDemo(page)
    await studentWithCalendar(page)
    for (const path of STUDENT) expect(await audit(page, path), path).toEqual([])
  })

  test(`clinician screens have no overflow or unnamed controls at ${width}px`, async ({ page }) => {
    test.setTimeout(120_000)
    await page.setViewportSize({ width, height: 900 })
    await resetDemo(page)
    await page.request.post('/api/v1/auth/login', { headers: H, data: { email: 'dr.rivera@clinic.example.com', password: 'curalink-demo' } })
    for (const path of CLINICIAN) expect(await audit(page, path), path).toEqual([])
    expect(await audit(page, '/clinician/encounters/enc_jordan_1'), 'encounter').toEqual([])
  })
}

test('sign-in and role screens are usable on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  for (const path of ['/select-role', '/student/sign-in', '/clinician/sign-in']) expect(await audit(page, path), path).toEqual([])
})
