import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import JobsPage from '@/pages/JobsPage.vue'
import { useAuthStore } from '@/stores/auth'
import { jobsApi } from '@/api/jobs'
import { modelsApi } from '@/api/models'
import { projectsApi } from '@/api/projects'
import { createTestVuetify, makeProject, makeUser } from '@/test/helpers'
import type { JobConfig, Model } from '@/types'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: {} }) }))
vi.mock('@/api/auth', () => ({ authApi: {} }))
vi.mock('@/api/projects', () => ({ projectsApi: { list: vi.fn() } }))
vi.mock('@/api/models', () => ({ modelsApi: { list: vi.fn(), get: vi.fn(), getVersion: vi.fn() } }))
vi.mock('@/api/jobs', () => ({
  jobsApi: { list: vi.fn(), update: vi.fn(), trigger: vi.fn(), backfill: vi.fn(), getHistory: vi.fn() },
}))

const projects = [
  makeProject({ id: 'pa', name: 'team-a', my_role: 'editor' }),
  makeProject({ id: 'pb', name: 'team-b', my_role: 'viewer' }),
]

function makeJob(overrides: Partial<JobConfig>): JobConfig {
  return {
    id: 'j',
    model_version_id: 'v',
    name: 'job',
    schedule: '0 2 * * *',
    comparison_type: 'vs_reference',
    window_size: '7d',
    min_samples: 200,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

// Mirrors the real API: the list endpoint has no versions, only the model details do
const model = (id: string, projectId: string) =>
  ({ id, name: id, project_id: projectId }) as unknown as Model
const modelDetails = (id: string, projectId: string, versionId: string) =>
  ({ ...model(id, projectId), versions: [{ id: versionId }] }) as unknown as Model

let wrapper: VueWrapper | null = null

async function mountPage(globalRole: 'owner' | 'viewer') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.authConfig = { enabled: true, local_enabled: true, google_oauth_enabled: false, allow_registration: false }
  auth.user = makeUser({ role: globalRole })
  wrapper = mount(JobsPage, { global: { plugins: [pinia, createTestVuetify()] }, attachTo: document.body })
  await flushPromises()
}

const rowFor = (name: string) => wrapper!.findAll('tbody tr').find((r) => r.text().includes(name))!
const hasAction = (name: string, icon: string) => rowFor(name).find(`.${icon}`).exists()

beforeEach(() => {
  vi.mocked(projectsApi.list).mockReset().mockResolvedValue(projects)
  vi.mocked(jobsApi.list)
    .mockReset()
    .mockResolvedValue([
      makeJob({ id: 'ja', name: 'job-a', model_version_id: 'va' }),
      makeJob({ id: 'jb', name: 'job-b', model_version_id: 'vb' }),
      makeJob({ id: 'jc', name: 'job-unknown', model_version_id: 'vx' }),
    ])
  vi.mocked(modelsApi.list).mockReset().mockResolvedValue([model('ma', 'pa'), model('mb', 'pb')])
  vi.mocked(modelsApi.get)
    .mockReset()
    .mockImplementation(async (modelId: string) =>
      modelId === 'ma' ? modelDetails('ma', 'pa', 'va') : modelDetails('mb', 'pb', 'vb'),
    )
  vi.mocked(jobsApi.trigger).mockReset().mockResolvedValue({} as never)
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe('JobsPage per-job write gating on the global page', () => {
  it('shows actions only for jobs in projects where the user can write', async () => {
    await mountPage('viewer')
    expect(hasAction('job-a', 'mdi-play')).toBe(true)
    expect(hasAction('job-a', 'mdi-pencil')).toBe(true)
    expect(hasAction('job-b', 'mdi-play')).toBe(false)
    expect(hasAction('job-b', 'mdi-pencil')).toBe(false)
    expect(hasAction('job-b', 'mdi-history')).toBe(true)
  })

  it('keeps jobs with an unresolved project read-only', async () => {
    await mountPage('viewer')
    expect(hasAction('job-unknown', 'mdi-play')).toBe(false)
  })

  it('does not resolve versions of read-only projects', async () => {
    await mountPage('viewer')
    expect(modelsApi.get).toHaveBeenCalledTimes(1)
    expect(modelsApi.get).toHaveBeenCalledWith('ma')
  })

  it('keeps permissions of other models when one model lookup fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.mocked(modelsApi.list).mockResolvedValue([model('ma', 'pa'), model('mc', 'pa')])
    vi.mocked(modelsApi.get).mockImplementation(async (modelId: string) => {
      if (modelId === 'mc') throw new Error('boom')
      return modelDetails('ma', 'pa', 'va')
    })
    await mountPage('viewer')
    expect(hasAction('job-a', 'mdi-play')).toBe(true)
    expect(hasAction('job-b', 'mdi-play')).toBe(false)
  })

  it('shows every action to a global owner without resolving projects', async () => {
    await mountPage('owner')
    expect(modelsApi.list).not.toHaveBeenCalled()
    expect(hasAction('job-b', 'mdi-play')).toBe(true)
    expect(hasAction('job-unknown', 'mdi-pencil')).toBe(true)
  })
})

describe('JobsPage action errors', () => {
  it('surfaces a rejected action to the user', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.mocked(jobsApi.trigger).mockRejectedValue({ status: 403, message: 'x', detail: 'Editor access required' })
    await mountPage('viewer')
    await rowFor('job-a').find('.mdi-play').element.closest('button')!.click()
    await flushPromises()

    expect(document.body.querySelector('[data-testid="job-action-error"]')?.textContent).toContain('Editor access required')
  })
})
