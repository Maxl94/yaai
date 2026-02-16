import client from './client'
import type { JobConfig, DriftOverviewItem, ApiResponse, PaginatedResponse } from '@/types'

interface JobHistoryItem {
  id: string
  status: string
  drifts_detected: number
  run_at: string
}

interface UpdateJobData {
  name?: string
  schedule?: string
  comparison_type?: 'vs_reference' | 'rolling_window'
  window_size?: string | null
  min_samples?: number
  is_active?: boolean
}

async function list(): Promise<JobConfig[]> {
  const response = await client.get<PaginatedResponse<JobConfig>>('/jobs')
  return response.data.data
}

async function listForVersion(modelId: string, versionId: string): Promise<JobConfig[]> {
  const response = await client.get<{ data: JobConfig[] }>(
    `/models/${modelId}/versions/${versionId}/jobs`
  )
  return response.data.data
}

async function get(jobId: string): Promise<JobConfig> {
  const response = await client.get<ApiResponse<JobConfig>>(`/jobs/${jobId}`)
  return response.data.data
}

async function update(jobId: string, data: UpdateJobData): Promise<JobConfig> {
  const response = await client.patch<ApiResponse<JobConfig>>(`/jobs/${jobId}`, data)
  return response.data.data
}

async function trigger(jobId: string): Promise<void> {
  await client.post(`/jobs/${jobId}/trigger`)
}

async function getHistory(jobId: string): Promise<JobHistoryItem[]> {
  const response = await client.get<PaginatedResponse<JobHistoryItem>>(`/jobs/${jobId}/runs`)
  return response.data.data
}

async function triggerAllForVersion(modelId: string, versionId: string): Promise<number> {
  const jobs = await listForVersion(modelId, versionId)
  const activeJobs = jobs.filter(j => j.is_active)
  await Promise.all(activeJobs.map(j => trigger(j.id)))
  return activeJobs.length
}

async function backfill(jobId: string): Promise<{ runs_created: number }> {
  const response = await client.post<ApiResponse<{ runs_created: number }>>(`/jobs/${jobId}/backfill`)
  return response.data.data
}

async function getDriftOverview(page: number = 1, pageSize: number = 10): Promise<PaginatedResponse<DriftOverviewItem>> {
  const response = await client.get<PaginatedResponse<DriftOverviewItem>>('/drift-overview', {
    params: { page, page_size: pageSize },
  })
  return response.data
}

export const jobsApi = {
  list,
  listForVersion,
  get,
  update,
  trigger,
  triggerAllForVersion,
  getHistory,
  backfill,
  getDriftOverview,
}
