import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import client, { setAccessToken } from '@/api/client'

type Handler = (config: InternalAxiosRequestConfig) => { status: number; data?: unknown }

const originalAdapter = client.defaults.adapter
const calls: Array<{ url?: string; authorization: unknown }> = []

function useServer(handler: Handler) {
  client.defaults.adapter = async (config) => {
    calls.push({ url: config.url, authorization: config.headers.Authorization })
    const { status, data } = handler(config)
    const response = { data, status, statusText: '', headers: {}, config }
    if (status >= 400) throw new AxiosError('failed', String(status), config, null, response)
    return response
  }
}

beforeEach(() => {
  calls.length = 0
  setAccessToken(null)
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  client.defaults.adapter = originalAdapter
  vi.restoreAllMocks()
})

describe('401 interceptor', () => {
  it('refreshes once and retries the request with the new access token', async () => {
    setAccessToken('expired')
    useServer((config) => {
      if (config.url === '/auth/refresh') return { status: 200, data: { data: { access_token: 'fresh' } } }
      return config.headers.Authorization === 'Bearer fresh' ? { status: 200, data: { ok: true } } : { status: 401 }
    })

    const response = await client.get('/models')

    expect(response.data).toEqual({ ok: true })
    expect(calls.map((c) => c.url)).toEqual(['/models', '/auth/refresh', '/models'])
    expect(calls[2]?.authorization).toBe('Bearer fresh')
  })

  it('does not loop when the refresh itself returns 401 and ends logged out', async () => {
    setAccessToken('expired')
    useServer(() => ({ status: 401 }))

    await expect(client.get('/models')).rejects.toMatchObject({ status: 401 })

    expect(calls.filter((c) => c.url === '/auth/refresh')).toHaveLength(1)
    expect(console.error).not.toHaveBeenCalled()
    calls.length = 0
    await client.get('/other').catch(() => {})
    expect(calls[0]?.authorization).toBeUndefined()
  })
})
