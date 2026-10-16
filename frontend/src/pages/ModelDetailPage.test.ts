import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ModelDetailPage from '@/pages/ModelDetailPage.vue'
import { useAuthStore } from '@/stores/auth'
import { useProjectsStore } from '@/stores/projects'
import { modelsApi } from '@/api/models'
import { authApi } from '@/api/auth'
import { projectsApi } from '@/api/projects'
import { createTestVuetify, makeProject, makeUser } from '@/test/helpers'
import type { Model } from '@/types'

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { modelId: 'm1' } }),
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('@/api/projects', () => ({ projectsApi: { list: vi.fn() } }))
vi.mock('@/api/auth', () => ({
  authApi: { listModelAccess: vi.fn(), listServiceAccounts: vi.fn(), grantModelAccess: vi.fn(), revokeModelAccess: vi.fn() },
}))
vi.mock('@/api/models', () => ({ modelsApi: { get: vi.fn(), update: vi.fn() } }))

const projects = [
  makeProject({ id: 'pa', name: 'team-a', my_role: 'editor' }),
  makeProject({ id: 'pb', name: 'team-b', my_role: 'viewer' }),
  makeProject({ id: 'pc', name: 'team-c', my_role: 'viewer' }),
]

const model: Model = {
  id: 'm1',
  name: 'churn',
  description: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  project_id: 'pa',
  project_name: 'team-a',
  versions: [],
}

let wrapper: VueWrapper | null = null

async function mountPage(globalRole: 'owner' | 'viewer', modelOverrides: Partial<Model> = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.authConfig = { enabled: true, local_enabled: true, google_oauth_enabled: false, allow_registration: false }
  auth.user = makeUser({ role: globalRole })
  vi.mocked(projectsApi.list).mockResolvedValue(projects)
  vi.mocked(modelsApi.get).mockResolvedValue({ ...model, ...modelOverrides })
  // The layout loads the projects before any page renders
  await useProjectsStore().ensureLoaded()
  wrapper = mount(ModelDetailPage, { global: { plugins: [pinia, createTestVuetify()] }, attachTo: document.body })
  await flushPromises()
}

const moveButton = () => wrapper!.findAll('button').find((b) => b.text().includes('Move to project'))
const bodyButton = (text: string) =>
  [...document.body.querySelectorAll('button')].find((b) => b.textContent?.trim() === text)

async function openMoveDialog() {
  await moveButton()!.trigger('click')
  await flushPromises()
}

beforeEach(() => {
  vi.mocked(modelsApi.update).mockReset()
  vi.mocked(authApi.listModelAccess).mockReset().mockResolvedValue([])
  vi.mocked(authApi.listServiceAccounts).mockReset().mockResolvedValue([])
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe('ModelDetailPage permissions', () => {
  it('offers the move action only to global owners', async () => {
    await mountPage('owner')
    expect(moveButton()).toBeDefined()
    wrapper!.unmount()

    await mountPage('viewer')
    expect(moveButton()).toBeUndefined()
  })

  it('hides write actions from a viewer of the model project', async () => {
    await mountPage('viewer', { project_id: 'pb', project_name: 'team-b' })
    expect(wrapper!.find('button .mdi-pencil').exists()).toBe(false)
    expect(wrapper!.text()).not.toContain('New Version')
  })

  it('shows write actions to an editor of the model project', async () => {
    await mountPage('viewer')
    expect(wrapper!.find('button .mdi-pencil').exists()).toBe(true)
  })
})

describe('ModelDetailPage move dialog', () => {
  it('excludes the current project from the targets', async () => {
    await mountPage('owner')
    await openMoveDialog()
    const select = wrapper!.findAllComponents({ name: 'VSelect' }).find((c) => c.attributes('data-testid') === 'move-target-project')!
    expect((select.props('items') as { value: string }[]).map((i) => i.value)).toEqual(['pb', 'pc'])
  })

  it('moves the model and updates the shown project', async () => {
    vi.mocked(modelsApi.update).mockResolvedValue({ ...model, project_id: 'pb', project_name: 'team-b' })
    await mountPage('owner')
    await openMoveDialog()
    const select = wrapper!.findAllComponents({ name: 'VSelect' }).find((c) => c.attributes('data-testid') === 'move-target-project')!
    select.vm.$emit('update:modelValue', 'pb')
    await flushPromises()
    bodyButton('Move')!.click()
    await flushPromises()

    expect(modelsApi.update).toHaveBeenCalledWith('m1', { project_id: 'pb' })
    expect(wrapper!.find('[data-testid="model-project"]').text()).toContain('team-b')
  })

  it.each([
    [403, 'Only global owners can move models'],
    [404, 'Project not found'],
    [409, 'A model with this name already exists in the target project'],
  ])('shows the backend message for a %i response', async (status, detail) => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.mocked(modelsApi.update).mockRejectedValue({ status, message: 'x', detail })
    await mountPage('owner')
    await openMoveDialog()
    const select = wrapper!.findAllComponents({ name: 'VSelect' }).find((c) => c.attributes('data-testid') === 'move-target-project')!
    select.vm.$emit('update:modelValue', 'pb')
    await flushPromises()
    bodyButton('Move')!.click()
    await flushPromises()

    expect(document.body.textContent).toContain(detail)
    expect(wrapper!.find('[data-testid="model-project"]').text()).toContain('team-a')
  })
})
