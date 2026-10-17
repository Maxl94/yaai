import { format } from 'echarts/core'
import type { CategoryCount, HistogramBucket } from '@/types'

const TOP_CATEGORIES = 10
const HORIZONTAL_LABEL_THRESHOLD = 12

/** Labels always use one locale so decimal separators match the tooltips and statistics. */
const LABEL_LOCALE = 'en-US'

/** Compact notation is only used if the bin width is at least this fraction of the value. */
const COMPACT_MIN_WIDTH_RATIO = 0.01
const MAX_PLAIN_DECIMALS = 8

/**
 * Format a number for an axis label. With a bin `width`, the precision is chosen so that edges one bin
 * apart stay distinguishable (compact notation only if the width is >= 1% of the value); without a width,
 * three significant digits are used.
 */
export function formatCompactNumber(value: number, width?: number, locale = LABEL_LOCALE): string {
  if (!Number.isFinite(value)) return String(value)
  if (value === 0) return '0'
  const compact = new Intl.NumberFormat(locale, {
    notation: 'compact',
    maximumSignificantDigits: 3,
  })
  if (width === undefined || !Number.isFinite(width) || width <= 0) {
    return Math.abs(value) < 0.001 ? String(Number(value.toPrecision(3))) : compact.format(value)
  }
  if (width >= COMPACT_MIN_WIDTH_RATIO * Math.abs(value)) return compact.format(value)
  const decimals = Math.max(0, Math.ceil(-Math.log10(width)) + 1)
  if (decimals > MAX_PLAIN_DECIMALS) {
    const digits = Math.min(Math.max(Math.ceil(Math.log10(Math.abs(value) / width)) + 2, 3), 15)
    return String(Number(value.toPrecision(digits)))
  }
  return new Intl.NumberFormat(locale, {
    maximumFractionDigits: decimals,
  }).format(value)
}

/**
 * Short axis label for a histogram bucket: "<1.2" (underflow), ">98.7" (overflow), "1.2–3.4".
 * `width` is the width of the regular bins (defaults to the bucket's own width).
 */
export function formatBucketLabel(bucket: HistogramBucket, width?: number, locale = LABEL_LOCALE): string {
  if (bucket.is_underflow) return `<${formatCompactNumber(bucket.range_end, width, locale)}`
  if (bucket.is_overflow) return `>${formatCompactNumber(bucket.range_start, width, locale)}`
  const binWidth = width ?? bucket.range_end - bucket.range_start
  const start = formatCompactNumber(bucket.range_start, binWidth, locale)
  if (bucket.range_start === bucket.range_end) return start
  return `${start}–${formatCompactNumber(bucket.range_end, binWidth, locale)}`
}

/** Axis labels for all buckets, using the width of the regular bins for every label. */
export function formatBucketLabels(buckets: HistogramBucket[], locale = LABEL_LOCALE): string[] {
  const regular = buckets.find((b) => !b.is_underflow && !b.is_overflow)
  const width = regular ? regular.range_end - regular.range_start : undefined
  return buckets.map((b) => formatBucketLabel(b, width, locale))
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

interface CategoryBar {
  label: string
  count: number
  percentage: number
  /** Number of aggregated categories if this is the "Other" bar. */
  otherCount?: number
}

/** Full text for tooltips; the short "Other (N)" axis label is expanded. */
export function categoryDisplayName(label: string, otherCount?: number): string {
  if (!otherCount) return label
  return `Other (${otherCount} ${otherCount === 1 ? 'category' : 'categories'})`
}

/** Fields of the summed "Other" bar that replaces all categories beyond the top N. */
const otherLabel = (rest: unknown[]) => ({ label: `Other (${rest.length})`, otherCount: rest.length })

const sumBy = <T>(items: T[], key: (item: T) => number) => items.reduce((sum, item) => sum + key(item), 0)

/** Keep the `topN` most frequent categories and sum the rest into one "Other" bar. */
export function aggregateTopCategories(categories: CategoryCount[], topN = TOP_CATEGORIES): CategoryBar[] {
  const sorted = categories
    .map((c) => ({ label: c.value, count: c.count, percentage: c.percentage }))
    .sort((a, b) => b.count - a.count)
  const bars = sorted.slice(0, topN)
  const rest = sorted.slice(topN)
  if (rest.length > 0) {
    bars.push({
      ...otherLabel(rest),
      count: sumBy(rest, (c) => c.count),
      percentage: sumBy(rest, (c) => c.percentage),
    })
  }
  return bars
}

interface GroupedCategoryBar {
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
  const bars = sorted.slice(0, topN)
  const rest = sorted.slice(topN)
  if (rest.length > 0) {
    bars.push({
      ...otherLabel(rest),
      countA: sumBy(rest, (c) => c.countA),
      countB: sumBy(rest, (c) => c.countB),
    })
  }
  return bars
}
