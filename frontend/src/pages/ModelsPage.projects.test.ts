import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ModelsPage from '@/pages/ModelsPage.vue'
import { useAuthStore } from '@/stores/auth'
import { useProjectsStore } from '@/stores/projects'
import { modelsApi } from '@/api/models'
import { projectsApi } from '@/api/projects'
import { createTestVuetify, makeProject, makeUser } from '@/test/helpers'
import type { Model } from '@/types'

const push = vi.fn()
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))
vi.mock('@/api/auth', () => ({ authApi: {} }))
vi.mock('@/api/projects', () => ({ projectsApi: { list: vi.fn() } }))
vi.mock('@/api/models', () => ({
  modelsApi: { list: vi.fn(), create: vi.fn(), delete: vi.fn(), getDriftResults: vi.fn() },
}))

const projects = [
  makeProject({ id: 'default', name: 'default', is_default: true, my_role: 'viewer' }),
  makeProject({ id: 'team-a', name: 'team-a', my_role: 'editor' }),
]

function makeModel(overrides: Partial<Model> = {}): Model {
  return {
    id: 'm1',
    name: 'churn',
    description: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    project_id: 'team-a',
    project_name: 'team-a',
    ...overrides,
  }
}

let wrapper: VueWrapper | null = null

async function mountPage(globalRole: 'owner' | 'viewer', projectList = projects) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.authConfig = { enabled: true, local_enabled: true, google_oauth_enabled: false, allow_registration: false }
  auth.user = makeUser({ role: globalRole })
  vi.mocked(projectsApi.list).mockResolvedValue(projectList)
  wrapper = mount(ModelsPage, { global: { plugins: [pinia, createTestVuetify()] }, attachTo: document.body })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  localStorage.clear()
  push.mockReset()
  vi.mocked(modelsApi.list).mockReset().mockResolvedValue([makeModel()])
  vi.mocked(modelsApi.getDriftResults).mockReset().mockResolvedValue([])
  vi.mocked(modelsApi.create).mockReset().mockResolvedValue(makeModel({ id: 'new' }))
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

describe('ModelsPage project filtering', () => {
  it('lists all accessible models without a project filter by default', async () => {
    await mountPage('viewer')
    expect(modelsApi.list).toHaveBeenCalledWith({})
  })

  it('passes the stored current project to the API', async () => {
    localStorage.setItem('yaai.currentProjectId', 'team-a')
    await mountPage('viewer')
    expect(modelsApi.list).toHaveBeenCalledWith({ project_id: 'team-a' })
  })

  it('reloads models when the project switcher changes', async () => {
    await mountPage('viewer')
    useProjectsStore().setCurrentProject('team-a')
    await flushPromises()
    expect(modelsApi.list).toHaveBeenLastCalledWith({ project_id: 'team-a' })
  })

  it('shows the project chip only for the "All projects" view', async () => {
    await mountPage('viewer')
    expect(wrapper!.find('.project-chip').exists()).toBe(true)

    useProjectsStore().setCurrentProject('team-a')
    await flushPromises()
    expect(wrapper!.find('.project-chip').exists()).toBe(false)
  })
})

describe('ModelsPage permissions', () => {
  it('hides New Model for a viewer without any writable project', async () => {
    await mountPage('viewer', [projects[0]!])
    expect(wrapper!.text()).not.toContain('New Model')
  })

  it('shows New Model for an editor of a project', async () => {
    await mountPage('viewer')
    expect(wrapper!.text()).toContain('New Model')
  })

  it('shows New Model for a global owner even without projects', async () => {
    await mountPage('owner', [])
    expect(wrapper!.text()).toContain('New Model')
  })
})

