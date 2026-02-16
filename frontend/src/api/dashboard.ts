import client from './client'
import type { DashboardResponse, ComparisonPanel, ApiResponse } from '@/types'

async function getDashboard(
  modelId: string,
  versionId: string,
  params?: { from?: string; to?: string; direction?: string }
): Promise<DashboardResponse> {
  const response = await client.get<ApiResponse<DashboardResponse>>(
    `/models/${modelId}/versions/${versionId}/dashboard`,
    { params }
  )
  return response.data.data
}

async function getComparison(
  modelId: string,
  versionId: string,
  params: {
    mode: 'time_window' | 'vs_reference'
    from_a: string
    to_a: string
    from_b?: string
    to_b?: string
  }
): Promise<{ panels: ComparisonPanel[] }> {
  const response = await client.get<ApiResponse<{ panels: ComparisonPanel[] }>>(
    `/models/${modelId}/versions/${versionId}/dashboard/compare`,
    { params }
  )
  return response.data.data
}

export const dashboardApi = {
  getDashboard,
  getComparison,
}
