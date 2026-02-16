import { type Page } from '@playwright/test'
import { readFileSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))

/**
 * Login via the UI login form.
 * Waits for redirect to /models after successful login.
 * Retries up to 3 times on failure (e.g. rate limiting, slow backend).
 */
export async function login(page: Page, username: string, password: string): Promise<void> {
  const maxRetries = 3
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      await page.goto('/login', { waitUntil: 'networkidle' })
      await page.getByLabel('Username').fill(username)
      await page.locator('input[type="password"]').fill(password)
      await page.getByRole('button', { name: 'Sign In', exact: true }).click()
      await page.waitForURL('**/models', { timeout: 15000 })
      return
    } catch (err) {
      if (attempt === maxRetries) throw err
      // Wait before retrying
      await page.waitForTimeout(1000 * attempt)
    }
  }
}

/**
 * Load seed data from the JSON file written by seed_e2e_auth.py.
 */
export function loadSeedData(): SeedData {
  const filePath = resolve(__dirname, '..', '.seed-data.json')
  return JSON.parse(readFileSync(filePath, 'utf-8')) as SeedData
}

export interface SeedData {
  owner: { username: string; password: string }
  viewer: { username: string; password: string }
  sa1: { id: string; key: string; name: string }
  sa2: { id: string; key: string; name: string }
  model_a: { id: string; name: string }
  model_b: { id: string; name: string }
  version_a: { id: string; version: string }
  job_a: { id: string }
}
