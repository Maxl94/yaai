import { describe, it, expect } from 'vitest'
import type { DriftResult, DriftOverviewItem } from '@/types'

// Extract and test the pure logic functions used in DriftResultsPage.
// These mirror the functions defined inside the component's <script setup>.

function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function formatRelativeDate(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

function getOverviewLatestScore(item: DriftOverviewItem): number | null {
  if (item.results.length === 0) return null
  const sorted = [...item.results].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  )
  return sorted[0]!.score
}

function getOverviewAvgScore(item: DriftOverviewItem): number {
  if (item.results.length === 0) return 0
  return item.results.reduce((sum, r) => sum + r.score, 0) / item.results.length
}

function getOverviewMaxScore(item: DriftOverviewItem): number {
  if (item.results.length === 0) return 0
  return Math.max(...item.results.map(r => r.score))
}

function makeResult(overrides: Partial<DriftResult> = {}): DriftResult {
  return {
    id: '1',
    job_run_id: null,
    schema_field_id: 'f1',
    field_name: 'age',
    metric_name: 'psi',
    score: 0.05,
    threshold: 0.1,
    is_drifted: false,
    details: {},
    created_at: '2026-01-15T10:00:00Z',
    ...overrides,
  }
}

function makeOverviewItem(overrides: Partial<DriftOverviewItem> = {}): DriftOverviewItem {
  return {
    model_id: 'm1',
    model_name: 'Test Model',
    model_description: null,
    version_id: 'v1',
    version: 'v1.0',
    total_inferences: 1000,
    total_fields: 5,
    drifted_fields: 1,
    health_percentage: 80,
    last_check: '2026-01-15T10:00:00Z',
    results: [],
    ...overrides,
  }
}

describe('formatDate', () => {
  it('formats ISO string to YYYY-MM-DD', () => {
    expect(formatDate('2026-01-05T14:30:00Z')).toBe('2026-01-05')
  })

  it('pads single-digit months and days', () => {
    expect(formatDate('2026-03-09T00:00:00Z')).toBe('2026-03-09')
  })
})

describe('formatRelativeDate', () => {
  it('returns "just now" for very recent timestamps', () => {
    const now = new Date().toISOString()
    expect(formatRelativeDate(now)).toBe('just now')
  })

  it('returns minutes ago', () => {
    const fiveMinAgo = new Date(Date.now() - 5 * 60000).toISOString()
    expect(formatRelativeDate(fiveMinAgo)).toBe('5m ago')
  })

  it('returns hours ago', () => {
    const threeHoursAgo = new Date(Date.now() - 3 * 3600000).toISOString()
    expect(formatRelativeDate(threeHoursAgo)).toBe('3h ago')
  })

  it('returns days ago', () => {
    const twoDaysAgo = new Date(Date.now() - 2 * 86400000).toISOString()
    expect(formatRelativeDate(twoDaysAgo)).toBe('2d ago')
  })
})

describe('getOverviewLatestScore', () => {
  it('returns null for empty results', () => {
    const item = makeOverviewItem({ results: [] })
    expect(getOverviewLatestScore(item)).toBeNull()
  })

  it('returns the score of the most recent result', () => {
    const item = makeOverviewItem({
      results: [
        makeResult({ score: 0.05, created_at: '2026-01-10T10:00:00Z' }),
        makeResult({ score: 0.20, created_at: '2026-01-15T10:00:00Z' }),
        makeResult({ score: 0.10, created_at: '2026-01-12T10:00:00Z' }),
      ],
    })
    expect(getOverviewLatestScore(item)).toBe(0.20)
  })
})

describe('getOverviewAvgScore', () => {
  it('returns 0 for empty results', () => {
    const item = makeOverviewItem({ results: [] })
    expect(getOverviewAvgScore(item)).toBe(0)
  })

  it('computes the average score', () => {
    const item = makeOverviewItem({
      results: [
        makeResult({ score: 0.10 }),
        makeResult({ score: 0.20 }),
        makeResult({ score: 0.30 }),
      ],
    })
    expect(getOverviewAvgScore(item)).toBeCloseTo(0.20)
  })
})

describe('getOverviewMaxScore', () => {
  it('returns 0 for empty results', () => {
    const item = makeOverviewItem({ results: [] })
    expect(getOverviewMaxScore(item)).toBe(0)
  })

  it('returns the maximum score', () => {
    const item = makeOverviewItem({
      results: [
        makeResult({ score: 0.05 }),
        makeResult({ score: 0.42 }),
        makeResult({ score: 0.15 }),
      ],
    })
    expect(getOverviewMaxScore(item)).toBe(0.42)
  })
})

// --- Field-level helper functions (used in version-specific view) ---

