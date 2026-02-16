import { test, expect } from '@playwright/test'
import { login, loadSeedData, type SeedData } from './helpers/auth'

let seed: SeedData

test.beforeAll(() => {
  seed = loadSeedData()
})

test.describe('Notifications Page', () => {
  test.beforeEach(async ({ context, page }) => {
    await context.clearCookies()
    await login(page, seed.owner.username, seed.owner.password)
  })

  test('notifications page loads with heading', async ({ page }) => {
    await page.goto('/notifications', { waitUntil: 'networkidle' })
    await expect(
      page.getByRole('heading', { name: 'Notifications', level: 1 }),
    ).toBeVisible({ timeout: 10000 })
  })

  test('notifications page shows drift notifications from seed data', async ({ page }) => {
    await page.goto('/notifications', { waitUntil: 'networkidle' })
    await expect(
      page.getByRole('heading', { name: 'Notifications', level: 1 }),
    ).toBeVisible({ timeout: 10000 })

    // Seed script triggered drift detection, which should create notifications.
    // Notifications contain "Drift detected" in the message.
    await expect(page.getByText('Drift detected').first()).toBeVisible({ timeout: 10000 })
  })

  test('notifications display unread count chip', async ({ page }) => {
    await page.goto('/notifications', { waitUntil: 'networkidle' })
    await expect(
      page.getByRole('heading', { name: 'Notifications', level: 1 }),
    ).toBeVisible({ timeout: 10000 })

    // Should show unread count chip (seed data creates unread notifications)
    await expect(page.getByText('unread')).toBeVisible({ timeout: 10000 })
  })

  test('mark all read clears unread count', async ({ page }) => {
    await page.goto('/notifications', { waitUntil: 'networkidle' })
    await expect(
      page.getByRole('heading', { name: 'Notifications', level: 1 }),
    ).toBeVisible({ timeout: 10000 })

    // Should have Mark All Read button when there are unread notifications
    const markAllBtn = page.getByRole('button', { name: /mark all read/i })
    await expect(markAllBtn).toBeVisible({ timeout: 10000 })

    // Click Mark All Read
    await markAllBtn.click()

    // Unread count chip should disappear and Mark All Read button should disappear
    await expect(markAllBtn).not.toBeVisible({ timeout: 10000 })
  })

  test('severity filter dropdown is present', async ({ page }) => {
    await page.goto('/notifications', { waitUntil: 'networkidle' })
    await expect(
      page.getByRole('heading', { name: 'Notifications', level: 1 }),
    ).toBeVisible({ timeout: 10000 })

    // Filter area should contain severity and status select dropdowns
    const filterCard = page.locator('.filter-card')
    await expect(filterCard).toBeVisible({ timeout: 10000 })
    await expect(filterCard.getByText('Severity').first()).toBeVisible()
    await expect(filterCard.getByText('Status').first()).toBeVisible()
  })

  test('status filter can filter to read notifications', async ({ page }) => {
    await page.goto('/notifications', { waitUntil: 'networkidle' })
    await expect(
      page.getByRole('heading', { name: 'Notifications', level: 1 }),
    ).toBeVisible({ timeout: 10000 })

    // First mark all as read so we have read notifications
    const markAllBtn = page.getByRole('button', { name: /mark all read/i })
    if (await markAllBtn.isVisible()) {
      await markAllBtn.click()
      await expect(markAllBtn).not.toBeVisible({ timeout: 10000 })
    }

    // Open the Status filter and select "Read"
    const statusSelect = page.locator('.filter-card .v-select').filter({ hasText: 'Status' })
    await statusSelect.locator('.v-field').click()
    const readOption = page.getByRole('option', { name: 'Read', exact: true })
    await readOption.waitFor({ state: 'visible', timeout: 5000 })
    await readOption.click()

    // Should still show notifications (now all are read)
    await expect(page.getByText('Drift detected').first()).toBeVisible({ timeout: 10000 })
  })
})
