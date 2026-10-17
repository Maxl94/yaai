import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import ComparisonPage from './ComparisonPage.vue'
import { modelsApi } from '@/api/models'
import { dashboardApi } from '@/api/dashboard'
import type { ComparisonPanel, HistogramData, CategoricalData, DriftScore, SchemaDiffItem } from '@/types'

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { modelId: 'm1', versionId: 'v2' } }),
}))
vi.mock('@/api/models', () => ({
  modelsApi: { get: vi.fn(), getVersion: vi.fn(), list: vi.fn(), listVersions: vi.fn() },
}))
vi.mock('@/api/dashboard', () => ({ dashboardApi: { getComparison: vi.fn() } }))

// Pure functions extracted from ComparisonPage.vue for testing.

function getDefaultDate(daysOffset: number): string {
  const date = new Date()
  date.setDate(date.getDate() + daysOffset)
  return date.toISOString().split('T')[0] || ''
}

function isHistogramData(data: HistogramData | CategoricalData): data is HistogramData {
  return 'buckets' in data
}

function getDriftColor(panel: ComparisonPanel): string {
  if (!panel.drift_score) return 'grey'
  return panel.drift_score.is_drifted ? 'warning' : 'success'
}

function makePanel(overrides: Partial<ComparisonPanel> = {}): ComparisonPanel {
  return {
    field_name: 'age',
    direction: 'input',
    data_type: 'numerical',
    chart_type: 'histogram',
    data_a: { buckets: [], statistics: { mean: 0, median: 0, std: 0, min: 0, max: 0, count: 0, null_count: 0 } },
    data_b: { buckets: [], statistics: { mean: 0, median: 0, std: 0, min: 0, max: 0, count: 0, null_count: 0 } },
    ...overrides,
  }
}

describe('getDefaultDate', () => {
  it('returns today for offset 0', () => {
    const today = new Date().toISOString().split('T')[0]
    expect(getDefaultDate(0)).toBe(today)
  })

  it('returns yesterday for offset -1', () => {
    const yesterday = new Date()
    yesterday.setDate(yesterday.getDate() - 1)
    expect(getDefaultDate(-1)).toBe(yesterday.toISOString().split('T')[0])
  })

  it('returns a future date for positive offset', () => {
    const future = new Date()
    future.setDate(future.getDate() + 7)
    expect(getDefaultDate(7)).toBe(future.toISOString().split('T')[0])
  })

  it('returns YYYY-MM-DD format', () => {
    const result = getDefaultDate(0)
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })
})

describe('isHistogramData', () => {
  it('returns true for histogram data', () => {
    const data: HistogramData = {
      buckets: [{ range_start: 0, range_end: 10, count: 5 }],
      statistics: { mean: 5, median: 5, std: 1, min: 0, max: 10, count: 5, null_count: 0 },
    }
    expect(isHistogramData(data)).toBe(true)
  })

  it('returns false for categorical data', () => {
    const data: CategoricalData = {
      categories: [{ value: 'a', count: 5, percentage: 100 }],
      statistics: { unique_count: 1, total_count: 5, null_count: 0, top_category: 'a' },
    }
    expect(isHistogramData(data)).toBe(false)
  })
})

describe('getDriftColor', () => {
  it('returns grey when no drift score', () => {
    expect(getDriftColor(makePanel())).toBe('grey')
  })

  it('returns warning when drifted', () => {
    const score: DriftScore = { metric_name: 'psi', metric_value: 0.5, is_drifted: true, threshold: 0.1 }
    expect(getDriftColor(makePanel({ drift_score: score }))).toBe('warning')
  })

  it('returns success when not drifted', () => {
    const score: DriftScore = { metric_name: 'psi', metric_value: 0.05, is_drifted: false, threshold: 0.1 }
    expect(getDriftColor(makePanel({ drift_score: score }))).toBe('success')
  })
})

describe('ComparisonPage', () => {
  const diff: SchemaDiffItem = {
    field_name: 'score',
    direction: 'output',
    status: 'type_changed',
    data_type_a: 'numerical',
    data_type_b: 'categorical',
  }

  async function mountPage() {
    const wrapper = mount(ComparisonPage, {
      global: {
        plugins: [createVuetify({ components, directives })],
        stubs: { VersionNavTabs: true, OverlaidHistogram: true, GroupedBarChart: true, StatsSummary: true },
      },
    })
    await flushPromises()
    return wrapper
  }

  async function switchToOtherVersion(wrapper: Awaited<ReturnType<typeof mountPage>>) {
    const btn = wrapper.findAll('button').find((b) => b.text() === 'Other version')!
    await btn.trigger('click')
    await flushPromises()
  }

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(modelsApi.get).mockResolvedValue({ id: 'm1', name: 'Model' } as never)
    vi.mocked(modelsApi.getVersion).mockResolvedValue({ id: 'v2', version: 'v2' } as never)
    vi.mocked(modelsApi.list).mockResolvedValue([{ id: 'm1', name: 'Model' }] as never)
    vi.mocked(modelsApi.listVersions).mockResolvedValue([
      { id: 'v2', version: 'v2' },
      { id: 'v1', version: 'v1' },
    ] as never)
    vi.mocked(dashboardApi.getComparison).mockResolvedValue({ model_version_id: 'v2', panels: [], schema_diff: [] })
  })

  it('keeps time_window params unchanged', async () => {
    await mountPage()
    const [, , params] = vi.mocked(dashboardApi.getComparison).mock.calls[0]!
    expect(params.mode).toBe('time_window')
    expect(params).not.toHaveProperty('other_version_id')
  })

  it('sends other model/version and same period B as A in vs_version mode', async () => {
    const wrapper = await mountPage()
    await switchToOtherVersion(wrapper)
    const [modelId, versionId, params] = vi.mocked(dashboardApi.getComparison).mock.lastCall!
    expect([modelId, versionId]).toEqual(['m1', 'v2'])
    expect(params).toMatchObject({
      mode: 'vs_version',
      other_model_id: 'm1',
      other_version_id: 'v1',
    })
    expect(params.from_b).toBe(params.from_a)
    expect(params.to_b).toBe(params.to_a)
  })

  it('renders schema_diff as fields not compared', async () => {
    vi.mocked(dashboardApi.getComparison).mockResolvedValue({
      model_version_id: 'v2',
      panels: [],
      schema_diff: [diff],
    })
    const wrapper = await mountPage()
    await switchToOtherVersion(wrapper)
    expect(wrapper.text()).toContain('Fields not compared')
    expect(wrapper.text()).toContain('score (output): type changed: numerical → categorical')
  })
})
