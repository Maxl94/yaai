import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import JobsPage from '@/pages/JobsPage.vue'
import { useAuthStore } from '@/stores/auth'
import { useProjectsStore } from '@/stores/projects'
import { jobsApi } from '@/api/jobs'
import { projectsApi } from '@/api/projects'
import { createTestVuetify, makeProject, makeUser } from '@/test/helpers'
import type { JobConfig } from '@/types'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: {} }) }))
vi.mock('@/api/auth', () => ({ authApi: {} }))
vi.mock('@/api/projects', () => ({ projectsApi: { list: vi.fn() } }))
vi.mock('@/api/models', () => ({ modelsApi: {} }))
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
    model_id: 'm',
    project_id: 'pa',
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

let wrapper: VueWrapper | null = null

async function mountPage(globalRole: 'owner' | 'viewer', { preloadProjects = true } = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.authConfig = { enabled: true, local_enabled: true, google_oauth_enabled: false, allow_registration: false }
  auth.user = makeUser({ role: globalRole })
  if (preloadProjects) await useProjectsStore().ensureLoaded()
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
      makeJob({ id: 'ja', name: 'job-a', project_id: 'pa' }),
      makeJob({ id: 'jb', name: 'job-b', project_id: 'pb' }),
      makeJob({ id: 'jc', name: 'job-other', project_id: 'px' }),
    ])
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
    expect(hasAction('job-other', 'mdi-play')).toBe(false)
    expect(hasAction('job-other', 'mdi-pencil')).toBe(false)
  })

  it('shows actions once the projects store finishes loading after mount', async () => {
    await mountPage('viewer', { preloadProjects: false })
    expect(hasAction('job-a', 'mdi-pencil')).toBe(false)
    await useProjectsStore().ensureLoaded()
    await flushPromises()
    expect(hasAction('job-a', 'mdi-pencil')).toBe(true)
    expect(hasAction('job-b', 'mdi-pencil')).toBe(false)
  })

  it('shows every action to a global owner', async () => {
    await mountPage('owner')
    expect(hasAction('job-b', 'mdi-play')).toBe(true)
    expect(hasAction('job-other', 'mdi-pencil')).toBe(true)
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
