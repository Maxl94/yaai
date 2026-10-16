<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { projectsApi } from '@/api/projects'
import { authApi } from '@/api/auth'
import { useProjectsStore } from '@/stores/projects'
import { errorMessage } from '@/utils/errors'
import type { AuthUser, Project, ProjectMember, ProjectMemberCreate, ProjectRole, ServiceAccount } from '@/types'

const projectsStore = useProjectsStore()

const ROLE_OPTIONS: ProjectRole[] = ['owner', 'editor', 'viewer']
const SA_ROLE_OPTIONS: ProjectRole[] = ['editor', 'viewer']
const ROLE_COLORS: Record<ProjectRole, string> = { owner: 'primary', editor: 'info', viewer: 'default' }

const headers = [
  { title: 'Project', key: 'name' },
  { title: 'Description', key: 'description', sortable: false },
  { title: 'Models', key: 'model_count', width: '110px' },
  { title: 'My role', key: 'my_role', width: '130px' },
  { title: '', key: 'actions', sortable: false, width: '150px' },
]

const loading = computed(() => projectsStore.loading)
const errorMain = ref('')
const infoMain = ref('')

const NO_PROJECTS_MESSAGE = 'You are not a member of any project yet. Ask an administrator to add you.'

/** Reload projects and report a failed reload of this very request. */
async function refreshProjects(): Promise<boolean> {
  const ok = await projectsStore.load()
  errorMain.value = ok ? '' : (projectsStore.loadError ?? 'Failed to load projects')
  return ok
}

// Create / edit project
const showProjectDialog = ref(false)
const editingProject = ref<Project | null>(null)
const projectForm = ref({ name: '', description: '' })
const savingProject = ref(false)
const projectError = ref('')

function openCreateProject() {
  editingProject.value = null
  projectForm.value = { name: '', description: '' }
  projectError.value = ''
  showProjectDialog.value = true
}

function openEditProject(project: Project) {
  editingProject.value = project
  projectForm.value = { name: project.name, description: project.description ?? '' }
  projectError.value = ''
  showProjectDialog.value = true
}

async function saveProject() {
  savingProject.value = true
  projectError.value = ''
  try {
    const name = projectForm.value.name.trim()
    const description = projectForm.value.description.trim()
    if (editingProject.value) {
      await projectsApi.update(editingProject.value.id, { name, description })
    } else {
      await projectsApi.create({ name, description: description || undefined })
    }
    showProjectDialog.value = false
    await refreshProjects()
  } catch (error) {
    projectError.value = errorMessage(error, 'Failed to save project')
  } finally {
    savingProject.value = false
  }
}

// Delete project (global owner only)
const showDeleteDialog = ref(false)
const projectToDelete = ref<Project | null>(null)
const deleting = ref(false)
const deleteError = ref('')

function deleteBlockedReason(project: Project): string | null {
  if (project.is_default) return 'The default project cannot be deleted'
  if (project.model_count > 0) return 'Only empty projects can be deleted'
  return null
}

function confirmDelete(project: Project) {
  projectToDelete.value = project
  deleteError.value = ''
  showDeleteDialog.value = true
}

async function deleteProject() {
  if (!projectToDelete.value) return
  deleting.value = true
  deleteError.value = ''
  try {
    await projectsApi.delete(projectToDelete.value.id)
    showDeleteDialog.value = false
    projectToDelete.value = null
    await refreshProjects()
  } catch (error) {
    deleteError.value = errorMessage(error, 'Failed to delete project')
  } finally {
    deleting.value = false
  }
}

// Members
const showMembersDialog = ref(false)
const membersProject = ref<Project | null>(null)
const members = ref<ProjectMember[]>([])
const loadingMembers = ref(false)
const membersError = ref('')
const users = ref<AuthUser[]>([])
const serviceAccounts = ref<ServiceAccount[]>([])
const memberToRemove = ref<ProjectMember | null>(null)
const showRemoveDialog = ref(false)

const principalType = ref<'user' | 'service_account'>('user')
const newUsername = ref('')
const newUserId = ref<string | null>(null)
const newServiceAccountId = ref<string | null>(null)
const newRole = ref<ProjectRole>('viewer')
const addingMember = ref(false)

const memberHeaders = [
  { title: 'Name', key: 'name' },
  { title: 'Email', key: 'email' },
  { title: 'Type', key: 'principal_type', width: '140px' },
  { title: 'Role', key: 'role', width: '170px' },
  { title: '', key: 'actions', sortable: false, width: '70px' },
]

const roleOptionsForNew = computed(() => (principalType.value === 'service_account' ? SA_ROLE_OPTIONS : ROLE_OPTIONS))

