import { test, expect } from '@playwright/test'
import { login, loadSeedData } from './helpers/auth'

const V1 = 'e2e-cmp-v1'
const V2 = 'e2e-cmp-v2'

let ids: { modelId: string; v1Id: string }
let owner: ReturnType<typeof loadSeedData>['owner']

test.beforeAll(async ({ playwright }) => {
  const seed = loadSeedData()
  owner = seed.owner
  const api = await playwright.request.newContext({ baseURL: test.info().project.use.baseURL })

  const loginResp = await api.post('/api/v1/auth/login', {
    data: { username: owner.username, password: owner.password },
  })
  expect(loginResp.ok()).toBeTruthy()
  const headers = { Authorization: `Bearer ${(await loginResp.json()).data.access_token}` }

  async function post(url: string, data: unknown) {
    const resp = await api.post(url, { data, headers })
    expect(resp.ok(), `${url}: ${await resp.text()}`).toBeTruthy()
    return (await resp.json()).data
  }

  const model = await post('/api/v1/models', { name: `E2E-Compare-${Date.now()}` })
  // v2 drops "region" and changes the type of "income"
  const v1 = await post(`/api/v1/models/${model.id}/versions`, {
    version: V1,
    schema: [
      { direction: 'input', field_name: 'age', data_type: 'numerical' },
      { direction: 'input', field_name: 'region', data_type: 'categorical' },
      { direction: 'input', field_name: 'income', data_type: 'numerical' },
      { direction: 'output', field_name: 'score', data_type: 'numerical' },
    ],
  })
  const v2 = await post(`/api/v1/models/${model.id}/versions`, {
    version: V2,
    schema: [
      { direction: 'input', field_name: 'age', data_type: 'numerical' },
      { direction: 'input', field_name: 'income', data_type: 'categorical' },
      { direction: 'output', field_name: 'score', data_type: 'numerical' },
    ],
  })

  // Day offsets stay inside the default period A (last 7 days up to today 00:00)
  const daysAgo = (d: number) => new Date(Date.now() - d * 86_400_000).toISOString()
  const records = (version: { inputs: (i: number) => object }) =>
    [1, 2, 3, 4, 5].map((i) => ({
      inputs: version.inputs(i),
      outputs: { score: i / 10 },
      timestamp: daysAgo(i),
    }))
  await post('/api/v1/inferences/batch', {
    model_version_id: v1.id,
    records: records({ inputs: (i) => ({ age: 20 + i, region: i % 2 ? 'north' : 'south', income: 1000 * i }) }),
  })
  await post('/api/v1/inferences/batch', {
    model_version_id: v2.id,
    records: records({ inputs: (i) => ({ age: 30 + i, income: i % 2 ? 'low' : 'high' }) }),
  })

  await api.dispose()
  ids = { modelId: model.id, v1Id: v1.id }
})

test.describe('Comparison - Other version', () => {
  test('compares v1 with v2 and reports fields that are not comparable', async ({ context, page }) => {
    await context.clearCookies()
    await login(page, owner.username, owner.password)
    await page.goto(`/models/${ids.modelId}/versions/${ids.v1Id}/compare`, { waitUntil: 'networkidle' })

    const panel = (field: string) => page.locator('.v-card-title').filter({ hasText: field })
    const notCompared = page.getByRole('alert').filter({ hasText: 'Fields not compared' })

    // Time window mode: all v1 fields are shown
    for (const field of ['age', 'region', 'income', 'score']) {
      await expect(panel(field)).toBeVisible({ timeout: 10000 })
    }

    // Other version mode: v2 is preselected, only shared fields of the same type are compared
    await page.getByRole('button', { name: 'Other version' }).click()
    await expect(page.locator('.v-select').filter({ hasText: 'Version' })).toContainText(V2, { timeout: 10000 })
    await expect(panel('age')).toBeVisible({ timeout: 10000 })
    await expect(panel('score')).toBeVisible()
    await expect(panel('region')).toHaveCount(0)
    await expect(panel('income')).toHaveCount(0)

    await expect(notCompared).toBeVisible()
    await expect(notCompared.locator('li').filter({ hasText: 'region' })).toContainText(`only in ${V1}`)
    await expect(notCompared.locator('li').filter({ hasText: 'income' })).toContainText(
      'type changed: numerical → categorical',
    )

    // Back to time window mode: period B is restored and the comparison renders again
    await page.getByRole('button', { name: 'Time Window' }).click()
    await expect(page.getByText('Period B (Baseline)')).toBeVisible()
    await expect(notCompared).toHaveCount(0)
    await expect(panel('region')).toBeVisible({ timeout: 10000 })
  })
})
