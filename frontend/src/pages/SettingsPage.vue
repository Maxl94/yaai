<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import type { AuthUser, ServiceAccount, ServiceAccountCreateResponse } from '@/types'

const authStore = useAuthStore()

const activeTab = ref('users')

// Users
const users = ref<AuthUser[]>([])
const loadingUsers = ref(false)
const errorUsers = ref('')
const showEditUserDialog = ref(false)
const editingUser = ref<AuthUser | null>(null)
const editUserRole = ref('viewer')
const editUserActive = ref(true)
const savingUser = ref(false)

const userHeaders = [
  { title: 'User', key: 'username' },
  { title: 'Email', key: 'email' },
  { title: 'Role', key: 'role', width: '120px' },
  { title: 'Provider', key: 'auth_provider', width: '120px' },
  { title: 'Status', key: 'is_active', width: '100px' },
  { title: '', key: 'actions', sortable: false, width: '80px' },
]

async function loadUsers() {
  loadingUsers.value = true
  errorUsers.value = ''
  try {
    users.value = await authApi.listUsers()
  } catch {
    errorUsers.value = 'Failed to load users'
  } finally {
    loadingUsers.value = false
  }
}

function openEditUser(user: AuthUser) {
  editingUser.value = user
  editUserRole.value = user.role
  editUserActive.value = user.is_active
  showEditUserDialog.value = true
}

async function saveUser() {
  if (!editingUser.value) return
  savingUser.value = true
  try {
    await authApi.updateUser(editingUser.value.id, {
      role: editUserRole.value,
      is_active: editUserActive.value,
    })
    showEditUserDialog.value = false
    await loadUsers()
  } catch {
    errorUsers.value = 'Failed to update user'
  } finally {
    savingUser.value = false
  }
}

// Service Accounts
const serviceAccounts = ref<ServiceAccount[]>([])
const loadingSAs = ref(false)
const errorSAs = ref('')
const showCreateSADialog = ref(false)
const newSA = ref({ name: '', description: '', auth_type: 'api_key', google_sa_email: '' })
const creatingSA = ref(false)
const showDeleteSADialog = ref(false)
const saToDelete = ref<ServiceAccount | null>(null)
const deletingSA = ref(false)
const createdSAResult = ref<ServiceAccountCreateResponse | null>(null)
const showCreatedSADialog = ref(false)
const keyCopied = ref(false)

const saHeaders = [
  { title: 'Name', key: 'name' },
  { title: 'Description', key: 'description' },
  { title: 'Auth Type', key: 'auth_type', width: '130px' },
  { title: 'Google Email', key: 'google_sa_email' },
  { title: 'Created', key: 'created_at', width: '140px' },
  { title: '', key: 'actions', sortable: false, width: '80px' },
]

async function loadServiceAccounts() {
  loadingSAs.value = true
  errorSAs.value = ''
  try {
    serviceAccounts.value = await authApi.listServiceAccounts()
  } catch {
    errorSAs.value = 'Failed to load service accounts'
  } finally {
    loadingSAs.value = false
  }
}

async function createServiceAccount() {
  creatingSA.value = true
  try {
    const data: { name: string; description?: string; auth_type?: string; google_sa_email?: string } = {
      name: newSA.value.name,
      auth_type: newSA.value.auth_type,
    }
    if (newSA.value.description) data.description = newSA.value.description
    if (newSA.value.auth_type === 'google' && newSA.value.google_sa_email) {
      data.google_sa_email = newSA.value.google_sa_email
    }
    const result = await authApi.createServiceAccount(data)
    showCreateSADialog.value = false
    newSA.value = { name: '', description: '', auth_type: 'api_key', google_sa_email: '' }
    
    // Show the raw key dialog if an API key was created
    if (result.raw_key) {
      createdSAResult.value = result
      showCreatedSADialog.value = true
      keyCopied.value = false
    }
    
    await loadServiceAccounts()
  } catch {
    errorSAs.value = 'Failed to create service account'
  } finally {
    creatingSA.value = false
  }
}

async function copyRawKey() {
  if (!createdSAResult.value?.raw_key) return
  await navigator.clipboard.writeText(createdSAResult.value.raw_key)
  keyCopied.value = true
}

function confirmDeleteSA(sa: ServiceAccount) {
  saToDelete.value = sa
  showDeleteSADialog.value = true
}

async function deleteServiceAccount() {
  if (!saToDelete.value) return
  deletingSA.value = true
  try {
    await authApi.deleteServiceAccount(saToDelete.value.id)
    showDeleteSADialog.value = false
    await loadServiceAccounts()
  } catch {
    errorSAs.value = 'Failed to delete service account'
  } finally {
    deletingSA.value = false
  }
}



function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleDateString()
}

