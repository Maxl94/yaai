import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { authApi } from '@/api/auth'
import { setAccessToken } from '@/api/client'
import type { AuthUser, AuthConfigResponse } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const authConfig = ref<AuthConfigResponse | null>(null)
  const initialized = ref(false)
  const loading = ref(false)

  const isAuthenticated = computed(() => !!user.value)
  const isOwner = computed(() => user.value?.role === 'owner')
  const authEnabled = computed(() => authConfig.value?.enabled ?? true)

  let _initPromise: Promise<void> | null = null

  async function initialize() {
    if (initialized.value) return
    if (_initPromise) return _initPromise
    _initPromise = _doInitialize()
    return _initPromise
  }

  async function _doInitialize() {
    // Tokens used to be kept in localStorage; do not leave old ones lying around
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')

    try {
      // Fetch auth config from backend
      authConfig.value = await authApi.getConfig()
    } catch {
      // If the endpoint doesn't exist (older backend), assume auth is disabled
      authConfig.value = {
        enabled: false,
        local_enabled: false,
        google_oauth_enabled: false,
        allow_registration: false,
      }
      initialized.value = true
      return
    }

    if (!authConfig.value.enabled) {
      initialized.value = true
      return
    }

    // The refresh cookie restores the session after a reload and completes the Google OAuth redirect
    await refreshSession()

    initialized.value = true
  }

  async function login(username: string, password: string) {
    loading.value = true
    try {
      const result = await authApi.login({ username, password })
      setAccessToken(result.access_token)
      user.value = result.user
    } finally {
      loading.value = false
    }
  }

  async function refreshSession() {
    try {
      const result = await authApi.refresh()
      setAccessToken(result.access_token)
      user.value = result.user
    } catch {
      clearSession()
    }
  }

  function clearSession() {
    user.value = null
    setAccessToken(null)
  }

  async function logout() {
    try {
      await authApi.logout()
    } catch {
      // Cookie could not be revoked server-side; the local session is dropped regardless
    } finally {
      clearSession()
    }
  }

  return {
    user,
    authConfig,
    initialized,
    loading,
    isAuthenticated,
    isOwner,
    authEnabled,
    initialize,
    login,
    logout,
    refreshSession,
    clearSession,
  }
})
