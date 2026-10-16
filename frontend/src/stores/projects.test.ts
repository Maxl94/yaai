import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useProjectsStore, CURRENT_PROJECT_STORAGE_KEY } from '@/stores/projects'
import { projectsApi } from '@/api/projects'
import { makeProject, makeUser } from '@/test/helpers'

vi.mock('@/api/projects', () => ({ projectsApi: { list: vi.fn() } }))
vi.mock('@/api/auth', () => ({ authApi: {} }))

const listMock = vi.mocked(projectsApi.list)

const projects = [
  makeProject({ id: 'default', name: 'default', is_default: true, my_role: 'viewer' }),
  makeProject({ id: 'edit', name: 'edit-me', my_role: 'editor' }),
  makeProject({ id: 'own', name: 'own-me', my_role: 'owner' }),
]

function setup(role: 'owner' | 'viewer' | null, authEnabled = true) {
  const auth = useAuthStore()
  auth.authConfig = {
    enabled: authEnabled,
    local_enabled: true,
    google_oauth_enabled: false,
    allow_registration: false,
  }
  auth.user = role ? makeUser({ role }) : null
  return { auth, store: useProjectsStore() }
}

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  listMock.mockReset()
  listMock.mockResolvedValue(projects)
})

describe('role logic for a global viewer', () => {
  it('allows writes only for editor and owner roles', async () => {
    const { store } = setup('viewer')
    await store.load()
    expect(store.canWrite('default')).toBe(false)
    expect(store.canWrite('edit')).toBe(true)
    expect(store.canWrite('own')).toBe(true)
    expect(store.canWrite('unknown')).toBe(false)
    expect(store.canWrite(null)).toBe(false)
  })

  it('allows administration only for project owners', async () => {
    const { store } = setup('viewer')
    await store.load()
    expect(store.canAdmin('own')).toBe(true)
    expect(store.canAdmin('edit')).toBe(false)
    expect(store.canAdmin('default')).toBe(false)
  })

  it('can create models only when a writable project exists', async () => {
    const { store } = setup('viewer')
    listMock.mockResolvedValue([projects[0]!])
    await store.load()
    expect(store.canCreateModel).toBe(false)

    listMock.mockResolvedValue(projects)
    await store.load()
    expect(store.canCreateModel).toBe(true)
    expect(store.writableProjects.map((p) => p.id)).toEqual(['edit', 'own'])
  })
})

describe('role logic for super-admins', () => {
  it('grants everything to global owners', () => {
    const { store } = setup('owner')
    expect(store.canWrite('anything')).toBe(true)
    expect(store.canAdmin('anything')).toBe(true)
    expect(store.canCreateModel).toBe(true)
  })

  it('grants everything when auth is disabled', () => {
    const { store } = setup(null, false)
    expect(store.canWrite('anything')).toBe(true)
    expect(store.canAdmin('anything')).toBe(true)
    expect(store.canCreateModel).toBe(true)
  })
})

describe('current project selection', () => {
  it('persists the selection in localStorage and clears it for "All projects"', () => {
    const { store } = setup('viewer')
    store.setCurrentProject('edit')
    expect(localStorage.getItem(CURRENT_PROJECT_STORAGE_KEY)).toBe('edit')
    store.setCurrentProject(null)
    expect(localStorage.getItem(CURRENT_PROJECT_STORAGE_KEY)).toBeNull()
  })

  it('restores a stored selection that is still accessible', async () => {
    localStorage.setItem(CURRENT_PROJECT_STORAGE_KEY, 'edit')
    const { store } = setup('viewer')
    await store.load()
    expect(store.currentProjectId).toBe('edit')
    expect(store.currentProject?.name).toBe('edit-me')
  })

  it('ignores a stale stored id that is not in the project list', async () => {
    localStorage.setItem(CURRENT_PROJECT_STORAGE_KEY, 'deleted-project')
    const { store } = setup('viewer')
    await store.load()
    expect(store.currentProjectId).toBeNull()
    expect(localStorage.getItem(CURRENT_PROJECT_STORAGE_KEY)).toBeNull()
  })
})

describe('loading', () => {
  it('shares one request between concurrent ensureLoaded calls', async () => {
    const { store } = setup('viewer')
    await Promise.all([store.ensureLoaded(), store.ensureLoaded()])
    await store.ensureLoaded()
    expect(listMock).toHaveBeenCalledTimes(1)
  })

  it('stays unloaded when the request fails so it can be retried', async () => {
    const { store } = setup('viewer')
    vi.spyOn(console, 'error').mockImplementation(() => {})
    listMock.mockRejectedValueOnce(new Error('boom'))
    await store.ensureLoaded()
    expect(store.loaded).toBe(false)
    await store.ensureLoaded()
    expect(store.loaded).toBe(true)
  })

  it('resets projects and selection on logout', async () => {
    const { auth, store } = setup('viewer')
    await store.load()
    store.setCurrentProject('edit')
    auth.user = null
    await nextTick()
    expect(store.projects).toEqual([])
    expect(store.currentProjectId).toBeNull()
    expect(store.loaded).toBe(false)
  })
})
