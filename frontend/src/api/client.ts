import axios, { type AxiosError } from 'axios'
import type { ApiError, TokenResponse } from '@/types'

const client = axios.create({
  baseURL: '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
})

// The access token lives in memory only; the refresh token is an httpOnly cookie that JS cannot read
let accessToken: string | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

// Request interceptor: attach access token from memory
client.interceptors.request.use((config) => {
  if (accessToken && config.url && !config.url.startsWith('/auth/config') && !config.url.startsWith('/auth/login')) {
    config.headers.Authorization = `Bearer ${accessToken}`
  }
  return config
})

// Track whether we're currently refreshing to avoid multiple refresh calls
let isRefreshing = false
let failedQueue: Array<{
  resolve: (value: unknown) => void
  reject: (reason: unknown) => void
}> = []

function processQueue(error: unknown, token: string | null = null) {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error)
    } else {
      prom.resolve(token)
    }
  })
  failedQueue = []
}

// Response interceptor: handle errors and 401 token refresh
client.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<{ detail?: string }>) => {
    const originalRequest = error.config

    // If 401 and not already retrying, attempt token refresh
    if (
      error.response?.status === 401 &&
      originalRequest &&
      !originalRequest.url?.startsWith('/auth/login') &&
      !originalRequest.url?.startsWith('/auth/refresh') &&
      !(originalRequest as unknown as Record<string, unknown>)._retry
    ) {
      if (isRefreshing) {
        // Queue the request while refresh is in progress
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject })
        }).then((token) => {
          if (originalRequest.headers) {
            originalRequest.headers.Authorization = `Bearer ${token}`
          }
          return client(originalRequest)
        })
      }

      ;(originalRequest as unknown as Record<string, unknown>)._retry = true
      isRefreshing = true

      try {
        const response = await client.post<{ data: TokenResponse }>('/auth/refresh')
        const { access_token } = response.data.data
        setAccessToken(access_token)

        if (originalRequest.headers) {
          originalRequest.headers.Authorization = `Bearer ${access_token}`
        }

        processQueue(null, access_token)
        return client(originalRequest)
      } catch (refreshError) {
        processQueue(refreshError, null)
        // Refresh failed: drop the token (router guard will redirect to login)
        setAccessToken(null)
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    const apiError: ApiError = {
      status: error.response?.status ?? 500,
      message: error.message,
      detail: error.response?.data?.detail,
    }
    // A 401 from the startup refresh just means "not logged in"
    if (!(apiError.status === 401 && originalRequest?.url?.startsWith('/auth/refresh'))) {
      console.error('API Error:', apiError)
    }
    return Promise.reject(apiError)
  }
)

export default client
