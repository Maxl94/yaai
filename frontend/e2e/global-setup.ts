/**
 * Global setup for auth-separation E2E tests.
 *
 * Starts the docker-compose test stack and runs the seed script.
 * Run from project root: npx playwright test --config playwright.e2e.config.ts
 */
import { execSync } from 'child_process'

export default async function globalSetup() {
  const projectRoot = new URL('../../', import.meta.url).pathname

  console.log('[global-setup] Starting docker-compose test stack...')
  execSync('docker compose -f docker-compose.test.yml up -d --build --wait', {
    cwd: projectRoot,
    stdio: 'inherit',
    timeout: 300_000, // 5 minutes for build + start
  })

  console.log('[global-setup] Running seed script...')
  execSync('uv run python scripts/seed_e2e_auth.py', {
    cwd: projectRoot,
    stdio: 'inherit',
    timeout: 60_000,
  })

  console.log('[global-setup] Ready.')
}
