import { describe, it, expect } from 'vitest'
import type { Model, ModelVersionSummary } from '@/types'

// Pure functions extracted from ModelsPage.vue for testing.

function getActiveVersion(model: Model): string | null {
  if (model.active_version) {
    return model.active_version.version
  }
  return model.versions?.find((v) => v.is_active)?.version || null
}

function getInferenceCount(model: Model): string {
  const count = model.total_inferences ?? 0
  if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`
  if (count >= 1000) return `${(count / 1000).toFixed(1)}K`
  return count.toString()
}

function makeVersion(overrides: Partial<ModelVersionSummary> = {}): ModelVersionSummary {
  return {
    id: 'v1',
    version: 'v1.0',
    is_active: false,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function makeModel(overrides: Partial<Model> = {}): Model {
  return {
    id: 'm1',
    name: 'Test Model',
    description: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('getActiveVersion', () => {
  it('returns version from active_version shortcut', () => {
    const model = makeModel({
      active_version: makeVersion({ version: 'v2.0', is_active: true }),
    })
    expect(getActiveVersion(model)).toBe('v2.0')
  })

  it('falls back to versions array when active_version is null', () => {
    const model = makeModel({
      active_version: null,
      versions: [
        makeVersion({ version: 'v1.0', is_active: false }),
        makeVersion({ version: 'v2.0', is_active: true }),
      ],
    })
    expect(getActiveVersion(model)).toBe('v2.0')
  })

  it('returns null when no version is active', () => {
    const model = makeModel({
      active_version: null,
      versions: [makeVersion({ is_active: false })],
    })
    expect(getActiveVersion(model)).toBeNull()
  })

  it('returns null when versions is undefined', () => {
    const model = makeModel({ active_version: null })
    expect(getActiveVersion(model)).toBeNull()
  })

  it('returns null when versions is empty', () => {
    const model = makeModel({ active_version: null, versions: [] })
    expect(getActiveVersion(model)).toBeNull()
  })
})

describe('getInferenceCount', () => {
  it('formats millions', () => {
    expect(getInferenceCount(makeModel({ total_inferences: 1500000 }))).toBe('1.5M')
  })

  it('formats exact million', () => {
    expect(getInferenceCount(makeModel({ total_inferences: 1000000 }))).toBe('1.0M')
  })

  it('formats thousands', () => {
    expect(getInferenceCount(makeModel({ total_inferences: 5000 }))).toBe('5.0K')
  })

  it('formats exact thousand', () => {
    expect(getInferenceCount(makeModel({ total_inferences: 1000 }))).toBe('1.0K')
  })

  it('returns raw number below 1000', () => {
    expect(getInferenceCount(makeModel({ total_inferences: 42 }))).toBe('42')
  })

  it('returns 0 when total_inferences is undefined', () => {
    expect(getInferenceCount(makeModel())).toBe('0')
  })

  it('returns 0 for zero inferences', () => {
    expect(getInferenceCount(makeModel({ total_inferences: 0 }))).toBe('0')
  })
})
