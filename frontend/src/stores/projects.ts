import { ref, computed, watch } from 'vue'
import { defineStore } from 'pinia'
import { projectsApi } from '@/api/projects'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'
import type { Project, ProjectRole } from '@/types'

export const CURRENT_PROJECT_STORAGE_KEY = 'yaai.currentProjectId'

const WRITE_ROLES: ReadonlyArray<ProjectRole> = ['owner', 'editor']

export const useProjectsStore = defineStore('projects', () => {
  const authStore = useAuthStore()

  const projects = ref<Project[]>([])
  const loaded = ref(false)
  const loading = ref(false)
  const loadError = ref<string | null>(null)
  // null means "All projects"
  const currentProjectId = ref<string | null>(localStorage.getItem(CURRENT_PROJECT_STORAGE_KEY))

  const currentProject = computed(() => projects.value.find((p) => p.id === currentProjectId.value) ?? null)
  // Validated selection: a stored id that is not in the accessible project list must never filter anything
  const activeProjectId = computed(() => currentProject.value?.id ?? null)
  // Global owners (and everyone when auth is disabled) act as super-admins in every project
  const isGlobalAdmin = computed(() => !authStore.authEnabled || authStore.isOwner)
  const writableProjects = computed(() => projects.value.filter((p) => canWrite(p.id)))
  const canCreateModel = computed(() => isGlobalAdmin.value || writableProjects.value.length > 0)
  // Signed-in users that belong to no project see nothing and cannot write anywhere
  const hasNoProjects = computed(() => loaded.value && !isGlobalAdmin.value && projects.value.length === 0)
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
  // Incremented on reset() so that responses started for a previous user are dropped
  let generation = 0

  /** Load projects once; concurrent and later callers share the same result. */
  function ensureLoaded(): Promise<void> {
    if (loaded.value) return Promise.resolve()
    loadPromise ??= load().then(() => undefined)
    return loadPromise
  }

  /**
   * Fetch the accessible projects.
   *
   * Returns:
   *   True if the list was refreshed, False if the request failed (previous data is kept and `loadError` is set).
   */
  async function load(): Promise<boolean> {
    const requestGeneration = generation
    loading.value = true
    try {
      const result = await projectsApi.list()
      if (requestGeneration !== generation) return false
      projects.value = result
      loaded.value = true
      loadError.value = null
      // A stored selection may point to a project that was deleted or is no longer accessible
      if (currentProjectId.value && !currentProject.value) {
        setCurrentProject(null)
      }
      return true
    } catch (error) {
      console.error('Failed to load projects:', error)
      if (requestGeneration === generation) {
        loadError.value = errorMessage(error, 'Failed to load projects')
      }
      return false
    } finally {
      if (requestGeneration === generation) {
        loading.value = false
        loadPromise = null
      }
    }
  }

  function reset() {
    generation++
    loadPromise = null
    projects.value = []
    loaded.value = false
    loading.value = false
    loadError.value = null
    setCurrentProject(null)
  }

  watch(
    () => authStore.isAuthenticated,
    (authenticated, wasAuthenticated) => {
      if (wasAuthenticated && !authenticated) reset()
      if (!wasAuthenticated && authenticated) void ensureLoaded()
    },
  )

  return {
    projects,
    loaded,
    loading,
    loadError,
    currentProjectId,
    activeProjectId,
    currentProject,
    defaultProject,
    isGlobalAdmin,
    writableProjects,
    canCreateModel,
    hasNoProjects,
    roleFor,
    canWrite,
    canAdmin,
    setCurrentProject,
    load,
    ensureLoaded,
    reset,
  }
})
