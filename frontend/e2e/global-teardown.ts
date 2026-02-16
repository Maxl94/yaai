/**
 * Global teardown for auth-separation E2E tests.
 *
 * Stops and removes the docker-compose test stack.
 */
import { execSync } from 'child_process'

export default async function globalTeardown() {
  const projectRoot = new URL('../../', import.meta.url).pathname

  console.log('[global-teardown] Stopping docker-compose test stack...')
  execSync('docker compose -f docker-compose.test.yml down -v', {
    cwd: projectRoot,
    stdio: 'inherit',
    timeout: 60_000,
  })

  console.log('[global-teardown] Done.')
}
