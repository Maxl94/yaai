import client from './client'
import type {
  AuthConfigResponse,
  TokenResponse,
  LoginRequest,
  AuthUser,
  ServiceAccount,
  ServiceAccountCreateResponse,
  ModelAccessEntry,
} from '@/types'

async function getConfig(): Promise<AuthConfigResponse> {
  const response = await client.get<{ data: AuthConfigResponse }>('/auth/config')
  return response.data.data
}

async function login(credentials: LoginRequest): Promise<TokenResponse> {
  const response = await client.post<{ data: TokenResponse }>('/auth/login', credentials)
  return response.data.data
}

async function refresh(): Promise<TokenResponse> {
  const response = await client.post<{ data: TokenResponse }>('/auth/refresh')
  return response.data.data
}

async function logout(): Promise<void> {
  await client.post('/auth/logout')
}

async function getMe(): Promise<AuthUser> {
  const response = await client.get<{ data: AuthUser }>('/auth/me')
  return response.data.data
}

async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await client.put('/auth/me/password', {
    current_password: currentPassword,
    new_password: newPassword,
  })
}

// Owner: Users
async function listUsers(): Promise<AuthUser[]> {
  const response = await client.get<{ data: AuthUser[] }>('/auth/users')
  return response.data.data
}

async function createUser(data: {
  username: string
  password: string
  email?: string
  role?: string
}): Promise<AuthUser> {
  const response = await client.post<{ data: AuthUser }>('/auth/users', data)
  return response.data.data
}

async function updateUser(
  userId: string,
  data: { email?: string; role?: string; is_active?: boolean }
): Promise<AuthUser> {
  const response = await client.put<{ data: AuthUser }>(`/auth/users/${userId}`, data)
  return response.data.data
}

async function deleteUser(userId: string): Promise<void> {
  await client.delete(`/auth/users/${userId}`)
}

// Owner: Service Accounts
async function listServiceAccounts(): Promise<ServiceAccount[]> {
  const response = await client.get<{ data: ServiceAccount[] }>('/auth/service-accounts')
  return response.data.data
}

async function createServiceAccount(data: {
  name: string
  description?: string
  auth_type?: string
  google_sa_email?: string
}): Promise<ServiceAccountCreateResponse> {
  const response = await client.post<{ data: ServiceAccountCreateResponse }>('/auth/service-accounts', data)
  return response.data.data
}

async function regenerateServiceAccountKey(saId: string): Promise<{ raw_key: string; key_prefix: string }> {
  const response = await client.post<{ data: { raw_key: string; key_prefix: string } }>(
    `/auth/service-accounts/${saId}/regenerate-key`
  )
  return response.data.data
}

async function deleteServiceAccount(saId: string): Promise<void> {
  await client.delete(`/auth/service-accounts/${saId}`)
}

// Owner: Model Access
async function listModelAccess(modelId: string): Promise<ModelAccessEntry[]> {
  const response = await client.get<{ data: ModelAccessEntry[] }>(`/auth/models/${modelId}/access`)
  return response.data.data
}

async function grantModelAccess(modelId: string, serviceAccountId: string): Promise<ModelAccessEntry> {
  const response = await client.post<{ data: ModelAccessEntry }>(`/auth/models/${modelId}/access`, {
    service_account_id: serviceAccountId,
  })
  return response.data.data
}

async function revokeModelAccess(modelId: string, saId: string): Promise<void> {
  await client.delete(`/auth/models/${modelId}/access/${saId}`)
}

export const authApi = {
  getConfig,
  login,
  refresh,
  logout,
  getMe,
  changePassword,
  listUsers,
  createUser,
  updateUser,
  deleteUser,
  listServiceAccounts,
  createServiceAccount,
  regenerateServiceAccountKey,
  deleteServiceAccount,
  listModelAccess,
  grantModelAccess,
  revokeModelAccess,
}
