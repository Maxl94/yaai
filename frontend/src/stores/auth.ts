import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { authApi } from '@/api/auth'
import type { AuthUser, AuthConfigResponse } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const accessToken = ref<string | null>(null)
  const refreshToken = ref<string | null>(null)
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

    // Check for OAuth callback auth code in URL
    const params = new URLSearchParams(window.location.search)
    const authCode = params.get('auth_code')
    if (authCode) {
      // Clean URL immediately to prevent code reuse/leakage
      window.history.replaceState({}, '', window.location.pathname)
      try {
        const tokens = await authApi.exchangeAuthCode(authCode)
        setTokens(tokens.access_token, tokens.refresh_token)
      } catch {
        // Auth code expired or invalid — user will need to re-authenticate
        console.warn('OAuth auth code exchange failed')
      }
    }

    // Try to restore session from localStorage
    const storedAccess = accessToken.value || localStorage.getItem('access_token')
    const storedRefresh = refreshToken.value || localStorage.getItem('refresh_token')

    if (storedAccess) {
      accessToken.value = storedAccess
      refreshToken.value = storedRefresh
      try {
        user.value = await authApi.getMe()
      } catch {
        // Token expired/invalid, try refresh
        if (storedRefresh) {
          await refreshSession()
        } else {
          clearSession()
        }
      }
    }

    initialized.value = true
  }

  async function login(username: string, password: string) {
    loading.value = true
    try {
      const result = await authApi.login({ username, password })
      setTokens(result.access_token, result.refresh_token)
      user.value = result.user
    } finally {
      loading.value = false
    }
  }

  async function refreshSession() {
    if (!refreshToken.value) {
      clearSession()
      return
    }
    try {
      const result = await authApi.refresh(refreshToken.value)
      setTokens(result.access_token, result.refresh_token)
      user.value = result.user
    } catch {
      clearSession()
    }
  }

  function setTokens(access: string, refresh: string) {
    accessToken.value = access
    refreshToken.value = refresh
    localStorage.setItem('access_token', access)
    localStorage.setItem('refresh_token', refresh)
  }

  function clearSession() {
    user.value = null
    accessToken.value = null
    refreshToken.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }

  function logout() {
    clearSession()
  }

  return {
    user,
    accessToken,
    refreshToken,
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
