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

  test('owner sees all projects and can create a project', async ({ page }) => {
    const projectName = `e2e-project-${Date.now()}`

    await page.getByRole('link', { name: /projects/i }).click()
    await expect(page.locator('h1')).toContainText('Projects', { timeout: 10000 })
    await expect(page.getByRole('cell', { name: seed.other_project.name, exact: true })).toBeVisible({ timeout: 10000 })

    await page.getByTestId('create-project').click()
    await page.getByLabel('Project Name').fill(projectName)
    await page.getByRole('button', { name: 'Create', exact: true }).click()

    await expect(page.getByRole('cell', { name: projectName, exact: true })).toBeVisible({ timeout: 10000 })
  })

  test('project switcher filters the model list', async ({ page }) => {
    await expect(page.getByText(seed.model_a.name)).toBeVisible({ timeout: 10000 })
    await expect(page.getByText(seed.hidden_model.name)).toBeVisible()

    await page.getByTestId('project-switcher').click()
    await page.getByRole('option', { name: seed.other_project.name, exact: true }).click()
    await expect(page.getByText(seed.hidden_model.name)).toBeVisible({ timeout: 10000 })
    await expect(page.getByText(seed.model_a.name)).toHaveCount(0)

    await page.getByTestId('project-switcher').click()
    await page.getByRole('option', { name: 'default', exact: true }).click()
    await expect(page.getByText(seed.model_a.name)).toBeVisible({ timeout: 10000 })
    await expect(page.getByText(seed.hidden_model.name)).toHaveCount(0)
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

  test('viewer does not see New Model button', async ({ page }) => {
    await expect(page.getByText(seed.model_a.name)).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('button', { name: /new model/i })).toHaveCount(0)
  })

  test('viewer does not see models of projects without membership', async ({ page }) => {
    await expect(page.getByText(seed.model_a.name)).toBeVisible({ timeout: 10000 })
    await expect(page.getByText(seed.hidden_model.name)).toHaveCount(0)

    // The viewer only belongs to the default project, so there is nothing to filter by
    await expect(page.getByTestId('project-switcher')).toHaveCount(0)
  })

  test('viewer cannot open a model of a foreign project', async ({ page }) => {
    await page.goto(`/models/${seed.hidden_model.id}`, { waitUntil: 'networkidle' })
    await expect(page.getByText('Model not found')).toBeVisible({ timeout: 10000 })
  })

  test('viewer sees projects read-only', async ({ page }) => {
    await page.getByRole('link', { name: /projects/i }).click()
    await expect(page.locator('h1')).toContainText('Projects', { timeout: 10000 })
    await expect(page.getByRole('cell', { name: 'default' }).first()).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('cell', { name: seed.other_project.name, exact: true })).toHaveCount(0)
    await expect(page.getByTestId('create-project')).toHaveCount(0)
    await expect(page.getByRole('button', { name: /^(Members of|Edit|Delete) / })).toHaveCount(0)
  })
})