onMounted(() => {
  loadUsers()
  loadServiceAccounts()
})
</script>

<template>
  <div>
    <!-- Page Header -->
    <div class="d-flex align-center mb-6">
      <div>
        <h1 class="text-h4 font-weight-bold">Settings</h1>
        <p class="text-body-2 text-medium-emphasis mt-1">Manage users and service accounts</p>
      </div>
    </div>

    <!-- Tabs -->
    <v-tabs v-model="activeTab" color="primary" class="mb-6">
      <v-tab value="users">
        <v-icon start>mdi-account-group-outline</v-icon>
        Users
      </v-tab>
      <v-tab value="service-accounts">
        <v-icon start>mdi-robot-outline</v-icon>
        Service Accounts
      </v-tab>
    </v-tabs>

    <v-tabs-window v-model="activeTab">
      <!-- Users Tab -->
      <v-tabs-window-item value="users">
        <v-alert v-if="errorUsers" type="error" variant="tonal" closable class="mb-4" @click:close="errorUsers = ''">
          {{ errorUsers }}
        </v-alert>

        <v-card variant="flat" rounded="lg" class="settings-card">
          <v-data-table
            :headers="userHeaders"
            :items="users"
            :loading="loadingUsers"
            hover
            items-per-page="-1"
            density="comfortable"
          >
            <template #item.role="{ item }">
              <v-chip
                :color="item.role === 'owner' ? 'primary' : 'default'"
                size="small"
                variant="tonal"
              >
                {{ item.role }}
              </v-chip>
            </template>
            <template #item.auth_provider="{ item }">
              <v-chip size="small" variant="outlined">
                <v-icon start size="14">{{ item.auth_provider === 'google' ? 'mdi-google' : 'mdi-lock-outline' }}</v-icon>
                {{ item.auth_provider }}
              </v-chip>
            </template>
            <template #item.is_active="{ item }">
              <v-chip
                :color="item.is_active ? 'success' : 'error'"
                size="small"
                variant="tonal"
              >
                {{ item.is_active ? 'Active' : 'Inactive' }}
              </v-chip>
            </template>
            <template #item.actions="{ item }">
              <v-btn
                v-if="item.id !== authStore.user?.id"
                icon
                size="small"
                variant="text"
                @click="openEditUser(item)"
              >
                <v-icon size="18">mdi-pencil-outline</v-icon>
                <v-tooltip activator="parent" location="top">Edit user</v-tooltip>
              </v-btn>
            </template>
          </v-data-table>
        </v-card>
      </v-tabs-window-item>

      <!-- Service Accounts Tab -->
      <v-tabs-window-item value="service-accounts">
        <v-alert v-if="errorSAs" type="error" variant="tonal" closable class="mb-4" @click:close="errorSAs = ''">
          {{ errorSAs }}
        </v-alert>

        <div class="d-flex justify-end mb-4">
          <v-btn color="primary" prepend-icon="mdi-plus" @click="showCreateSADialog = true">
            Create Service Account
          </v-btn>
        </div>

        <v-card variant="flat" rounded="lg" class="settings-card">
          <v-data-table
            :headers="saHeaders"
            :items="serviceAccounts"
            :loading="loadingSAs"
            hover
            items-per-page="-1"
            density="comfortable"
          >
            <template #item.auth_type="{ item }">
              <v-chip size="small" variant="outlined">
                <v-icon start size="14">{{ item.auth_type === 'google' ? 'mdi-google' : 'mdi-key-outline' }}</v-icon>
                {{ item.auth_type }}
              </v-chip>
            </template>
            <template #item.google_sa_email="{ item }">
              <span class="text-body-2">{{ item.google_sa_email || '—' }}</span>
            </template>
            <template #item.created_at="{ item }">
              {{ formatDate(item.created_at) }}
            </template>
            <template #item.actions="{ item }">
              <v-btn icon size="small" variant="text" color="error" @click="confirmDeleteSA(item)">
                <v-icon size="18">mdi-delete-outline</v-icon>
                <v-tooltip activator="parent" location="top">Delete</v-tooltip>
              </v-btn>
            </template>
            <template #no-data>
              <div class="text-center pa-8">
                <v-icon size="48" color="grey-lighten-1">mdi-robot-outline</v-icon>
                <p class="text-body-1 text-medium-emphasis mt-2">No service accounts yet</p>
              </div>
            </template>
          </v-data-table>
        </v-card>
      </v-tabs-window-item>
    </v-tabs-window>

    <!-- Dialogs -->

    <!-- Edit User Dialog -->
    <v-dialog v-model="showEditUserDialog" max-width="480">
      <v-card>
        <v-card-title class="pa-4 dialog-header">
          <v-icon start color="white">mdi-account-edit-outline</v-icon>
          Edit User
        </v-card-title>
        <v-card-text class="pa-6">
          <p class="text-body-1 mb-4">
            <strong>{{ editingUser?.username }}</strong>
            <span v-if="editingUser?.email" class="text-medium-emphasis ml-2">{{ editingUser.email }}</span>
          </p>
          <v-select
            v-model="editUserRole"
            :items="[{ title: 'Owner', value: 'owner' }, { title: 'Viewer', value: 'viewer' }]"
            label="Role"
            variant="outlined"
            density="comfortable"
          />
          <v-switch
            v-model="editUserActive"
            label="Active"
            color="primary"
            density="comfortable"
            hide-details
          />
        </v-card-text>
        <v-divider />
        <v-card-actions class="pa-4">
          <v-spacer />
          <v-btn variant="text" @click="showEditUserDialog = false">Cancel</v-btn>
          <v-btn color="primary" variant="flat" :loading="savingUser" @click="saveUser">Save</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Create Service Account Dialog -->
    <v-dialog v-model="showCreateSADialog" max-width="560">
      <v-card>
        <v-card-title class="pa-4 dialog-header">
          <v-icon start color="white">mdi-robot-outline</v-icon>
          Create Service Account
        </v-card-title>
        <v-card-text class="pa-6">
          <v-text-field
            v-model="newSA.name"
            label="Name"
            variant="outlined"
            density="comfortable"
            class="mb-2"
          />
          <v-textarea
            v-model="newSA.description"
            label="Description (optional)"
            variant="outlined"
            density="comfortable"
            rows="2"
            class="mb-2"
          />
          <v-select
            v-model="newSA.auth_type"
            :items="[{ title: 'API Key', value: 'api_key' }, { title: 'Google SA', value: 'google' }]"
            label="Auth Type"
            variant="outlined"
            density="comfortable"
            class="mb-2"
          />
          <v-text-field
            v-if="newSA.auth_type === 'google'"
            v-model="newSA.google_sa_email"
            label="Google Service Account Email"
            variant="outlined"
            density="comfortable"
            placeholder="sa-name@project.iam.gserviceaccount.com"
          />
        </v-card-text>
        <v-divider />
        <v-card-actions class="pa-4">
          <v-spacer />
          <v-btn variant="text" @click="showCreateSADialog = false">Cancel</v-btn>
          <v-btn color="primary" variant="flat" :loading="creatingSA" :disabled="!newSA.name" @click="createServiceAccount">
            Create
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Delete SA Confirmation -->
    <v-dialog v-model="showDeleteSADialog" max-width="440">
      <v-card>
        <v-card-title class="pa-4">Delete Service Account</v-card-title>
        <v-card-text>
          Are you sure you want to delete <strong>{{ saToDelete?.name }}</strong>?
          This will also revoke its API key and model access.
        </v-card-text>
        <v-card-actions class="pa-4">
          <v-spacer />
          <v-btn variant="text" @click="showDeleteSADialog = false">Cancel</v-btn>
          <v-btn color="error" variant="flat" :loading="deletingSA" @click="deleteServiceAccount">Delete</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Service Account Created with API Key Dialog -->
    <v-dialog v-model="showCreatedSADialog" max-width="560" persistent>
      <v-card v-if="createdSAResult">
        <v-card-title class="pa-4" style="background: rgb(16, 185, 129); color: white;">
          <v-icon start color="white">mdi-check-circle-outline</v-icon>
          Service Account Created
        </v-card-title>
        <v-card-text class="pa-6">
          <p class="text-body-1 mb-4">
            <strong>{{ createdSAResult.service_account.name }}</strong> has been created.
          </p>
          <v-alert type="warning" variant="tonal" density="compact" class="mb-4">
            Copy this API key now. You won't be able to see it again.
          </v-alert>
          <div class="d-flex align-center ga-2">
            <v-text-field
              :model-value="createdSAResult.raw_key"
              variant="outlined"
              density="comfortable"
              readonly
              hide-details
              class="key-display"
            />
            <v-btn
              :icon="keyCopied ? 'mdi-check' : 'mdi-content-copy'"
              :color="keyCopied ? 'success' : 'primary'"
              variant="tonal"
              @click="copyRawKey"
            />
          </div>
        </v-card-text>
        <v-divider />
        <v-card-actions class="pa-4">
          <v-spacer />
          <v-btn color="primary" variant="flat" @click="showCreatedSADialog = false; createdSAResult = null">Done</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<style scoped>
.settings-card {
  border: 1px solid rgba(13, 148, 136, 0.1);
}

.dialog-header {
  background: rgba(13, 148, 136, 1);
  color: white;
}

.key-display :deep(input) {
  font-family: monospace;
  font-size: 0.85rem;
}
</style>