function getFieldResults(allResults: DriftResult[], fieldName: string): DriftResult[] {
  return allResults
    .filter(r => r.field_name === fieldName)
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
}

function getFieldDriftStatus(allResults: DriftResult[], fieldName: string): boolean {
  const fieldResults = getFieldResults(allResults, fieldName)
  const latestResult = fieldResults[0]
  return !!latestResult && latestResult.is_drifted
}

function getFieldLatestScore(allResults: DriftResult[], fieldName: string): number {
  const results = getFieldResults(allResults, fieldName)
  return results[0]?.score ?? 0
}

function getFieldAvgScore(allResults: DriftResult[], fieldName: string): number {
  const results = getFieldResults(allResults, fieldName)
  if (results.length === 0) return 0
  return results.reduce((sum, r) => sum + r.score, 0) / results.length
}

function getFieldMaxScore(allResults: DriftResult[], fieldName: string): number {
  const results = getFieldResults(allResults, fieldName)
  if (results.length === 0) return 0
  return Math.max(...results.map(r => r.score))
}

describe('getFieldResults', () => {
  it('filters by field name', () => {
    const results = [
      makeResult({ field_name: 'age', score: 0.1 }),
      makeResult({ field_name: 'gender', score: 0.2 }),
      makeResult({ field_name: 'age', score: 0.3 }),
    ]
    expect(getFieldResults(results, 'age')).toHaveLength(2)
  })

  it('sorts by created_at descending', () => {
    const results = [
      makeResult({ field_name: 'age', score: 0.1, created_at: '2026-01-10T00:00:00Z' }),
      makeResult({ field_name: 'age', score: 0.3, created_at: '2026-01-15T00:00:00Z' }),
      makeResult({ field_name: 'age', score: 0.2, created_at: '2026-01-12T00:00:00Z' }),
    ]
    const sorted = getFieldResults(results, 'age')
    expect(sorted[0]!.score).toBe(0.3) // Jan 15 first
    expect(sorted[2]!.score).toBe(0.1) // Jan 10 last
  })

  it('returns empty array for unknown field', () => {
    expect(getFieldResults([makeResult()], 'unknown')).toHaveLength(0)
  })
})

describe('getFieldDriftStatus', () => {
  it('returns false when no results for field', () => {
    expect(getFieldDriftStatus([], 'age')).toBe(false)
  })

  it('returns true when latest result is drifted', () => {
    const results = [
      makeResult({ field_name: 'age', is_drifted: true, created_at: '2026-01-15T00:00:00Z' }),
      makeResult({ field_name: 'age', is_drifted: false, created_at: '2026-01-10T00:00:00Z' }),
    ]
    expect(getFieldDriftStatus(results, 'age')).toBe(true)
  })

  it('returns false when latest result is not drifted', () => {
    const results = [
      makeResult({ field_name: 'age', is_drifted: false, created_at: '2026-01-15T00:00:00Z' }),
      makeResult({ field_name: 'age', is_drifted: true, created_at: '2026-01-10T00:00:00Z' }),
    ]
    expect(getFieldDriftStatus(results, 'age')).toBe(false)
  })
})

describe('getFieldLatestScore', () => {
  it('returns 0 for empty results', () => {
    expect(getFieldLatestScore([], 'age')).toBe(0)
  })

  it('returns the most recent score', () => {
    const results = [
      makeResult({ field_name: 'age', score: 0.1, created_at: '2026-01-10T00:00:00Z' }),
      makeResult({ field_name: 'age', score: 0.5, created_at: '2026-01-15T00:00:00Z' }),
    ]
    expect(getFieldLatestScore(results, 'age')).toBe(0.5)
  })
})

describe('getFieldAvgScore', () => {
  it('returns 0 for empty results', () => {
    expect(getFieldAvgScore([], 'age')).toBe(0)
  })

  it('computes average for matching field', () => {
    const results = [
      makeResult({ field_name: 'age', score: 0.10 }),
      makeResult({ field_name: 'age', score: 0.20 }),
      makeResult({ field_name: 'age', score: 0.30 }),
      makeResult({ field_name: 'gender', score: 0.99 }), // should be excluded
    ]
    expect(getFieldAvgScore(results, 'age')).toBeCloseTo(0.20)
  })
})

describe('getFieldMaxScore', () => {
  it('returns 0 for empty results', () => {
    expect(getFieldMaxScore([], 'age')).toBe(0)
  })

  it('returns max for matching field', () => {
    const results = [
      makeResult({ field_name: 'age', score: 0.05 }),
      makeResult({ field_name: 'age', score: 0.42 }),
      makeResult({ field_name: 'age', score: 0.15 }),
    ]
    expect(getFieldMaxScore(results, 'age')).toBe(0.42)
  })
})
