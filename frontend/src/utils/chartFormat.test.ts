import { describe, it, expect } from 'vitest'
import type { CategoryCount, HistogramBucket } from '@/types'
import {
  aggregateGroupedCategories,
  aggregateTopCategories,
  bucketTooltipTitle,
  categoryDisplayName,
  countAxis,
  countBarStyle,
  escapeHtml,
  formatBucketLabel,
  formatBucketLabels,
  formatCompactNumber,
  isHorizontalLayout,
  plotCount,
} from './chartFormat'

const bucket = (overrides: Partial<HistogramBucket> = {}): HistogramBucket => ({
  range_start: 1.2,
  range_end: 3.4,
  count: 5,
  ...overrides,
})

const cat = (value: string, count: number, percentage = 0): CategoryCount => ({
  value,
  count,
  percentage,
})

describe('formatCompactNumber', () => {
  it('formats zero and small integers plainly', () => {
    expect(formatCompactNumber(0)).toBe('0')
    expect(formatCompactNumber(42)).toBe('42')
  })

  it('compacts large numbers', () => {
    expect(formatCompactNumber(1500)).toBe('1.5K')
    expect(formatCompactNumber(2_300_000)).toBe('2.3M')
    expect(formatCompactNumber(-12345)).toBe('-12.3K')
  })

  it('keeps three significant digits for fractions', () => {
    expect(formatCompactNumber(0.123456)).toBe('0.123')
  })

  it('keeps tiny numbers distinguishable', () => {
    expect(formatCompactNumber(0.00012345)).toBe('0.000123')
    expect(formatCompactNumber(1.2345e-7)).toBe('1.23e-7')
    expect(formatCompactNumber(0.0005)).not.toBe(formatCompactNumber(0.0006))
  })

  it('uses plain digits derived from the bin width for narrow ranges', () => {
    expect(formatCompactNumber(100.5, 0.5)).toBe('100.5')
    expect(formatCompactNumber(1000.5, 0.5)).toBe('1,000.5')
    expect(formatCompactNumber(1.7e9, 5)).toBe('1,700,000,000')
  })

  it('uses a fixed locale independent of the browser', () => {
    expect(formatCompactNumber(1500, undefined)).toBe('1.5K')
    expect(formatCompactNumber(0.5, 0.01)).toBe('0.5')
  })

  it('does not throw on non-finite values', () => {
    expect(formatCompactNumber(Number.NaN)).toBe('NaN')
  })
})

describe('formatBucketLabel', () => {
  it('formats a regular bucket as a range', () => {
    expect(formatBucketLabel(bucket())).toBe('1.2–3.4')
  })

  it('formats an underflow bucket', () => {
    expect(formatBucketLabel(bucket({ range_start: -50, range_end: 1.2, is_underflow: true }))).toBe('<1.2')
  })

  it('formats an overflow bucket', () => {
    expect(formatBucketLabel(bucket({ range_start: 98.7, range_end: 5000, is_overflow: true }))).toBe('>98.7')
  })

  it('collapses a zero-width bucket to a single value', () => {
    expect(formatBucketLabel(bucket({ range_start: 7, range_end: 7 }))).toBe('7')
  })

  it('produces distinct labels for tiny ranges', () => {
    const a = formatBucketLabel(bucket({ range_start: 0.001, range_end: 0.00145 }))
    const b = formatBucketLabel(bucket({ range_start: 0.00145, range_end: 0.0019 }))
    expect(a).not.toBe(b)
  })
})

describe('escapeHtml', () => {
  it('escapes HTML in tooltip text', () => {
    expect(escapeHtml('<img src=x onerror=alert(1)>')).not.toContain('<img')
  })
})

describe('formatBucketLabels', () => {
  const regularBuckets = (start: number, end: number, n = 20): HistogramBucket[] =>
    Array.from({ length: n }, (_, i) => ({
      range_start: start + ((end - start) * i) / n,
      range_end: start + ((end - start) * (i + 1)) / n,
      count: 1,
    }))

  const expectDistinctEdges = (start: number, end: number) => {
    const buckets = regularBuckets(start, end)
    const labels = formatBucketLabels(buckets)
    expect(new Set(labels).size).toBe(buckets.length)
    for (const label of labels) {
      const [lo, hi] = label.split('–')
      expect(lo).not.toBe(hi)
    }
  }

  it('keeps adjacent labels distinct for 100..102', () => {
    expectDistinctEdges(100, 102)
  })

  it('keeps adjacent labels distinct for 1000..1001', () => {
    expectDistinctEdges(1000, 1001)
  })

  it('keeps adjacent labels distinct for 100..110', () => {
    expectDistinctEdges(100, 110)
  })

  it.each([
    [0, 1],
    [0, 7],
    [0.001, 0.01],
    [1e-7, 2e-7],
    [-5, 5],
    [1.7e9, 1.7e9 + 100],
    [1234.5, 1240],
    [0, 1e6],
    [95, 105],
  ])('keeps labels distinct for %s..%s', (start, end) => {
    expectDistinctEdges(start, end)
  })

  it('uses the regular bin width for the outlier labels', () => {
    const buckets: HistogramBucket[] = [
      { range_start: 0, range_end: 100.5, count: 1, is_underflow: true },
      ...regularBuckets(100.5, 102.5, 4),
      { range_start: 102.5, range_end: 5000, count: 1, is_overflow: true },
    ]
    const labels = formatBucketLabels(buckets)
    expect(labels[0]).toBe('<100.5')
    expect(labels[1]).toBe('100.5–101')
    expect(labels[5]).toBe('>102.5')
  })

  it('handles a single zero-width bucket', () => {
    expect(formatBucketLabels([bucket({ range_start: 7, range_end: 7 })])).toEqual(['7'])
  })
})

