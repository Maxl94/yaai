import { test, expect } from '@playwright/test'
import { login, loadSeedData, type SeedData } from './helpers/auth'

let seed: SeedData

test.beforeAll(() => {
  seed = loadSeedData()
})

// Owner: Model Detail

test.describe('Model Detail - Owner', () => {
  test.beforeEach(async ({ context, page }) => {
    await context.clearCookies()
    await login(page, seed.owner.username, seed.owner.password)
  })

  test('owner can view model detail page with breadcrumb', async ({ page }) => {
    await expect(page.getByText(seed.model_a.name)).toBeVisible({ timeout: 10000 })
    await page.getByText(seed.model_a.name).click()
    await page.waitForURL(`**/models/${seed.model_a.id}`, { timeout: 15000 })

    // Breadcrumb should show "Models" link and model name
    await expect(page.locator('.v-breadcrumbs')).toContainText('Models')
    await expect(page.getByText(seed.model_a.name).first()).toBeVisible()
  })

  test('owner can edit model name and description', async ({ page }) => {
    // Create a temporary model to edit (avoids mutating seed data)
    const modelName = `E2E-Edit-${Date.now()}`
    await page.getByRole('button', { name: /new model/i }).click()
    await page.getByLabel('Model Name').fill(modelName)
    await page.getByRole('button', { name: 'Create Model' }).click()
    await expect(page.getByText(modelName).first()).toBeVisible({ timeout: 10000 })

    // Click pencil to start editing
    await page.locator('button:has(.mdi-pencil)').first().click()

    // Edit name
    const newName = `${modelName}-Renamed`
    const nameInput = page.locator('.v-card-title input')
    await nameInput.clear()
    await nameInput.fill(newName)

    // Add description
    await page.locator('textarea').fill('E2E test description')

    // Save
    await page.getByRole('button', { name: 'Save' }).click()

    // Verify changes persisted
    await expect(page.getByText(newName).first()).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('E2E test description')).toBeVisible()
  })

  test('owner sees seeded version in versions table', async ({ page }) => {
    await page.goto(`/models/${seed.model_a.id}`, { waitUntil: 'networkidle' })
    await expect(page.getByText(seed.model_a.name).first()).toBeVisible({ timeout: 10000 })

    // Should see the version created by seed
    await expect(page.getByText(seed.version_a.version)).toBeVisible({ timeout: 10000 })

    // Should see schema field count (3 fields: age, gender, score)
    await expect(page.getByText('3 fields')).toBeVisible()
  })

  test('owner can create a version with schema fields', async ({ page }) => {
    // Use Model-B which has no version yet
    await page.goto(`/models/${seed.model_b.id}`, { waitUntil: 'networkidle' })
    await expect(page.getByText(seed.model_b.name).first()).toBeVisible({ timeout: 10000 })

    // Click New Version
    await page.getByRole('button', { name: /new version/i }).click()

    // Fill version label
    const dialog = page.getByRole('dialog').filter({ hasText: 'Create New Version' })
    await expect(dialog).toBeVisible({ timeout: 5000 })
    await dialog.getByLabel('Version Label').fill('v-e2e-test')

    // Add an input schema field
    await dialog.getByRole('button', { name: /add field/i }).click()
    const fieldRows = dialog.locator('.d-flex.gap-2.mb-2')
    const inputRow = fieldRows.nth(0)
    await inputRow.getByLabel('Field Name').fill('temperature')
    // Direction defaults to 'input', which is correct

    // Add an output schema field (backend requires at least one input + one output)
    await dialog.getByRole('button', { name: /add field/i }).click()
    const outputRow = fieldRows.nth(1)
    await outputRow.getByLabel('Field Name').fill('prediction')
    // Change direction to 'output'
    await outputRow.locator('.v-select').first().locator('.v-field').click()
    await page.getByRole('option', { name: 'output' }).click()

    // Click Create Version and wait for the API response
    const responsePromise = page.waitForResponse(
      (resp) => resp.url().includes('/versions') && resp.request().method() === 'POST',
    )
    await dialog.getByRole('button', { name: 'Create Version' }).click()
    await responsePromise

    // Dialog should close and version should appear in table
    await expect(dialog).not.toBeVisible({ timeout: 15000 })
    await expect(page.getByText('v-e2e-test')).toBeVisible({ timeout: 10000 })
  })

  test('owner can view schema dialog for a version', async ({ page }) => {
    await page.goto(`/models/${seed.model_a.id}`, { waitUntil: 'networkidle' })
    await expect(page.getByText(seed.version_a.version)).toBeVisible({ timeout: 10000 })

    // Click Schema button for the version
    await page.getByRole('button', { name: 'Schema' }).first().click()

    // Schema dialog should show fields
    const dialog = page.getByRole('dialog').filter({ hasText: 'Schema' })
    await expect(dialog).toBeVisible({ timeout: 5000 })
    await expect(dialog.getByText('age')).toBeVisible()
    await expect(dialog.getByText('gender')).toBeVisible()
    await expect(dialog.getByText('score')).toBeVisible()

    // Should show field count
    await expect(dialog.getByText('3 field(s)')).toBeVisible()

    // Close dialog
    await dialog.getByRole('button', { name: 'Close' }).click()
    await expect(dialog).not.toBeVisible({ timeout: 5000 })
  })

  test('owner sees service account access section', async ({ page }) => {
    await page.goto(`/models/${seed.model_a.id}`, { waitUntil: 'networkidle' })
    await expect(page.getByText(seed.model_a.name).first()).toBeVisible({ timeout: 10000 })

    // Owner should see the Service Account Access heading
    await expect(page.getByText('Service Account Access')).toBeVisible({ timeout: 10000 })

    // Should see SA-1 which was granted access to Model-A by the seed
    await expect(page.getByText(seed.sa1.name)).toBeVisible()
  })

  test('owner can navigate from version to dashboard', async ({ page }) => {
    await page.goto(`/models/${seed.model_a.id}`, { waitUntil: 'networkidle' })
    await expect(page.getByText(seed.version_a.version)).toBeVisible({ timeout: 10000 })

    // Click Dashboard button
    await page.getByRole('button', { name: 'Dashboard' }).first().click()

    // Should navigate to dashboard route
    await page.waitForURL(
      `**/models/${seed.model_a.id}/versions/${seed.version_a.id}/dashboard`,
      { timeout: 15000 },
    )
  })
})

// Viewer: Model Detail

test.describe('Model Detail - Viewer', () => {
  test.beforeEach(async ({ context, page }) => {
    await context.clearCookies()
    await login(page, seed.viewer.username, seed.viewer.password)
  })

  test('viewer can view model detail', async ({ page }) => {
    await page.goto(`/models/${seed.model_a.id}`, { waitUntil: 'networkidle' })
    await expect(page.getByText(seed.model_a.name).first()).toBeVisible({ timeout: 10000 })

    // Should see the version
    await expect(page.getByText(seed.version_a.version)).toBeVisible({ timeout: 10000 })
  })

  test('viewer does not see service account access section', async ({ page }) => {
    await page.goto(`/models/${seed.model_a.id}`, { waitUntil: 'networkidle' })
    await expect(page.getByText(seed.model_a.name).first()).toBeVisible({ timeout: 10000 })

    // Viewer should NOT see the Service Account Access section
    await expect(page.getByText('Service Account Access')).not.toBeVisible()
  })
})
