import { describe, it, expect } from 'vitest'
import type { ComparisonPanel, HistogramData, CategoricalData, DriftScore } from '@/types'

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
