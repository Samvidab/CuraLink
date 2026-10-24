import { expect, test } from '@playwright/test'
import { resetDemo, studentWithCalendar } from './helpers'

test.beforeEach(async ({ page }) => { await resetDemo(page); await studentWithCalendar(page) })

test('ranks demo slots against classes and books one only after explicit confirmation', async ({ page }) => {
  await page.goto('/student/appointments')
  const options = page.getByRole('radiogroup', { name: 'Ranked appointment options' }).getByRole('radio')
  await expect(options.first()).toContainText('10:30 AM–11:00 AM')
  await expect(options.first()).toContainText('#1')
  await expect(page.getByText('DEMO').first()).toBeVisible()
  await page.getByText(/Why some times aren’t shown/).click()
  await expect(page.getByText('Not enough travel time around a class').first()).toBeVisible()

  await options.filter({ hasText: '2:30 PM–2:50 PM' }).click()
  await page.getByRole('button', { name: 'Confirm demo appointment' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('not booked with a real clinic')
  await expect(dialog.getByRole('button', { name: 'Confirm demo appointment' })).toBeDisabled()
  await dialog.getByLabel('I understand this is a simulated reservation.').check()
  await dialog.getByRole('button', { name: 'Confirm demo appointment' }).click()
  await expect(page.getByRole('heading', { name: 'Demo time reserved' })).toBeVisible()

  await page.goto('/student/dashboard')
  await expect(page.getByText('Demo appointment', { exact: true })).toBeVisible()
  await expect(page.getByText(/2:30 PM · Demo Student Health Clinic/)).toBeVisible()
})

test('a slot taken before confirmation is never silently rebooked', async ({ page }) => {
  await page.goto('/student/appointments')
  const first = page.getByRole('radiogroup', { name: 'Ranked appointment options' }).getByRole('radio').first()
  await expect(first).toContainText('10:30 AM')
  await first.click()
  await page.getByText('Demo controls').click()
  await page.getByRole('button', { name: 'Mark selected slot as taken' }).click()
  await page.getByRole('button', { name: 'Confirm demo appointment' }).first().click()
  await page.getByRole('dialog').getByLabel('I understand this is a simulated reservation.').check()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm demo appointment' }).click()
  await expect(page.getByRole('alert')).toContainText('just taken')
  await expect(page.getByRole('radiogroup', { name: 'Ranked appointment options' }).getByRole('radio').first()).toContainText('2:30 PM')
})
