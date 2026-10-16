import { format } from 'echarts/core'
import type { CategoryCount, HistogramBucket } from '@/types'

export const TOP_CATEGORIES = 10
export const HORIZONTAL_LABEL_THRESHOLD = 12

/**
 * Format a number compactly (1.5K, 2.3M); tiny values use few significant digits / exponent.
 */
export function formatCompactNumber(value: number, locale?: string): string {
  if (!Number.isFinite(value)) return String(value)
  if (value === 0) return '0'
  if (Math.abs(value) < 0.001) return String(Number(value.toPrecision(3)))
  return new Intl.NumberFormat(locale, {
    notation: 'compact',
    maximumSignificantDigits: 3,
  }).format(value)
}

/**
 * Short axis label for a histogram bucket: "<1.2" (underflow), "≥98.7" (overflow), "1.2–3.4".
 */
export function formatBucketLabel(bucket: HistogramBucket, locale?: string): string {
  if (bucket.is_underflow) return `<${formatCompactNumber(bucket.range_end, locale)}`
  if (bucket.is_overflow) return `≥${formatCompactNumber(bucket.range_start, locale)}`
  const start = formatCompactNumber(bucket.range_start, locale)
  if (bucket.range_start === bucket.range_end) return start
  return `${start}–${formatCompactNumber(bucket.range_end, locale)}`
}

/** Truncate a label to at most `max` characters, ending with an ellipsis. */
export function truncateLabel(label: string, max: number): string {
  if (label.length <= max) return label
  return `${label.slice(0, Math.max(max - 1, 1))}…`
}

/** Escape text for ECharts HTML tooltips. */
export function escapeHtml(text: string): string {
  return format.encodeHTML(text)
}

/** Tooltip title with the exact bucket range (escaped) and a note for outlier buckets. */
export function bucketTooltipTitle(bucket: HistogramBucket): string {
  const range = `${bucket.range_start} – ${bucket.range_end}`
  let html = escapeHtml(range)
  if (bucket.is_underflow) html += '<br/><i>Outliers below the 1st percentile (p1)</i>'
  if (bucket.is_overflow) html += '<br/><i>Outliers above the 99th percentile (p99)</i>'
  return html
}

/** Use horizontal bars if any label is too long to read below a vertical bar. */
export function isHorizontalLayout(labels: string[], threshold = HORIZONTAL_LABEL_THRESHOLD): boolean {
  return labels.some((l) => l.length > threshold)
}

export interface CategoryBar {
  label: string
  count: number
  percentage: number
  /** Number of aggregated categories if this is the "Other" bar. */
  otherCount?: number
}

function otherLabel(n: number): string {
  return `Other (${n} ${n === 1 ? 'category' : 'categories'})`
}

/** Keep the `topN` most frequent categories and sum the rest into one "Other" bar. */
export function aggregateTopCategories(categories: CategoryCount[], topN = TOP_CATEGORIES): CategoryBar[] {
  const sorted = [...categories].sort((a, b) => b.count - a.count)
  const bars: CategoryBar[] = sorted
    .slice(0, topN)
    .map((c) => ({ label: c.value, count: c.count, percentage: c.percentage }))
  const rest = sorted.slice(topN)
  if (rest.length > 0) {
    bars.push({
      label: otherLabel(rest.length),
      count: rest.reduce((sum, c) => sum + c.count, 0),
      percentage: rest.reduce((sum, c) => sum + c.percentage, 0),
      otherCount: rest.length,
    })
  }
  return bars
}

export interface GroupedCategoryBar {
  label: string
  countA: number
  countB: number
  otherCount?: number
}

/** Top `topN` categories by combined count across both datasets; the rest is summed per series into "Other". */
export function aggregateGroupedCategories(
  a: CategoryCount[],
  b: CategoryCount[],
  topN = TOP_CATEGORIES
): GroupedCategoryBar[] {
  const merged = new Map<string, { countA: number; countB: number }>()
  for (const c of a) merged.set(c.value, { countA: c.count, countB: 0 })
  for (const c of b) {
    const entry = merged.get(c.value)
    if (entry) entry.countB = c.count
    else merged.set(c.value, { countA: 0, countB: c.count })
  }

  const sorted = [...merged.entries()]
    .map(([label, counts]) => ({ label, ...counts }))
    .sort((x, y) => y.countA + y.countB - (x.countA + x.countB))
  const bars: GroupedCategoryBar[] = sorted.slice(0, topN)
  const rest = sorted.slice(topN)
  if (rest.length > 0) {
    bars.push({
      label: otherLabel(rest.length),
      countA: rest.reduce((sum, c) => sum + c.countA, 0),
      countB: rest.reduce((sum, c) => sum + c.countB, 0),
      otherCount: rest.length,
    })
  }
  return bars
}
