import { test, expect } from '@playwright/test'
import { login, loadSeedData, type SeedData } from './helpers/auth'

let seed: SeedData

test.beforeAll(() => {
  seed = loadSeedData()
})

// Users Tab

test.describe('Settings - Users', () => {
  test.beforeEach(async ({ context, page }) => {
    await context.clearCookies()
    await login(page, seed.owner.username, seed.owner.password)
    await page.goto('/settings', { waitUntil: 'networkidle' })
    await expect(
      page.getByRole('heading', { name: 'Settings', level: 1 }),
    ).toBeVisible({ timeout: 10000 })
  })

  test('owner sees both seeded users in users table', async ({ page }) => {
    await expect(
      page.getByRole('cell', { name: seed.owner.username, exact: true }).first(),
    ).toBeVisible({ timeout: 10000 })
    await expect(
      page.getByRole('cell', { name: seed.viewer.username, exact: true }).first(),
    ).toBeVisible()
  })

  test('owner sees role chips for users', async ({ page }) => {
    // Owner should have "owner" role chip, viewer should have "viewer"
    const ownerRow = page.locator('tr', { hasText: seed.owner.username })
    await expect(ownerRow.locator('.v-chip').first()).toContainText('owner', { timeout: 10000 })

    const viewerRow = page.locator('tr', { hasText: seed.viewer.username })
    await expect(viewerRow.locator('.v-chip').first()).toContainText('viewer')
  })

  test('owner can open edit dialog for viewer user', async ({ page }) => {
    // Find viewer row and click edit button
    const viewerRow = page.locator('tr', { hasText: seed.viewer.username })
    await expect(viewerRow).toBeVisible({ timeout: 10000 })
    await viewerRow.locator('button').click()

    // Edit dialog should appear with viewer info
    const dialog = page.locator('.v-dialog').filter({ hasText: 'Edit User' })
    await expect(dialog).toBeVisible({ timeout: 5000 })
    await expect(dialog.locator('strong')).toContainText(seed.viewer.username)

    // Cancel without changes
    await dialog.getByRole('button', { name: 'Cancel' }).click()
    await expect(dialog).not.toBeVisible({ timeout: 5000 })
  })

  test('owner cannot edit their own user (no edit button)', async ({ page }) => {
    // The edit button should not be present for the current user
    const ownerRow = page.locator('tr', { hasText: seed.owner.username })
    await expect(ownerRow).toBeVisible({ timeout: 10000 })
    await expect(ownerRow.locator('button')).not.toBeVisible()
  })
})

// Service Accounts Tab

test.describe('Settings - Service Accounts', () => {
  test.beforeEach(async ({ context, page }) => {
    await context.clearCookies()
    await login(page, seed.owner.username, seed.owner.password)
    await page.goto('/settings', { waitUntil: 'networkidle' })
    await expect(
      page.getByRole('heading', { name: 'Settings', level: 1 }),
    ).toBeVisible({ timeout: 10000 })
    await page.getByRole('tab', { name: 'Service Accounts' }).click()
  })

  test('owner sees seeded service accounts', async ({ page }) => {
    await expect(page.getByText(seed.sa1.name)).toBeVisible({ timeout: 10000 })
    await expect(page.getByText(seed.sa2.name)).toBeVisible()
  })

  test('owner can create and delete a service account', async ({ page }) => {
    const saName = `e2e-test-sa-${Date.now()}`

    // Click Create Service Account
    await page.getByRole('button', { name: /create service account/i }).click()

    // Fill the form
    const createDialog = page.locator('.v-dialog').filter({ hasText: 'Create Service Account' })
    await expect(createDialog).toBeVisible({ timeout: 5000 })
    await createDialog.getByLabel('Name').fill(saName)

    // Create
    await createDialog.getByRole('button', { name: 'Create' }).click()

    // API key dialog should appear (persistent)
    await expect(page.getByText('Service Account Created')).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('Copy this API key now')).toBeVisible()

    // Close the key dialog
    await page.getByRole('button', { name: 'Done' }).click()

    // Verify SA appears in the table
    await expect(page.locator('td', { hasText: saName })).toBeVisible({ timeout: 10000 })

    // Now delete the SA
    const saRow = page.locator('tr', { hasText: saName })
    await saRow.locator('button').click()

    // Confirm deletion
    const deleteDialog = page.locator('.v-dialog').filter({ hasText: 'Delete Service Account' })
    await expect(deleteDialog).toBeVisible({ timeout: 5000 })
    await deleteDialog.getByRole('button', { name: 'Delete' }).click()

    // Wait for delete dialog to close
    await expect(deleteDialog).not.toBeVisible({ timeout: 10000 })

    // Verify SA is gone from the table
    await expect(page.locator('td', { hasText: saName })).not.toBeVisible({ timeout: 10000 })
  })

  test('create button is disabled when name is empty', async ({ page }) => {
    await page.getByRole('button', { name: /create service account/i }).click()

    const createDialog = page.locator('.v-dialog').filter({ hasText: 'Create Service Account' })
    await expect(createDialog).toBeVisible({ timeout: 5000 })

    // Create button should be disabled when name is empty
    const createBtn = createDialog.getByRole('button', { name: 'Create' })
    await expect(createBtn).toBeDisabled()

    // After entering a name, button should be enabled
    await createDialog.getByLabel('Name').fill('test')
    await expect(createBtn).toBeEnabled()

    // Cancel
    await createDialog.getByRole('button', { name: 'Cancel' }).click()
  })
})