const userItems = computed(() => {
  const memberIds = new Set(members.value.map((m) => m.user_id))
  return users.value.filter((u) => !memberIds.has(u.id)).map((u) => ({ title: u.username, value: u.id }))
})

const serviceAccountItems = computed(() => {
  const memberIds = new Set(members.value.map((m) => m.service_account_id))
  return serviceAccounts.value.filter((sa) => !memberIds.has(sa.id)).map((sa) => ({ title: sa.name, value: sa.id }))
})

// Project owners cannot list users, so they add users by username; global owners pick from the user list
const canPickPrincipals = computed(() => projectsStore.isGlobalAdmin)

const canSubmitMember = computed(() => {
  if (principalType.value === 'service_account') return !!newServiceAccountId.value
  return canPickPrincipals.value ? !!newUserId.value : !!newUsername.value.trim()
})

function onPrincipalTypeChange() {
  if (principalType.value === 'service_account' && newRole.value === 'owner') {
    newRole.value = 'editor'
  }
}

async function loadMembers(projectId: string) {
  loadingMembers.value = true
  try {
    members.value = await projectsApi.listMembers(projectId)
  } catch (error) {
    membersError.value = errorMessage(error, 'Failed to load members')
  } finally {
    loadingMembers.value = false
  }
}

async function loadPrincipalChoices() {
  try {
    const [userList, saList] = await Promise.all([authApi.listUsers(), authApi.listServiceAccounts()])
    users.value = userList
    serviceAccounts.value = saList
  } catch (error) {
    membersError.value = errorMessage(error, 'Failed to load users and service accounts')
  }
}

async function openMembers(project: Project) {
  membersProject.value = project
  members.value = []
  membersError.value = ''
  principalType.value = 'user'
  newUsername.value = ''
  newUserId.value = null
  newServiceAccountId.value = null
  newRole.value = 'viewer'
  showMembersDialog.value = true
  await Promise.all([loadMembers(project.id), canPickPrincipals.value ? loadPrincipalChoices() : Promise.resolve()])
}

function buildMemberPayload(): ProjectMemberCreate {
  if (principalType.value === 'service_account') {
    return { service_account_id: newServiceAccountId.value!, role: newRole.value }
  }
  return canPickPrincipals.value
    ? { user_id: newUserId.value!, role: newRole.value }
    : { username: newUsername.value.trim(), role: newRole.value }
}

async function addMember() {
  if (!membersProject.value || !canSubmitMember.value) return
  addingMember.value = true
  membersError.value = ''
  try {
    await projectsApi.addMember(membersProject.value.id, buildMemberPayload())
    newUsername.value = ''
    newUserId.value = null
    newServiceAccountId.value = null
    await loadMembers(membersProject.value.id)
  } catch (error) {
    membersError.value = errorMessage(error, 'Failed to add member')
  } finally {
    addingMember.value = false
  }
}

async function changeRole(member: ProjectMember, role: ProjectRole) {
  if (!membersProject.value || role === member.role) return
  membersError.value = ''
  try {
    await projectsApi.updateMemberRole(membersProject.value.id, member.id, role)
  } catch (error) {
    membersError.value = errorMessage(error, 'Failed to change role')
  }
  // Reload in both cases so the table reflects the server state (also after a rejected change)
  await reloadAfterMembershipChange(membersProject.value.id)
}

// Owners may demote or remove themselves; then the members list is no longer accessible to them
async function reloadAfterMembershipChange(projectId: string) {
  const refreshed = await refreshProjects()
  if (refreshed && !projectsStore.canAdmin(projectId)) {
    showMembersDialog.value = false
    infoMain.value = 'You no longer manage this project, so its member list was closed.'
    return
  }
  await loadMembers(projectId)
}

function confirmRemove(member: ProjectMember) {
  memberToRemove.value = member
  showRemoveDialog.value = true
}

async function removeMember() {
  if (!membersProject.value || !memberToRemove.value) return
  membersError.value = ''
  try {
    await projectsApi.removeMember(membersProject.value.id, memberToRemove.value.id)
  } catch (error) {
    membersError.value = errorMessage(error, 'Failed to remove member')
  }
  showRemoveDialog.value = false
  memberToRemove.value = null
  await reloadAfterMembershipChange(membersProject.value.id)
}

onMounted(refreshProjects)
</script>

