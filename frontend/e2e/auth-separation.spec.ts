import { test, expect } from '@playwright/test'
import { login, loadSeedData, type SeedData } from './helpers/auth'

let seed: SeedData

test.beforeAll(() => {
  seed = loadSeedData()
})

// Navigation Guards

test.describe('Navigation Guards', () => {
  test.beforeEach(async ({ context }) => {
    await context.clearCookies()
  })

  test('unauthenticated user is redirected to login from /models', async ({ page }) => {
    await page.goto('/models', { waitUntil: 'commit' })
    await page.waitForURL('**/login', { timeout: 15000 })
    await expect(page.locator('text=Sign in to continue')).toBeVisible()
  })

  test('unauthenticated user is redirected to login from /settings', async ({ page }) => {
    await page.goto('/settings', { waitUntil: 'commit' })
    await page.waitForURL('**/login', { timeout: 15000 })
  })

  test('login as owner redirects to models page', async ({ page }) => {
    await login(page, seed.owner.username, seed.owner.password)
    await expect(page.locator('h1')).toContainText('Models', { timeout: 10000 })
  })
})

// Owner UI

test.describe('Owner UI', () => {
  test.beforeEach(async ({ context, page }) => {
    await context.clearCookies()
    await login(page, seed.owner.username, seed.owner.password)
  })

  test('owner sees all seeded models', async ({ page }) => {
    await expect(page.locator('h1')).toContainText('Models', { timeout: 10000 })
    await expect(page.getByText(seed.model_a.name)).toBeVisible({ timeout: 10000 })
    await expect(page.getByText(seed.model_b.name)).toBeVisible()
  })

  test('owner can access settings page', async ({ page }) => {
    await page.goto('/settings', { waitUntil: 'networkidle' })
    await expect(page.locator('h1')).toContainText('Settings', { timeout: 10000 })
    await expect(page.getByRole('tab', { name: 'Users' })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Service Accounts' })).toBeVisible()
  })

  test('owner can create a model via UI', async ({ page }) => {
    const modelName = `E2E-Owner-Model-${Date.now()}`

    // Click "New Model" button
    await page.getByRole('button', { name: /new model/i }).click()

    // Fill in the dialog form
    await page.getByLabel('Model Name').fill(modelName)
    await page.getByRole('button', { name: 'Create Model' }).click()

    // After creation, page navigates to model detail — verify via breadcrumb
    await expect(page.getByText(modelName).first()).toBeVisible({ timeout: 10000 })
  })

  test('owner can delete a model via UI', async ({ page }) => {
    // Create a model to delete
    const modelName = `E2E-Delete-Me-${Date.now()}`
    await page.getByRole('button', { name: /new model/i }).click()
    await page.getByLabel('Model Name').fill(modelName)
    await page.getByRole('button', { name: 'Create Model' }).click()
    await expect(page.getByText(modelName).first()).toBeVisible({ timeout: 10000 })

    // Navigate back to models list
    await page.goto('/models', { waitUntil: 'networkidle' })
    await expect(page.locator('h1')).toContainText('Models', { timeout: 10000 })

    // Open the card's three-dot menu for this model
    const card = page.locator('.model-card', { hasText: modelName })
    await card.hover()
    await card.locator('button:has(.mdi-dots-vertical)').click()

    // Click Delete in the dropdown menu
    await page.getByText('Delete', { exact: true }).click()

    // Wait for the confirmation dialog and click Delete inside it
    const dialog = page.locator('.v-dialog')
    await expect(dialog).toBeVisible({ timeout: 5000 })
    await dialog.getByRole('button', { name: 'Delete' }).click()

    // Wait for dialog to close
    await expect(dialog).not.toBeVisible({ timeout: 10000 })

    // Verify the model card is gone from the list
    await expect(card).not.toBeVisible({ timeout: 10000 })
  })
})

// Viewer UI

test.describe('Viewer UI', () => {
  test.beforeEach(async ({ context, page }) => {
    await context.clearCookies()
    await login(page, seed.viewer.username, seed.viewer.password)
  })

  test('viewer sees all seeded models', async ({ page }) => {
    await expect(page.locator('h1')).toContainText('Models', { timeout: 10000 })
    await expect(page.getByText(seed.model_a.name)).toBeVisible({ timeout: 10000 })
    await expect(page.getByText(seed.model_b.name)).toBeVisible()
  })

  test('viewer is redirected away from settings page', async ({ page }) => {
    await page.goto('/settings', { waitUntil: 'commit' })
    // Router guard redirects non-owner to /models
    await page.waitForURL('**/models', { timeout: 15000 })
    await expect(page.locator('h1')).toContainText('Models', { timeout: 10000 })
  })

  test('viewer can see model detail page', async ({ page }) => {
    // Click on the first seeded model
    await expect(page.getByText(seed.model_a.name)).toBeVisible({ timeout: 10000 })
    await page.getByText(seed.model_a.name).click()

    // Should navigate to model detail
    await page.waitForURL(`**/models/${seed.model_a.id}`, { timeout: 15000 })
    await expect(page.getByText(seed.model_a.name).first()).toBeVisible({ timeout: 10000 })
  })

  test('viewer does not see settings link in nav', async ({ page }) => {
    // Settings nav item should not be visible for viewers
    await expect(page.locator('h1')).toContainText('Models', { timeout: 10000 })
    await expect(page.getByText('Settings', { exact: true })).not.toBeVisible()
  })
})
