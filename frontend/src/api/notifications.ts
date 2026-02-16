import client from './client'
import type { Notification, ApiResponse, PaginatedResponse } from '@/types'

async function list(params?: {
  model_version_id?: string
  is_read?: boolean
  severity?: string
  page?: number
  per_page?: number
}): Promise<Notification[]> {
  const response = await client.get<PaginatedResponse<Notification>>('/notifications', { params })
  return response.data.data
}

async function getUnreadCount(): Promise<number> {
  const response = await client.get<PaginatedResponse<Notification>>('/notifications', {
    params: { is_read: false, per_page: 1 },
  })
  return response.data.meta.total
}

async function markAsRead(notificationId: string): Promise<Notification> {
  const response = await client.patch<ApiResponse<Notification>>(`/notifications/${notificationId}`, {
    is_read: true,
  })
  return response.data.data
}

async function markAllAsRead(modelVersionId?: string): Promise<void> {
  await client.post('/notifications/mark-all-read', null, {
    params: modelVersionId ? { model_version_id: modelVersionId } : undefined,
  })
}

async function remove(notificationId: string): Promise<void> {
  await client.delete(`/notifications/${notificationId}`)
}

export const notificationsApi = {
  list,
  getUnreadCount,
  markAsRead,
  markAllAsRead,
  delete: remove,
}