<template>
  <div>
    <div class="d-flex align-center mb-6">
      <div>
        <h1 class="text-h4 font-weight-bold">Projects</h1>
        <p class="text-body-2 text-medium-emphasis mt-1">
          Projects group models and control who can see and change them
        </p>
      </div>
      <v-spacer />
      <v-btn
        v-if="projectsStore.isGlobalAdmin"
        color="primary"
        prepend-icon="mdi-plus"
        data-testid="create-project"
        @click="openCreateProject"
      >
        New Project
      </v-btn>
    </div>

    <v-alert v-if="errorMain" type="error" variant="tonal" closable class="mb-4" @click:close="errorMain = ''">
      {{ errorMain }}
    </v-alert>

    <v-alert v-if="infoMain" type="info" variant="tonal" closable class="mb-4" @click:close="infoMain = ''">
      {{ infoMain }}
    </v-alert>

    <v-alert v-if="projectsStore.hasNoProjects" type="info" variant="tonal" class="mb-4" data-testid="no-projects">
      {{ NO_PROJECTS_MESSAGE }}
    </v-alert>

    <v-card variant="flat" rounded="lg" class="projects-card">
      <v-data-table
        :headers="headers"
        :items="projectsStore.projects"
        :loading="loading"
        hover
        items-per-page="-1"
        hide-default-footer
        density="comfortable"
        no-data-text="No projects available"
      >
        <template #item.name="{ item }">
          <span class="font-weight-medium">{{ item.name }}</span>
          <v-chip v-if="item.is_default" size="x-small" variant="tonal" class="ml-2">default</v-chip>
        </template>
        <template #item.description="{ item }">
          <span class="text-medium-emphasis">{{ item.description || '—' }}</span>
        </template>
        <template #item.my_role="{ item }">
          <v-chip
            v-if="projectsStore.isGlobalAdmin || item.my_role"
            :color="ROLE_COLORS[projectsStore.isGlobalAdmin ? 'owner' : item.my_role!]"
            size="small"
            variant="tonal"
          >
            {{ projectsStore.isGlobalAdmin ? 'owner' : item.my_role }}
          </v-chip>
        </template>
        <template #item.actions="{ item }">
          <div v-if="projectsStore.canAdmin(item.id)" class="d-flex justify-end">
            <v-btn
              icon
              size="small"
              variant="text"
              :aria-label="`Members of ${item.name}`"
              @click="openMembers(item)"
            >
              <v-icon size="18">mdi-account-multiple-outline</v-icon>
              <v-tooltip activator="parent" location="top">Members</v-tooltip>
            </v-btn>
            <v-btn
              icon
              size="small"
              variant="text"
              :aria-label="`Edit ${item.name}`"
              @click="openEditProject(item)"
            >
              <v-icon size="18">mdi-pencil-outline</v-icon>
              <v-tooltip activator="parent" location="top">Edit project</v-tooltip>
            </v-btn>
            <v-btn
              v-if="projectsStore.isGlobalAdmin"
              icon
              size="small"
              variant="text"
              color="error"
              :disabled="!!deleteBlockedReason(item)"
              :aria-label="`Delete ${item.name}`"
              @click="confirmDelete(item)"
            >
              <v-icon size="18">mdi-delete-outline</v-icon>
              <v-tooltip activator="parent" location="top">
                {{ deleteBlockedReason(item) ?? 'Delete project' }}
              </v-tooltip>
            </v-btn>
          </div>
        </template>
      </v-data-table>
    </v-card>

    <!-- Create / Edit Project Dialog -->
    <v-dialog v-model="showProjectDialog" max-width="480">
      <v-card>
        <v-card-title class="pa-4">{{ editingProject ? 'Edit Project' : 'Create Project' }}</v-card-title>
        <v-card-text>
          <v-alert v-if="projectError" type="error" variant="tonal" density="compact" class="mb-4">
            {{ projectError }}
          </v-alert>
          <v-text-field
            v-model="projectForm.name"
            label="Project Name"
            :disabled="editingProject?.is_default"
            :hint="editingProject?.is_default ? 'The default project cannot be renamed' : undefined"
            persistent-hint
            autofocus
            class="mb-4"
          />
          <v-textarea v-model="projectForm.description" label="Description" rows="3" />
        </v-card-text>
        <v-card-actions class="pa-4">
          <v-spacer />
          <v-btn variant="text" @click="showProjectDialog = false">Cancel</v-btn>
          <v-btn
            color="primary"
            variant="flat"
            :loading="savingProject"
            :disabled="!projectForm.name.trim()"
            @click="saveProject"
          >
            {{ editingProject ? 'Save' : 'Create' }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Delete Project Dialog -->
    <v-dialog v-model="showDeleteDialog" max-width="440">
      <v-card>
        <v-card-title class="pa-4 text-error">Delete Project</v-card-title>
        <v-card-text>
          <v-alert v-if="deleteError" type="error" variant="tonal" density="compact" class="mb-4">
            {{ deleteError }}
          </v-alert>
          Are you sure you want to delete <strong>{{ projectToDelete?.name }}</strong>?
          All memberships of this project will be removed.
        </v-card-text>
        <v-card-actions class="pa-4">
          <v-spacer />
          <v-btn variant="text" @click="showDeleteDialog = false">Cancel</v-btn>
          <v-btn color="error" variant="flat" :loading="deleting" @click="deleteProject">Delete</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Members Dialog -->
    <v-dialog v-model="showMembersDialog" max-width="860">
      <v-card>
        <v-card-title class="pa-4">Members of {{ membersProject?.name }}</v-card-title>
        <v-card-text>
          <v-alert
            v-if="membersError"
            type="error"
            variant="tonal"
            density="compact"
            closable
            class="mb-4"
            data-testid="members-error"
            @click:close="membersError = ''"
          >
            {{ membersError }}
          </v-alert>

          <v-data-table
            :headers="memberHeaders"
            :items="members"
            :loading="loadingMembers"
            items-per-page="-1"
            density="comfortable"
            hide-default-footer
            no-data-text="No members yet"
          >
            <template #item.email="{ item }">{{ item.email || '—' }}</template>
            <template #item.principal_type="{ item }">
              <v-chip size="small" variant="outlined">
                <v-icon start size="14">
                  {{ item.principal_type === 'user' ? 'mdi-account-outline' : 'mdi-robot-outline' }}
                </v-icon>
                {{ item.principal_type === 'user' ? 'User' : 'Service account' }}
              </v-chip>
            </template>
            <template #item.role="{ item }">
              <v-select
                :model-value="item.role"
                :items="item.principal_type === 'service_account' ? SA_ROLE_OPTIONS : ROLE_OPTIONS"
                density="compact"
                hide-details
                :aria-label="`Role of ${item.name}`"
                @update:model-value="changeRole(item, $event)"
              />
            </template>
            <template #item.actions="{ item }">
              <v-btn
                icon
                size="small"
                variant="text"
                color="error"
                :aria-label="`Remove ${item.name}`"
                @click="confirmRemove(item)"
              >
                <v-icon size="18">mdi-delete-outline</v-icon>
                <v-tooltip activator="parent" location="top">Remove member</v-tooltip>
              </v-btn>
            </template>
          </v-data-table>

          <v-divider class="my-4" />

          <h4 class="text-subtitle-1 mb-3">Add member</h4>
          <div class="d-flex ga-3 align-start flex-wrap">
            <v-select
              v-if="canPickPrincipals"
              v-model="principalType"
              :items="[
                { title: 'User', value: 'user' },
                { title: 'Service account', value: 'service_account' },
              ]"
              label="Type"
              hide-details
              style="max-width: 190px"
              @update:model-value="onPrincipalTypeChange"
            />
            <v-select
              v-if="principalType === 'service_account'"
              v-model="newServiceAccountId"
              :items="serviceAccountItems"
              label="Service account"
              no-data-text="No available service accounts"
              hide-details
              style="min-width: 220px"
            />
            <v-autocomplete
              v-else-if="canPickPrincipals"
              v-model="newUserId"
              :items="userItems"
              label="User"
              no-data-text="No available users"
              hide-details
              style="min-width: 220px"
            />
            <v-text-field
              v-else
              v-model="newUsername"
              label="Username"
              hide-details
              style="min-width: 220px"
              @keyup.enter="addMember"
            />
            <v-select
              v-model="newRole"
              :items="roleOptionsForNew"
              label="Role"
              hide-details
              style="max-width: 160px"
            />
            <v-btn
              color="primary"
              variant="flat"
              height="48"
              prepend-icon="mdi-plus"
              :loading="addingMember"
              :disabled="!canSubmitMember"
              data-testid="add-member"
              @click="addMember"
            >
              Add
            </v-btn>
          </div>
        </v-card-text>
        <v-card-actions class="pa-4">
          <v-spacer />
          <v-btn variant="flat" color="primary" @click="showMembersDialog = false">Close</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Remove Member Dialog -->
    <v-dialog v-model="showRemoveDialog" max-width="440">
      <v-card>
        <v-card-title class="pa-4">Remove Member</v-card-title>
        <v-card-text>
          Remove <strong>{{ memberToRemove?.name }}</strong> from <strong>{{ membersProject?.name }}</strong>?
        </v-card-text>
        <v-card-actions class="pa-4">
          <v-spacer />
          <v-btn variant="text" @click="showRemoveDialog = false">Cancel</v-btn>
          <v-btn color="error" variant="flat" @click="removeMember">Remove</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<style scoped>
.projects-card {
  border: 1px solid rgba(13, 148, 136, 0.1);
}
</style>
