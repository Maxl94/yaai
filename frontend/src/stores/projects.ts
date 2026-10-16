import { ref, computed, watch } from 'vue'
import { defineStore } from 'pinia'
import { projectsApi } from '@/api/projects'
import { useAuthStore } from '@/stores/auth'
import type { Project, ProjectRole } from '@/types'

export const CURRENT_PROJECT_STORAGE_KEY = 'yaai.currentProjectId'

const WRITE_ROLES: ReadonlyArray<ProjectRole> = ['owner', 'editor']

export const useProjectsStore = defineStore('projects', () => {
  const authStore = useAuthStore()

  const projects = ref<Project[]>([])
  const loaded = ref(false)
  const loading = ref(false)
  // null means "All projects"
  const currentProjectId = ref<string | null>(localStorage.getItem(CURRENT_PROJECT_STORAGE_KEY))

  const currentProject = computed(() => projects.value.find((p) => p.id === currentProjectId.value) ?? null)
  // Global owners (and everyone when auth is disabled) act as super-admins in every project
  const isGlobalAdmin = computed(() => !authStore.authEnabled || authStore.isOwner)
  const writableProjects = computed(() => projects.value.filter((p) => canWrite(p.id)))
  const canCreateModel = computed(() => isGlobalAdmin.value || writableProjects.value.length > 0)
  const defaultProject = computed(() => projects.value.find((p) => p.is_default) ?? null)

  function roleFor(projectId: string | null | undefined): ProjectRole | null {
    if (!projectId) return null
    return projects.value.find((p) => p.id === projectId)?.my_role ?? null
  }

  function canWrite(projectId: string | null | undefined): boolean {
    if (isGlobalAdmin.value) return true
    const role = roleFor(projectId)
    return role !== null && WRITE_ROLES.includes(role)
  }

  function canAdmin(projectId: string | null | undefined): boolean {
    return isGlobalAdmin.value || roleFor(projectId) === 'owner'
  }

  function setCurrentProject(projectId: string | null) {
    currentProjectId.value = projectId
    if (projectId) {
      localStorage.setItem(CURRENT_PROJECT_STORAGE_KEY, projectId)
    } else {
      localStorage.removeItem(CURRENT_PROJECT_STORAGE_KEY)
    }
  }

  let loadPromise: Promise<void> | null = null

  /** Load projects once; concurrent and later callers share the same result. */
  function ensureLoaded(): Promise<void> {
    if (loaded.value) return Promise.resolve()
    loadPromise ??= load().finally(() => {
      loadPromise = null
    })
    return loadPromise
  }

  async function load() {
    loading.value = true
    try {
      projects.value = await projectsApi.list()
      loaded.value = true
      // A stored selection may point to a project that was deleted or is no longer accessible
      if (currentProjectId.value && !currentProject.value) {
        setCurrentProject(null)
      }
    } catch (error) {
      console.error('Failed to load projects:', error)
    } finally {
      loading.value = false
    }
  }

  function reset() {
    projects.value = []
    loaded.value = false
    setCurrentProject(null)
  }

  watch(
    () => authStore.isAuthenticated,
    (authenticated, wasAuthenticated) => {
      if (wasAuthenticated && !authenticated) reset()
    },
  )

  return {
    projects,
    loaded,
    loading,
    currentProjectId,
    currentProject,
    defaultProject,
    isGlobalAdmin,
    writableProjects,
    canCreateModel,
    roleFor,
    canWrite,
    canAdmin,
    setCurrentProject,
    load,
    ensureLoaded,
    reset,
  }
})
