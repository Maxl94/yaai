import axios, { type AxiosError } from 'axios'
import type { ApiError } from '@/types'

const client = axios.create({
  baseURL: '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor: attach Bearer token from localStorage
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token && config.url && !config.url.startsWith('/auth/config') && !config.url.startsWith('/auth/login')) {
    config.headers.Authorization = `Bearer ${token}`
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

      const refreshToken = localStorage.getItem('refresh_token')
      if (refreshToken) {
        try {
          const response = await client.post<{
            data: { access_token: string; refresh_token: string }
          }>('/auth/refresh', { refresh_token: refreshToken })

          const { access_token, refresh_token: new_refresh } = response.data.data
          localStorage.setItem('access_token', access_token)
          localStorage.setItem('refresh_token', new_refresh)

          if (originalRequest.headers) {
            originalRequest.headers.Authorization = `Bearer ${access_token}`
          }

          processQueue(null, access_token)
          return client(originalRequest)
        } catch (refreshError) {
          processQueue(refreshError, null)
          // Refresh failed: clear tokens (router guard will redirect to login)
          localStorage.removeItem('access_token')
          localStorage.removeItem('refresh_token')
          return Promise.reject(refreshError)
        } finally {
          isRefreshing = false
        }
      } else {
        // No refresh token: clear tokens (router guard will redirect to login)
        localStorage.removeItem('access_token')
      }
    }

    const apiError: ApiError = {
      status: error.response?.status ?? 500,
      message: error.message,
      detail: error.response?.data?.detail,
    }
    console.error('API Error:', apiError)
    return Promise.reject(apiError)
  }
)

export default client
