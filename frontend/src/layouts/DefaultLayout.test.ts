import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import { useAuthStore } from '@/stores/auth'
import { projectsApi } from '@/api/projects'
import { notificationsApi } from '@/api/notifications'
import { createTestVuetify, makeUser } from '@/test/helpers'

vi.mock('vue-router', () => ({
  useRoute: () => ({ path: '/models', params: {}, query: {} }),
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('@/api/auth', () => ({ authApi: {} }))
vi.mock('@/api/projects', () => ({ projectsApi: { list: vi.fn() } }))
vi.mock('@/api/notifications', () => ({ notificationsApi: { getUnreadCount: vi.fn() } }))

let wrapper: VueWrapper | null = null

async function mountLayout(setup: (auth: ReturnType<typeof useAuthStore>) => void) {
  const pinia = createPinia()
  setActivePinia(pinia)
  setup(useAuthStore())
  wrapper = mount(DefaultLayout, {
    global: { plugins: [pinia, createTestVuetify()], stubs: { 'router-link': true, 'router-view': true } },
    attachTo: document.body,
  })
  await flushPromises()
}

const authConfig = (enabled: boolean) => ({
  enabled,
  local_enabled: enabled,
  google_oauth_enabled: false,
  allow_registration: false,
})

beforeEach(() => {
  vi.mocked(projectsApi.list).mockReset().mockResolvedValue([])
  vi.mocked(notificationsApi.getUnreadCount).mockReset().mockResolvedValue(0)
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe('DefaultLayout data loading', () => {
  it('does not request projects or notifications before login', async () => {
    await mountLayout((auth) => {
      auth.authConfig = authConfig(true)
    })
    expect(projectsApi.list).not.toHaveBeenCalled()
    expect(notificationsApi.getUnreadCount).not.toHaveBeenCalled()
  })

  it('loads projects for an authenticated user', async () => {
    await mountLayout((auth) => {
      auth.authConfig = authConfig(true)
      auth.user = makeUser()
    })
    expect(projectsApi.list).toHaveBeenCalledTimes(1)
  })

  it('loads projects when auth is disabled', async () => {
    await mountLayout((auth) => {
      auth.authConfig = authConfig(false)
    })
    expect(projectsApi.list).toHaveBeenCalledTimes(1)
  })
})
