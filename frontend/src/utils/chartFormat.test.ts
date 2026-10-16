import { describe, it, expect } from 'vitest'
import type { CategoryCount, HistogramBucket } from '@/types'
import {
  aggregateGroupedCategories,
  aggregateTopCategories,
  bucketTooltipTitle,
  escapeHtml,
  formatBucketLabel,
  formatCompactNumber,
  isHorizontalLayout,
  truncateLabel,
} from './chartFormat'

const bucket = (overrides: Partial<HistogramBucket> = {}): HistogramBucket => ({
  range_start: 1.2,
  range_end: 3.4,
  count: 5,
  ...overrides,
})

const cat = (value: string, count: number, percentage = 0): CategoryCount => ({ value, count, percentage })

describe('formatCompactNumber', () => {
  it('formats zero and small integers plainly', () => {
    expect(formatCompactNumber(0, 'en-US')).toBe('0')
    expect(formatCompactNumber(42, 'en-US')).toBe('42')
  })

  it('compacts large numbers', () => {
    expect(formatCompactNumber(1500, 'en-US')).toBe('1.5K')
    expect(formatCompactNumber(2_300_000, 'en-US')).toBe('2.3M')
    expect(formatCompactNumber(-12345, 'en-US')).toBe('-12.3K')
  })

  it('keeps three significant digits for fractions', () => {
    expect(formatCompactNumber(0.123456, 'en-US')).toBe('0.123')
  })

  it('keeps tiny numbers distinguishable', () => {
    expect(formatCompactNumber(0.00012345, 'en-US')).toBe('0.000123')
    expect(formatCompactNumber(1.2345e-7, 'en-US')).toBe('1.23e-7')
    expect(formatCompactNumber(0.0005, 'en-US')).not.toBe(formatCompactNumber(0.0006, 'en-US'))
  })

  it('does not throw on non-finite values', () => {
    expect(formatCompactNumber(Number.NaN)).toBe('NaN')
  })
})

describe('formatBucketLabel', () => {
  it('formats a regular bucket as a range', () => {
    expect(formatBucketLabel(bucket(), 'en-US')).toBe('1.2–3.4')
  })

  it('formats an underflow bucket', () => {
    expect(formatBucketLabel(bucket({ range_start: -50, range_end: 1.2, is_underflow: true }), 'en-US')).toBe('<1.2')
  })

  it('formats an overflow bucket', () => {
    expect(formatBucketLabel(bucket({ range_start: 98.7, range_end: 5000, is_overflow: true }), 'en-US')).toBe(
      '≥98.7'
    )
  })

  it('collapses a zero-width bucket to a single value', () => {
    expect(formatBucketLabel(bucket({ range_start: 7, range_end: 7 }), 'en-US')).toBe('7')
  })

  it('produces distinct labels for tiny ranges', () => {
    const a = formatBucketLabel(bucket({ range_start: 0.001, range_end: 0.00145 }), 'en-US')
    const b = formatBucketLabel(bucket({ range_start: 0.00145, range_end: 0.0019 }), 'en-US')
    expect(a).not.toBe(b)
  })
})

describe('truncateLabel', () => {
  it('keeps short labels', () => {
    expect(truncateLabel('abc', 5)).toBe('abc')
  })

  it('truncates long labels with an ellipsis', () => {
    expect(truncateLabel('abcdefghij', 5)).toBe('abcd…')
  })
})

describe('escapeHtml', () => {
  it('escapes HTML in tooltip text', () => {
    expect(escapeHtml('<img src=x onerror=alert(1)>')).not.toContain('<img')
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

  it('is true if any label is longer than the threshold', () => {
    expect(isHorizontalLayout(['a', 'a-very-long-category'])).toBe(true)
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
    expect(bars[2]).toEqual({ label: 'Other (2 categories)', count: 5, percentage: 25, otherCount: 2 })
  })

  it('uses the singular for a single remaining category', () => {
    const bars = aggregateTopCategories([cat('a', 3), cat('b', 2)], 1)
    expect(bars[1]!.label).toBe('Other (1 category)')
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
    expect(bars[1]).toEqual({ label: 'Other (3 categories)', countA: 5, countB: 5, otherCount: 3 })
  })
})
