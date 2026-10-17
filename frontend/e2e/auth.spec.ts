import { test, expect } from '@playwright/test'
import { loadSeedData, type SeedData } from './helpers/auth'

let seed: SeedData

test.beforeAll(() => {
  seed = loadSeedData()
})

test.describe('Authentication - Local Auth', () => {
  test.beforeEach(async ({ context }) => {
    await context.clearCookies()
  })

  test('redirects unauthenticated user to login page', async ({ page }) => {
    await page.goto('/models', { waitUntil: 'commit' })
    await page.waitForURL('**/login', { timeout: 15000 })
    await expect(page.locator('text=Sign in to continue')).toBeVisible()
  })

  test('login page shows username and password fields', async ({ page }) => {
    await page.goto('/login', { waitUntil: 'networkidle' })
    await expect(page.getByLabel('Username')).toBeVisible({ timeout: 10000 })
    await expect(page.locator('input[type="password"]')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Sign In', exact: true })).toBeVisible()
  })

  test('shows error for invalid credentials', async ({ page }) => {
    await page.goto('/login', { waitUntil: 'networkidle' })
    await expect(page.getByLabel('Username')).toBeVisible({ timeout: 10000 })

    await page.getByLabel('Username').fill(seed.owner.username)
    await page.locator('input[type="password"]').fill('wrongpassword')
    await page.getByRole('button', { name: 'Sign In', exact: true }).click()

    await expect(page.locator('.v-alert')).toBeVisible({ timeout: 10000 })
  })

  test('successful login redirects to models page', async ({ page }) => {
    await page.goto('/login', { waitUntil: 'networkidle' })
    await expect(page.getByLabel('Username')).toBeVisible({ timeout: 10000 })

    await page.getByLabel('Username').fill(seed.owner.username)
    await page.locator('input[type="password"]').fill(seed.owner.password)
    await page.getByRole('button', { name: 'Sign In', exact: true }).click()

    await page.waitForURL('**/models', { timeout: 15000 })
    await expect(page.locator('h1')).toContainText('Models', { timeout: 10000 })
  })

  test('keeps the refresh token in an httpOnly cookie and nothing in localStorage', async ({ page }) => {
    await page.goto('/login', { waitUntil: 'networkidle' })
    await expect(page.getByLabel('Username')).toBeVisible({ timeout: 10000 })

    await page.getByLabel('Username').fill(seed.owner.username)
    await page.locator('input[type="password"]').fill(seed.owner.password)
    await page.getByRole('button', { name: 'Sign In', exact: true }).click()

    await page.waitForURL('**/models', { timeout: 15000 })

    expect(await page.evaluate(() => localStorage.getItem('access_token'))).toBeNull()
    expect(await page.evaluate(() => localStorage.getItem('refresh_token'))).toBeNull()
    expect(await page.evaluate(() => document.cookie)).not.toContain('yaai_refresh')

    const cookies = await page.context().cookies()
    const refresh = cookies.find((c) => c.name === 'yaai_refresh')
    expect(refresh?.httpOnly).toBe(true)
    expect(refresh?.path).toBe('/api/v1/auth')
  })

  test('session persists across page reload', async ({ page }) => {
    await page.goto('/login', { waitUntil: 'networkidle' })
    await expect(page.getByLabel('Username')).toBeVisible({ timeout: 10000 })
    await page.getByLabel('Username').fill(seed.owner.username)
    await page.locator('input[type="password"]').fill(seed.owner.password)
    await page.getByRole('button', { name: 'Sign In', exact: true }).click()
    await page.waitForURL('**/models', { timeout: 15000 })

    await page.reload({ waitUntil: 'networkidle' })

    expect(page.url()).toContain('/models')
    await expect(page.locator('h1')).toContainText('Models', { timeout: 10000 })
  })

  test('authenticated user is redirected away from login page', async ({ page }) => {
    await page.goto('/login', { waitUntil: 'networkidle' })
    await expect(page.getByLabel('Username')).toBeVisible({ timeout: 10000 })
    await page.getByLabel('Username').fill(seed.owner.username)
    await page.locator('input[type="password"]').fill(seed.owner.password)
    await page.getByRole('button', { name: 'Sign In', exact: true }).click()
    await page.waitForURL('**/models', { timeout: 15000 })

    await page.goto('/login', { waitUntil: 'commit' })
    await page.waitForURL('**/models', { timeout: 15000 })
  })

  test('logout clears session and redirects to login', async ({ page }) => {
    await page.goto('/login', { waitUntil: 'networkidle' })
    await expect(page.getByLabel('Username')).toBeVisible({ timeout: 10000 })
    await page.getByLabel('Username').fill(seed.owner.username)
    await page.locator('input[type="password"]').fill(seed.owner.password)
    await page.getByRole('button', { name: 'Sign In', exact: true }).click()
    await page.waitForURL('**/models', { timeout: 15000 })

    await page.getByText('Sign Out').click()
    await page.waitForURL('**/login', { timeout: 15000 })

    const cookies = await page.context().cookies()
    expect(cookies.find((c) => c.name === 'yaai_refresh')).toBeUndefined()

    // Without the cookie a reload must not restore the session
    await page.goto('/models', { waitUntil: 'commit' })
    await page.waitForURL('**/login', { timeout: 15000 })
  })

  test('all protected routes redirect to login when unauthenticated', async ({ page }) => {
    const protectedRoutes = ['/models', '/jobs', '/drift', '/notifications']

    for (const route of protectedRoutes) {
      await page.goto(route, { waitUntil: 'commit' })
      await page.waitForURL('**/login', { timeout: 15000 })
    }
  })

  test('sign in button is disabled when fields are empty', async ({ page }) => {
    await page.goto('/login', { waitUntil: 'networkidle' })
    await expect(page.getByLabel('Username')).toBeVisible({ timeout: 10000 })

    const signInButton = page.getByRole('button', { name: 'Sign In', exact: true })

    await expect(signInButton).toBeDisabled()

    await page.getByLabel('Username').fill(seed.owner.username)
    await expect(signInButton).toBeDisabled()

    await page.locator('input[type="password"]').fill('test')
    await expect(signInButton).toBeEnabled()
  })
})