describe('ModelsPage create dialog', () => {
  it('only offers writable projects and sends the selected project_id', async () => {
    await mountPage('viewer')
    const newModelButton = wrapper!.findAll('button').find((b) => b.text().includes('New Model'))!
    await newModelButton.trigger('click')
    await flushPromises()

    const projectSelect = wrapper!.findAllComponents({ name: 'VSelect' }).find(
      (c) => c.attributes('data-testid') === 'create-model-project',
    )!
    const items = projectSelect.props('items') as { title: string; value: string }[]
    expect(items).toEqual([{ title: 'team-a', value: 'team-a' }])
    expect(projectSelect.props('modelValue')).toBe('team-a')

    const nameInput = document.body.querySelector<HTMLInputElement>('input[placeholder="e.g., fraud-detection-v2"]')!
    nameInput.value = 'fraud'
    nameInput.dispatchEvent(new Event('input'))
    await flushPromises()
    const createButton = [...document.body.querySelectorAll('button')].find((b) => b.textContent?.includes('Create Model'))!
    createButton.click()
    await flushPromises()

    expect(modelsApi.create).toHaveBeenCalledWith({ name: 'fraud', description: undefined, project_id: 'team-a' })
    expect(push).toHaveBeenCalledWith('/models/new')
  })

  it('shows the API error when creation is rejected', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.mocked(modelsApi.create).mockRejectedValue({ status: 409, message: 'conflict', detail: 'Name already exists' })
    await mountPage('owner')
    const newModelButton = wrapper!.findAll('button').find((b) => b.text().includes('New Model'))!
    await newModelButton.trigger('click')
    await flushPromises()

    const nameInput = document.body.querySelector<HTMLInputElement>('input[placeholder="e.g., fraud-detection-v2"]')!
    nameInput.value = 'dup'
    nameInput.dispatchEvent(new Event('input'))
    await flushPromises()
    const createButton = [...document.body.querySelectorAll('button')].find((b) => b.textContent?.includes('Create Model'))!
    createButton.click()
    await flushPromises()

    expect(document.body.textContent).toContain('Name already exists')
    expect(push).not.toHaveBeenCalled()
  })
})

describe('ModelsPage project filter', () => {
  const filter = () =>
    wrapper!.findAllComponents({ name: 'VSelect' }).find((c) => c.attributes('data-testid') === 'project-switcher')

  it('offers "All projects" plus every accessible project and updates the store', async () => {
    await mountPage('viewer')
    const items = filter()!.props('items') as { title: string; value: string }[]
    expect(items.map((i) => i.title)).toEqual(['All projects', 'default', 'team-a'])

    filter()!.vm.$emit('update:modelValue', 'team-a')
    await flushPromises()
    expect(useProjectsStore().currentProjectId).toBe('team-a')
    expect(localStorage.getItem('yaai.currentProjectId')).toBe('team-a')

    filter()!.vm.$emit('update:modelValue', '__all__')
    await flushPromises()
    expect(useProjectsStore().currentProjectId).toBeNull()
  })

  it('is hidden when only one project is accessible', async () => {
    await mountPage('viewer', [projects[0]!])
    expect(filter()).toBeUndefined()
  })

  it('does not filter by a stored project that is not accessible', async () => {
    localStorage.setItem('yaai.currentProjectId', 'gone')
    await mountPage('viewer')
    expect(modelsApi.list).toHaveBeenCalledTimes(1)
    expect(modelsApi.list).toHaveBeenCalledWith({})
  })

  it('ignores an outdated model list when the filter changes quickly', async () => {
    await mountPage('viewer')
    let resolveSlow!: (models: Model[]) => void
    vi.mocked(modelsApi.list)
      .mockReturnValueOnce(new Promise((resolve) => (resolveSlow = resolve)))
      .mockResolvedValueOnce([makeModel({ id: 'm2', name: 'fresh-model' })])

    useProjectsStore().setCurrentProject('team-a')
    await flushPromises()
    useProjectsStore().setCurrentProject('default')
    await flushPromises()
    resolveSlow([makeModel({ id: 'm3', name: 'stale-model' })])
    await flushPromises()

    expect(wrapper!.text()).toContain('fresh-model')
    expect(wrapper!.text()).not.toContain('stale-model')
  })
})

describe('ModelsPage without project access', () => {
  it('tells users without any membership to ask for access', async () => {
    vi.mocked(modelsApi.list).mockResolvedValue([])
    await mountPage('viewer', [])
    expect(wrapper!.find('[data-testid="no-projects"]').text()).toContain('You are not a member of any project yet')
    expect(wrapper!.text()).not.toContain('No models yet')
  })

  it('shows the generic empty state to a global owner without models', async () => {
    vi.mocked(modelsApi.list).mockResolvedValue([])
    await mountPage('owner', [])
    expect(wrapper!.find('[data-testid="no-projects"]').exists()).toBe(false)
    expect(wrapper!.text()).toContain('No models yet')
  })

  it('shows a retryable error when the project list cannot be loaded', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.authConfig = { enabled: true, local_enabled: true, google_oauth_enabled: false, allow_registration: false }
    auth.user = makeUser({ role: 'viewer' })
    vi.mocked(projectsApi.list).mockRejectedValueOnce({ status: 503, message: 'x', detail: 'Service unavailable' })
    wrapper = mount(ModelsPage, { global: { plugins: [pinia, createTestVuetify()] }, attachTo: document.body })
    await flushPromises()

    const alert = wrapper.find('[data-testid="projects-load-error"]')
    expect(alert.text()).toContain('Service unavailable')

    vi.mocked(projectsApi.list).mockResolvedValueOnce(projects)
    await alert.find('button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="projects-load-error"]').exists()).toBe(false)
  })
})
