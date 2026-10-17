import client from './client'
import type { ApiResponse, Project, ProjectMember, ProjectMemberCreate, ProjectRole } from '@/types'

async function list(): Promise<Project[]> {
  const response = await client.get<ApiResponse<Project[]>>('/projects')
  return response.data.data
}

async function get(projectId: string): Promise<Project> {
  const response = await client.get<ApiResponse<Project>>(`/projects/${projectId}`)
  return response.data.data
}

async function create(data: { name: string; description?: string }): Promise<Project> {
  const response = await client.post<ApiResponse<Project>>('/projects', data)
  return response.data.data
}

async function update(projectId: string, data: { name?: string; description?: string }): Promise<Project> {
  const response = await client.patch<ApiResponse<Project>>(`/projects/${projectId}`, data)
  return response.data.data
}

async function remove(projectId: string): Promise<void> {
  await client.delete(`/projects/${projectId}`)
}

async function listMembers(projectId: string): Promise<ProjectMember[]> {
  const response = await client.get<ApiResponse<ProjectMember[]>>(`/projects/${projectId}/members`)
  return response.data.data
}

async function addMember(projectId: string, data: ProjectMemberCreate): Promise<ProjectMember> {
  const response = await client.post<ApiResponse<ProjectMember>>(`/projects/${projectId}/members`, data)
  return response.data.data
}

async function updateMemberRole(projectId: string, membershipId: string, role: ProjectRole): Promise<ProjectMember> {
  const response = await client.patch<ApiResponse<ProjectMember>>(
    `/projects/${projectId}/members/${membershipId}`,
    { role },
  )
  return response.data.data
}

async function removeMember(projectId: string, membershipId: string): Promise<void> {
  await client.delete(`/projects/${projectId}/members/${membershipId}`)
}

export const projectsApi = {
  list,
  get,
  create,
  update,
  delete: remove,
  listMembers,
  addMember,
  updateMemberRole,
  removeMember,
}
