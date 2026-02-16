import { test, expect } from '@playwright/test'
import { login, loadSeedData, type SeedData } from './helpers/auth'

let seed: SeedData

test.beforeAll(() => {
  seed = loadSeedData()
})

test.describe('Jobs Page - Version context', () => {
  test.beforeEach(async ({ context, page }) => {
    await context.clearCookies()
    await login(page, seed.owner.username, seed.owner.password)
  })

  test('jobs page shows auto-created job for seeded version', async ({ page }) => {
    await page.goto(
      `/models/${seed.model_a.id}/versions/${seed.version_a.id}/jobs`,
      { waitUntil: 'networkidle' },
    )

    // Should show at least 1 job in the stats
    await expect(page.getByText('1 total')).toBeVisible({ timeout: 10000 })

    // Job name should be visible in the table
    await expect(page.locator('.jobs-table')).toBeVisible({ timeout: 10000 })
  })

  test('jobs page shows version navigation tabs', async ({ page }) => {
    await page.goto(
      `/models/${seed.model_a.id}/versions/${seed.version_a.id}/jobs`,
      { waitUntil: 'networkidle' },
    )

    // Should show breadcrumb with model name and version
    await expect(page.locator('.v-breadcrumbs')).toContainText(seed.model_a.name, {
      timeout: 10000,
    })
    await expect(page.locator('.v-breadcrumbs')).toContainText(seed.version_a.version)
  })

  test('owner can open edit dialog for a job', async ({ page }) => {
    await page.goto(
      `/models/${seed.model_a.id}/versions/${seed.version_a.id}/jobs`,
      { waitUntil: 'networkidle' },
    )

    // Wait for jobs table to load
    await expect(page.locator('.jobs-table')).toBeVisible({ timeout: 10000 })

    // Click edit button on the first job row (first action button)
    const actionsCell = page.locator('.jobs-table tbody tr').first().locator('td').last()
    await actionsCell.locator('button').first().click()

    // Edit dialog should appear
    const dialog = page.getByRole('dialog').filter({ hasText: 'Edit Drift Detection Job' })
    await expect(dialog).toBeVisible({ timeout: 5000 })

    // Should have job name field
    await expect(dialog.getByLabel('Job Name')).toBeVisible()

    // Should have schedule presets
    await expect(dialog.getByRole('button', { name: 'Hourly' })).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Daily' })).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Weekly' })).toBeVisible()

    // Should have comparison type select showing the current value
    await expect(dialog.getByText('vs Reference Data')).toBeVisible()

    // Cancel
    await dialog.getByRole('button', { name: 'Cancel' }).click()
    await expect(dialog).not.toBeVisible({ timeout: 5000 })
  })

  test('owner can edit job name and save', async ({ page }) => {
    await page.goto(
      `/models/${seed.model_a.id}/versions/${seed.version_a.id}/jobs`,
      { waitUntil: 'networkidle' },
    )

    await expect(page.locator('.jobs-table')).toBeVisible({ timeout: 10000 })

    // Click edit button
    const actionsCell = page.locator('.jobs-table tbody tr').first().locator('td').last()
    await actionsCell.locator('button').first().click()

    const dialog = page.getByRole('dialog').filter({ hasText: 'Edit Drift Detection Job' })
    await expect(dialog).toBeVisible({ timeout: 5000 })

    // Change job name
    const nameField = dialog.getByLabel('Job Name')
    const originalName = await nameField.inputValue()
    const newName = `E2E-Renamed-${Date.now()}`
    await nameField.clear()
    await nameField.fill(newName)

    // Save
    await dialog.getByRole('button', { name: 'Save' }).click()
    await expect(dialog).not.toBeVisible({ timeout: 10000 })

    // Verify new name appears in table
    await expect(page.getByText(newName)).toBeVisible({ timeout: 10000 })

    // Rename back to original
    const actionsCell2 = page.locator('.jobs-table tbody tr').first().locator('td').last()
    await actionsCell2.locator('button').first().click()
    const dialog2 = page.getByRole('dialog').filter({ hasText: 'Edit Drift Detection Job' })
    await expect(dialog2).toBeVisible({ timeout: 5000 })
    const nameField2 = dialog2.getByLabel('Job Name')
    await nameField2.clear()
    await nameField2.fill(originalName)
    await dialog2.getByRole('button', { name: 'Save' }).click()
    await expect(dialog2).not.toBeVisible({ timeout: 10000 })
  })

  test('owner can view job history', async ({ page }) => {
    await page.goto(
      `/models/${seed.model_a.id}/versions/${seed.version_a.id}/jobs`,
      { waitUntil: 'networkidle' },
    )

    await expect(page.locator('.jobs-table')).toBeVisible({ timeout: 10000 })

    // Click history button (last action button in the row)
    const actionsCell = page.locator('.jobs-table tbody tr').first().locator('td').last()
    await actionsCell.locator('button').last().click()

    // History dialog should appear
    const dialog = page.getByRole('dialog').filter({ hasText: 'Job History' })
    await expect(dialog).toBeVisible({ timeout: 5000 })

    // Should show at least one completed run (from seed script drift trigger)
    await expect(dialog.getByText('completed')).toBeVisible({ timeout: 10000 })

    // Close
    await dialog.getByRole('button', { name: 'Close' }).click()
    await expect(dialog).not.toBeVisible({ timeout: 5000 })
  })

  test('job status chip shows active/paused state', async ({ page }) => {
    await page.goto(
      `/models/${seed.model_a.id}/versions/${seed.version_a.id}/jobs`,
      { waitUntil: 'networkidle' },
    )

    await expect(page.locator('.jobs-table')).toBeVisible({ timeout: 10000 })

    // The job should show an Active status text
    await expect(page.locator('.jobs-table').getByText('Active').first()).toBeVisible({
      timeout: 10000,
    })
  })
})

// Global Jobs Page

test.describe('Jobs Page - Global', () => {
  test.beforeEach(async ({ context, page }) => {
    await context.clearCookies()
    await login(page, seed.owner.username, seed.owner.password)
  })

  test('global jobs page lists all jobs', async ({ page }) => {
    await page.goto('/jobs', { waitUntil: 'networkidle' })

    // Should show jobs stats
    await expect(page.getByText('total')).toBeVisible({ timeout: 10000 })

    // Should show the jobs table
    await expect(page.locator('.jobs-table')).toBeVisible({ timeout: 10000 })
  })
})