describe('bucketTooltipTitle', () => {
  it('shows the exact range', () => {
    expect(bucketTooltipTitle(bucket())).toBe('1.2 – 3.4')
  })

  it('adds a note for outlier buckets', () => {
    expect(bucketTooltipTitle(bucket({ is_underflow: true }))).toContain('below the 1st percentile')
    expect(bucketTooltipTitle(bucket({ is_overflow: true }))).toContain('above the 99th percentile')
  })
})

describe('isHorizontalLayout', () => {
  it('is false for short labels', () => {
    expect(isHorizontalLayout(['a', 'male', 'female'])).toBe(false)
  })

  it('is false for the short Other label of aggregated categories', () => {
    const categories = Array.from({ length: 15 }, (_, i) => cat(`c${i}`, i + 1))
    expect(isHorizontalLayout(aggregateTopCategories(categories).map((b) => b.label))).toBe(false)
  })

  it('is true if any label is longer than the threshold', () => {
    expect(isHorizontalLayout(['a', 'a-very-long-category'])).toBe(true)
  })
})

describe('categoryDisplayName', () => {
  it('expands the Other label for tooltips', () => {
    expect(categoryDisplayName('Other (3)', 3)).toBe('Other (3 categories)')
    expect(categoryDisplayName('Other (1)', 1)).toBe('Other (1 category)')
    expect(categoryDisplayName('male')).toBe('male')
  })
})

describe('aggregateTopCategories', () => {
  it('returns all categories if there are not more than topN', () => {
    const bars = aggregateTopCategories([cat('a', 2), cat('b', 5)], 3)
    expect(bars.map((b) => b.label)).toEqual(['b', 'a'])
    expect(bars.some((b) => b.otherCount)).toBe(false)
  })

  it('sums the remaining categories into an Other bar', () => {
    const categories = [cat('a', 10, 50), cat('b', 5, 25), cat('c', 3, 15), cat('d', 2, 10)]
    const bars = aggregateTopCategories(categories, 2)
    expect(bars).toHaveLength(3)
    expect(bars[2]).toEqual({
      label: 'Other (2)',
      count: 5,
      percentage: 25,
      otherCount: 2,
    })
  })

  it('uses the singular for a single remaining category', () => {
    const bars = aggregateTopCategories([cat('a', 3), cat('b', 2)], 1)
    expect(bars[1]!.label).toBe('Other (1)')
  })

  it('keeps the total count', () => {
    const categories = Array.from({ length: 15 }, (_, i) => cat(`c${i}`, i + 1))
    const bars = aggregateTopCategories(categories)
    expect(bars).toHaveLength(11)
    expect(bars.reduce((s, b) => s + b.count, 0)).toBe(categories.reduce((s, c) => s + c.count, 0))
  })

  it('handles empty input', () => {
    expect(aggregateTopCategories([])).toEqual([])
  })
})

describe('aggregateGroupedCategories', () => {
  it('merges categories of both series with zero for missing ones', () => {
    const bars = aggregateGroupedCategories([cat('a', 4)], [cat('a', 1), cat('b', 2)], 5)
    expect(bars).toEqual([
      { label: 'a', countA: 4, countB: 1 },
      { label: 'b', countA: 0, countB: 2 },
    ])
  })

  it('sums the rest per series into Other', () => {
    const a = [cat('x', 10), cat('y', 4), cat('z', 1)]
    const b = [cat('x', 8), cat('y', 3), cat('w', 2)]
    const bars = aggregateGroupedCategories(a, b, 1)
    expect(bars[0]).toMatchObject({ label: 'x', countA: 10, countB: 8 })
    expect(bars[1]).toEqual({
      label: 'Other (3)',
      countA: 5,
      countB: 5,
      otherCount: 3,
    })
  })
})

describe('count axis helpers', () => {
  it('switches the axis type and keeps the name', () => {
    expect(countAxis()).toEqual({ type: 'value', name: 'Count' })
    expect(countAxis(true)).toEqual({ type: 'log', name: 'Count', min: 1 })
  })

  it('drops zero counts only on the log axis', () => {
    expect(plotCount(0, true)).toBeNull()
    expect(plotCount(0)).toBe(0)
    expect(plotCount(4, true)).toBe(4)
  })

  it('gives bars a minimum height only on the log axis', () => {
    expect(countBarStyle(true).barMinHeight).toBeGreaterThan(0)
    expect(countBarStyle().barMinHeight).toBe(0)
  })
})
