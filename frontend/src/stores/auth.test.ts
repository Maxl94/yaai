import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api/auth'
import client, { setAccessToken } from '@/api/client'
import { makeUser } from '@/test/helpers'

vi.mock('@/api/auth', () => ({
  authApi: { getConfig: vi.fn(), login: vi.fn(), refresh: vi.fn(), logout: vi.fn() },
}))

const api = vi.mocked(authApi)
const enabledConfig = { enabled: true, local_enabled: true, google_oauth_enabled: true, allow_registration: false }

async function sentAuthorization(): Promise<unknown> {
  let header: unknown
  await client.get('/probe', {
    adapter: async (config) => {
      header = config.headers.Authorization
      return { data: {}, status: 200, statusText: 'OK', headers: {}, config }
    },
  })
  return header
}

beforeEach(() => {
  localStorage.clear()
  setAccessToken(null)
  setActivePinia(createPinia())
  Object.values(api).forEach((fn) => fn.mockReset())
  api.getConfig.mockResolvedValue(enabledConfig)
})

describe('session restore', () => {
  it('restores the session via the refresh cookie when no token is in memory', async () => {
    const user = makeUser({ role: 'owner' })
    api.refresh.mockResolvedValue({ access_token: 'new-access', token_type: 'bearer', user })
    const auth = useAuthStore()

    await auth.initialize()

    expect(api.refresh).toHaveBeenCalledTimes(1)
    expect(auth.isAuthenticated).toBe(true)
    expect(await sentAuthorization()).toBe('Bearer new-access')
  })

  it('stays logged out when the refresh cookie is missing or invalid', async () => {
    api.refresh.mockRejectedValue({ status: 401 })
    const auth = useAuthStore()

    await auth.initialize()

    expect(auth.isAuthenticated).toBe(false)
    expect(auth.initialized).toBe(true)
    expect(await sentAuthorization()).toBeUndefined()
  })

  it('does not try to refresh when auth is disabled', async () => {
    api.getConfig.mockResolvedValue({ ...enabledConfig, enabled: false })
    const auth = useAuthStore()

    await auth.initialize()

    expect(api.refresh).not.toHaveBeenCalled()
  })
})

describe('token storage', () => {
  it('never writes tokens to localStorage on login', async () => {
    api.login.mockResolvedValue({ access_token: 'login-access', token_type: 'bearer', user: makeUser() })
    const auth = useAuthStore()

    await auth.login('admin', 'secret')

    expect(localStorage.length).toBe(0)
    expect(await sentAuthorization()).toBe('Bearer login-access')
  })

  it('removes legacy localStorage tokens on init', async () => {
    localStorage.setItem('access_token', 'old')
    localStorage.setItem('refresh_token', 'old')
    api.refresh.mockRejectedValue({ status: 401 })

    await useAuthStore().initialize()

    expect(localStorage.getItem('access_token')).toBeNull()
    expect(localStorage.getItem('refresh_token')).toBeNull()
  })

  it('logout revokes the cookie server-side and drops the in-memory token', async () => {
    api.login.mockResolvedValue({ access_token: 'login-access', token_type: 'bearer', user: makeUser() })
    api.logout.mockResolvedValue()
    const auth = useAuthStore()
    await auth.login('admin', 'secret')

    await auth.logout()

    expect(api.logout).toHaveBeenCalledTimes(1)
    expect(auth.isAuthenticated).toBe(false)
    expect(await sentAuthorization()).toBeUndefined()
  })

  it('logout still clears the local session when the request fails', async () => {
    api.login.mockResolvedValue({ access_token: 'login-access', token_type: 'bearer', user: makeUser() })
    api.logout.mockRejectedValue({ status: 500 })
    const auth = useAuthStore()
    await auth.login('admin', 'secret')

    await auth.logout()

    expect(auth.isAuthenticated).toBe(false)
  })
})
