import client from './client'
import type { Inference, ApiResponse, PaginatedResponse } from '@/types'

async function list(
  modelVersionId: string,
  params?: { from?: string; to?: string; page?: number; per_page?: number }
): Promise<Inference[]> {
  const response = await client.get<PaginatedResponse<Inference>>('/inferences', {
    params: { model_version_id: modelVersionId, ...params },
  })
  return response.data.data
}

async function create(data: {
  model_version_id: string
  inputs: Record<string, unknown>
  outputs: Record<string, unknown>
  timestamp?: string
}): Promise<Inference> {
  const response = await client.post<ApiResponse<Inference>>('/inferences', data)
  return response.data.data
}

async function createBatch(data: {
  model_version_id: string
  records: Array<{
    inputs: Record<string, unknown>
    outputs: Record<string, unknown>
    timestamp?: string
  }>
}): Promise<{ created: number }> {
  const response = await client.post<ApiResponse<{ created: number }>>('/inferences/batch', data)
  return response.data.data
}

async function uploadReferenceData(
  versionId: string,
  data: {
    records: Array<{
      inputs: Record<string, unknown>
      outputs: Record<string, unknown>
    }>
  }
): Promise<{ created: number }> {
  const response = await client.post<ApiResponse<{ created: number }>>(
    `/versions/${versionId}/reference-data`,
    data
  )
  return response.data.data
}

async function addGroundTruth(inferenceId: string, data: { ground_truth: Record<string, unknown> }): Promise<Inference> {
  const response = await client.post<ApiResponse<Inference>>(`/inferences/${inferenceId}/ground-truth`, data)
  return response.data.data
}

export const inferencesApi = {
  list,
  create,
  createBatch,
  uploadReferenceData,
  addGroundTruth,
}
