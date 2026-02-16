import client from './client'
import type { Model, ModelVersion, SchemaFieldCreate, DriftResult, InferenceVolumeBucket, ApiResponse, PaginatedResponse } from '@/types'

async function list(): Promise<Model[]> {
  const response = await client.get<PaginatedResponse<Model>>('/models')
  return response.data.data
}

async function get(modelId: string): Promise<Model> {
  const response = await client.get<ApiResponse<Model>>(`/models/${modelId}`)
  return response.data.data
}

async function create(data: { name: string; description?: string }): Promise<Model> {
  const response = await client.post<ApiResponse<Model>>('/models', data)
  return response.data.data
}

async function update(modelId: string, data: { name?: string; description?: string }): Promise<Model> {
  const response = await client.put<ApiResponse<Model>>(`/models/${modelId}`, data)
  return response.data.data
}

async function remove(modelId: string): Promise<void> {
  await client.delete(`/models/${modelId}`)
}

async function listVersions(modelId: string): Promise<ModelVersion[]> {
  const response = await client.get<PaginatedResponse<ModelVersion>>(`/models/${modelId}/versions`)
  return response.data.data
}

async function getVersion(modelId: string, versionId: string): Promise<ModelVersion> {
  const response = await client.get<ApiResponse<ModelVersion>>(`/models/${modelId}/versions/${versionId}`)
  return response.data.data
}

async function createVersion(modelId: string, data: { version: string; schema: SchemaFieldCreate[] }): Promise<ModelVersion> {
  const response = await client.post<ApiResponse<ModelVersion>>(`/models/${modelId}/versions`, data)
  return response.data.data
}

async function updateVersion(modelId: string, versionId: string, data: { is_active?: boolean }): Promise<ModelVersion> {
  const response = await client.patch<ApiResponse<ModelVersion>>(`/models/${modelId}/versions/${versionId}`, data)
  return response.data.data
}

async function detectSchema(data: { records: Record<string, unknown>[] }): Promise<SchemaFieldCreate[]> {
  const response = await client.post<ApiResponse<SchemaFieldCreate[]>>('/models/detect-schema', data)
  return response.data.data
}

async function updateVersionSchema(modelId: string, versionId: string, schema: SchemaFieldCreate[]): Promise<ModelVersion> {
  const response = await client.put<ApiResponse<ModelVersion>>(`/models/${modelId}/versions/${versionId}/schema`, schema)
  return response.data.data
}

async function updateFieldThreshold(modelId: string, versionId: string, fieldId: string, alertThreshold: number | null): Promise<void> {
  await client.patch(`/models/${modelId}/versions/${versionId}/fields/${fieldId}/threshold`, {
    alert_threshold: alertThreshold,
  })
}

async function getDriftResults(modelId: string, versionId: string, fieldName?: string): Promise<DriftResult[]> {
  const page_size: number = 100

  const params: Record<string, unknown> = { page_size: page_size }
  if (fieldName) params.field_name = fieldName
  const response = await client.get<PaginatedResponse<DriftResult>>(`/models/${modelId}/versions/${versionId}/drift-results`, {
    params,
  })

  let data: DriftResult[] = response.data.data

  if (response.data.meta.total > page_size) {
    const pages = Math.ceil(response.data.meta.total / page_size)
    for (let page = 2; page <= pages; page++) {
      const pageResponse = await client.get<PaginatedResponse<DriftResult>>(
        `/models/${modelId}/versions/${versionId}/drift-results`,
        {
          params: { ...params, page, page_size },
        }
      )
      data = data.concat(pageResponse.data.data)
    }
  }

  return data
}

async function getInferenceVolume(
  modelId: string,
  versionId: string,
  bucket: string = 'day',
): Promise<InferenceVolumeBucket[]> {
  const response = await client.get<ApiResponse<InferenceVolumeBucket[]>>(
    `/models/${modelId}/versions/${versionId}/inference-volume`,
    { params: { bucket } },
  )
  return response.data.data
}

export const modelsApi = {
  list,
  get,
  create,
  update,
  delete: remove,
  listVersions,
  getVersion,
  createVersion,
  updateVersion,
  updateVersionSchema,
  updateFieldThreshold,
  detectSchema,
  getDriftResults,
  getInferenceVolume,
}
