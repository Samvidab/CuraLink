import { expect, test, type Page } from '@playwright/test'
import { H, resetDemo } from './helpers'

test.beforeEach(async ({ page }) => { await resetDemo(page) })

const signInSam = async (page: Page) => {
  await page.goto('/student/sign-in')
  await page.getByLabel('Student email').fill('sam.lee@students.example.com')
  await page.getByLabel('Password').fill('curalink-demo')
  await page.getByRole('button', { name: /Sign in to student portal/ }).click()
  await expect(page).toHaveURL(/student\/dashboard/)
}

test('a new visitor sees the welcome page and is never signed in as Sam', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Welcome to CuraLink' })).toBeVisible()
  await expect(page.getByText(/still signed in/)).toHaveCount(0)
  await expect(page.getByText('Sam Lee')).toHaveCount(0)
  expect((await page.request.get('/api/v1/me', { headers: H })).status()).toBe(401)
  await page.goto('/student/dashboard')
  await expect(page).toHaveURL(/student\/sign-in/)
})

test('new student: sign up, asked for a name once, greeted by preferred name, can change it', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: /I'm a student/ }).click()
  await page.getByRole('button', { name: 'New to CuraLink? Create a student account' }).click()
  await page.getByLabel('Email').fill('alex.morgan@students.example.com')
  await page.getByLabel('Create a password').fill('fictional-pass-1')
  await page.getByRole('button', { name: /Create account/ }).click()

  await expect(page.getByRole('heading', { name: 'Welcome to CuraLink! Before we get started, what should we call you?' })).toBeVisible()
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('alert')).toContainText('first and last name')
  await page.getByLabel(/First name/).fill('Alexandra')
  await page.getByLabel(/Last name/).fill('Morgan')
  await page.getByLabel(/Preferred name/).fill('Alex')
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('button', { name: 'Skip for now' }).click()
  await expect(page.getByRole('heading', { name: 'You’re ready, Alex.' })).toBeVisible()
  await page.getByRole('button', { name: /Go to dashboard/ }).click()
  await expect(page.getByRole('heading', { name: 'Good morning, Alex!' })).toBeVisible()

  await page.goto('/student/voice')
  await expect(page.getByText("Hi Alex! I'm CuraLink", { exact: false })).toBeVisible()

  await page.goto('/student/settings')
  await expect(page.getByLabel('First name')).toHaveValue('Alexandra')
  await page.getByLabel(/Preferred name/).fill('Lex')
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page.getByText('Profile saved.')).toBeVisible()
  await page.goto('/student/voice')
  await expect(page.getByText("Hi Lex! I'm CuraLink", { exact: false })).toBeVisible()

  // Sign out → welcome page; signing back in is not asked for a name again.
  await page.getByRole('button', { name: /Sign out/ }).first().click()
  await expect(page.getByRole('heading', { name: 'Welcome to CuraLink' })).toBeVisible()
  expect((await page.request.get('/api/v1/me', { headers: H })).status()).toBe(401)
  await page.goto('/student/sign-in')
  await page.getByLabel('Student email').fill('alex.morgan@students.example.com')
  await page.getByLabel('Password').fill('fictional-pass-1')
  await page.getByRole('button', { name: /Sign in to student portal/ }).click()
  await expect(page.getByRole('heading', { name: 'Good morning, Lex!' })).toBeVisible()
})

test('a still-valid session is offered on the welcome page, never entered silently', async ({ page }) => {
  await signInSam(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Welcome to CuraLink' })).toBeVisible()
  await expect(page).not.toHaveURL(/dashboard/)
  await expect(page.getByText(/still signed in as/)).toContainText('Sam Lee')
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByText(/still signed in/)).toHaveCount(0)
  await page.goto('/student/dashboard')
  await expect(page).toHaveURL(/student\/sign-in/)
})

test('Sam is greeted by name; switching to a clinician exposes none of Sam’s data', async ({ page }) => {
  await signInSam(page)
  await page.goto('/student/voice')
  await expect(page.getByText("Hi Sam! I'm CuraLink", { exact: false })).toBeVisible()

  await page.goto('/clinician/sign-in')
  await page.getByLabel('Professional email').fill('dr.hale@clinic.example.com')
  await page.getByLabel('Password').fill('curalink-demo')
  await page.getByRole('button', { name: /Sign in to clinician portal/ }).click()
  await expect(page).toHaveURL(/clinician\/dashboard/)
  await expect(page.getByText('Dr. Morgan Hale').first()).toBeVisible()
  expect((await page.request.get('/api/v1/students/me/dashboard', { headers: H })).status()).toBe(403)
  await page.goto('/student/dashboard')
  await expect(page.getByText('403 · ACCESS DENIED')).toBeVisible()
  await expect(page.getByText('Good morning, Sam!')).toHaveCount(0)
})

test('requesting a clinician account never grants clinician access', async ({ page }) => {
  await page.goto('/clinician/sign-in')
  await page.getByRole('button', { name: 'Request a clinician account' }).click()
  await page.getByLabel('First name').fill('Jamie')
  await page.getByLabel('Last name').fill('Ortiz')
  await page.getByLabel('Professional credentials').fill('MD')
  await page.getByLabel('Specialty or clinical role').fill('Family Medicine')
  await page.getByLabel('Professional email').fill('jamie.ortiz@clinic.example.com')
  await page.getByLabel('Create a password').fill('fictional-pass-1')
  await page.getByRole('button', { name: 'Submit for verification' }).click()
  await expect(page.getByRole('status')).toContainText('must verify your credentials')
  expect((await page.request.get('/api/v1/me', { headers: H })).status()).toBe(401)
  await page.getByRole('button', { name: '← Back to sign in' }).click()
  await page.getByLabel('Professional email').fill('jamie.ortiz@clinic.example.com')
  await page.getByLabel('Password').fill('fictional-pass-1')
  await page.getByRole('button', { name: /Sign in to clinician portal/ }).click()
  await expect(page.getByRole('alert')).toContainText("hasn't been verified")
})
