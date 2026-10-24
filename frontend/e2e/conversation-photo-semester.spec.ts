import { expect, test } from '@playwright/test'
import { H, resetDemo, studentWithCalendar } from './helpers'

test.beforeEach(async ({ page }) => { await resetDemo(page) })

test('multi-semester import: current term by default, correct grid positions, switching terms', async ({ page }) => {
  test.setTimeout(120_000)
  await page.request.post('/api/v1/auth/login', { headers: H, data: { email: 'sam.lee@students.example.com', password: 'curalink-demo' } })
  await page.goto('/student/import')
  await page.getByLabel('Upload UniTime .ics file').setInputFiles('../sample_data/unitime_multiterm_sample.ics')
  await expect(page.getByText('MA 16500', { exact: false })).toBeVisible() // historical course still listed with its term
  await page.goto('/student/calendar')
  await expect(page.getByRole('tab', { name: 'Fall 2026' })).toHaveAttribute('aria-selected', 'true')
  const events = page.getByTestId('grid-event')
  await expect(events).toHaveCount(5)
  const placed = await events.evaluateAll(els => els.map(e => `${(e.closest('[data-day]') as HTMLElement).dataset.day} ${(e as HTMLElement).dataset.start} ${e.querySelector('b')!.textContent}`))
  expect(placed.sort()).toEqual(['2026-10-26 3:00 PM COM 11400', '2026-10-27 1:00 PM CS 18000 · moved', '2026-10-28 3:00 PM COM 11400', '2026-10-28 8:30 AM MA 26100', '2026-10-29 10:30 AM CS 18000'])
  await expect(page.getByText('MA 16500')).toHaveCount(0) // Spring doesn't leak into Fall
  // Next week (after DST ends) keeps local times.
  await page.getByRole('button', { name: 'Next week' }).click()
  await expect(page.getByTestId('grid-event').filter({ hasText: 'CS 18000' }).first()).toHaveAttribute('data-start', '10:30 AM')
  // Switch to Spring: calendar jumps into the Spring term and shows only Spring classes.
  await page.getByRole('tab', { name: 'Spring 2026' }).click()
  await expect(page.getByText('Week of Jan 12, 2026')).toBeVisible()
  await expect(page.getByTestId('grid-event').filter({ hasText: 'MA 16500' })).toHaveCount(3)
  await expect(page.getByTestId('grid-event').filter({ hasText: 'CS 18000' })).toHaveCount(0)
  await page.getByRole('link', { name: 'Review imported schedule' }).click()
  await expect(page.getByRole('heading', { name: 'Spring 2026' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Fall 2026' })).toBeVisible()
})

test('assistant advances, asks contextual questions once, and opens the matching form', async ({ page }) => {
  test.setTimeout(120_000)
  await studentWithCalendar(page)
  await page.goto('/student/voice')
  const send = async (t: string) => { await page.getByLabel('Message').fill(t); await page.getByRole('button', { name: 'Send' }).click() }
  const bot = page.locator('div.border-slate-200.bg-white.text-slate-700')
  await send('I have a fever')
  await expect(bot.last()).toContainText(/when did|begin/i)
  await send("I don't know")
  await expect(bot.last()).toContainText(/temperature/i)
  await page.getByRole('button', { name: 'Open the details form' }).last().click()
  const drawer = page.getByRole('dialog')
  await expect(drawer.getByText('Temperature you measured')).toBeVisible()
  await expect(drawer.getByText('What you’re experiencing, in your words')).toHaveCount(0) // focused form
  await drawer.getByRole('button', { name: 'Cancel' }).click()
  await send('no idea, I did not measure it')
  await expect(bot.last()).toContainText('leave out your temperature')
  await send('what now?')
  await expect(bot.last()).not.toContainText(/temperature/i)
  await expect(page.getByRole('button', { name: 'Review my information' }).last()).toBeVisible()
  const texts = await bot.allInnerTexts()
  expect(new Set(texts).size).toBe(texts.length) // no repeated replies
  await expect(page.getByRole('list', { name: 'Conversation progress' })).toBeVisible()
  await page.getByRole('button', { name: 'End this conversation' }).last().click()
  await expect(page.getByText('Conversation ended.')).toBeVisible()
  await page.getByRole('button', { name: 'Start over' }).first().click()
  await expect(bot).toHaveCount(1)
})

test('photo upload: HEIC accepted and converted, formats shown, invalid rejected, remove works', async ({ page }) => {
  test.setTimeout(120_000)
  await studentWithCalendar(page)
  await page.goto('/student/voice')
  await page.getByLabel('Message').fill('I bruised my leg')
  await page.getByRole('button', { name: 'Send' }).click()
  await page.getByLabel('Message').fill('yesterday')
  await page.getByRole('button', { name: 'Send' }).click()
  await page.getByRole('button', { name: 'Add a photo (optional)' }).last().click()
  const drawer = page.getByRole('dialog')
  await expect(drawer.getByText('Upload a photo (JPG, PNG, WebP, or iPhone HEIC/HEIF) · up to 12 MB', { exact: false })).toBeVisible()
  const picker = drawer.getByLabel('Choose a photo from your files or photo library')
  await expect(picker).toBeDisabled() // consent first
  await drawer.getByLabel(/I agree to have this photo analyzed/).check()
  await picker.setInputFiles({ name: 'notes.heic', mimeType: 'image/heic', buffer: Buffer.from('definitely not an image') })
  await expect(drawer.getByText(/isn't a supported photo/)).toBeVisible()
  await picker.setInputFiles('../sample_data/demo_images/synthetic_red_area.heic')
  const preview = drawer.getByAltText('Your uploaded photo')
  await expect(preview).toBeVisible()
  expect(await preview.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0) // HEIC converted for display
  await expect(drawer.getByText('Visual analysis unavailable — limited demo fallback', { exact: false })).toBeVisible()
  await expect(drawer.getByText('AI-generated')).toBeVisible()
  await drawer.getByRole('button', { name: 'Remove photo' }).click()
  await expect(preview).toHaveCount(0)
})
