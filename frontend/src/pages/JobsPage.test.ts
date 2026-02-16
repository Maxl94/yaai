import { describe, it, expect } from 'vitest'

// Pure functions extracted from JobsPage.vue for testing.

function describeSchedule(cron: string): string {
  const map: Record<string, string> = {
    '0 * * * *': 'Hourly',
    '0 */6 * * *': 'Every 6h',
    '0 2 * * *': 'Daily 2am',
    '0 0 * * *': 'Daily midnight',
    '0 2 * * 1': 'Weekly Mon',
  }
  return map[cron] || cron
}

describe('describeSchedule', () => {
  it('maps hourly cron', () => {
    expect(describeSchedule('0 * * * *')).toBe('Hourly')
  })

  it('maps every 6 hours', () => {
    expect(describeSchedule('0 */6 * * *')).toBe('Every 6h')
  })

  it('maps daily 2am', () => {
    expect(describeSchedule('0 2 * * *')).toBe('Daily 2am')
  })

  it('maps daily midnight', () => {
    expect(describeSchedule('0 0 * * *')).toBe('Daily midnight')
  })

  it('maps weekly Monday', () => {
    expect(describeSchedule('0 2 * * 1')).toBe('Weekly Mon')
  })

  it('returns raw cron for unknown expressions', () => {
    expect(describeSchedule('*/5 * * * *')).toBe('*/5 * * * *')
  })

  it('returns raw cron for empty string', () => {
    expect(describeSchedule('')).toBe('')
  })
})
