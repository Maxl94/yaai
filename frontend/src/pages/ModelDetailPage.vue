<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { modelsApi } from '@/api/models'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import type { Model, ModelVersionSummary, SchemaFieldCreate, SchemaField, ModelAccessEntry, ServiceAccount } from '@/types'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const modelId = computed(() => route.params.modelId as string)

const model = ref<Model | null>(null)
const loading = ref(true)
const editingName = ref(false)
const editedName = ref('')
const editedDescription = ref('')

// Version creation
const showCreateVersionDialog = ref(false)
const newVersion = ref({
  version: '',
  schema: [] as SchemaFieldCreate[],
})
const creatingVersion = ref(false)

// Schema dialog
const showSchemaDialog = ref(false)
const selectedVersionForSchema = ref<ModelVersionSummary | null>(null)
const versionSchema = ref<SchemaField[]>([])
const loadingSchema = ref(false)
const editingSchema = ref(false)
const savingSchema = ref(false)

async function openSchemaDialog(version: ModelVersionSummary) {
  selectedVersionForSchema.value = version
  showSchemaDialog.value = true
  loadingSchema.value = true
  editingSchema.value = false
  try {
    const fullVersion = await modelsApi.getVersion(modelId.value, version.id)
    versionSchema.value = fullVersion.schema_fields || []
  } catch (error) {
    console.error('Failed to load schema:', error)
    versionSchema.value = []
  } finally {
    loadingSchema.value = false
  }
}

function addSchemaFieldToVersion() {
  versionSchema.value.push({
    id: `temp-${Date.now()}`,
    model_version_id: selectedVersionForSchema.value?.id || '',
    field_name: '',
    direction: 'input',
    data_type: 'numerical',
    drift_metric: null,
    alert_threshold: null,
  })
}

function removeSchemaFieldFromVersion(index: number) {
  versionSchema.value.splice(index, 1)
}

async function saveSchemaChanges() {
  if (!selectedVersionForSchema.value) return
  savingSchema.value = true
  try {
    // Convert to create format for update
    const schemaData: SchemaFieldCreate[] = versionSchema.value.map(f => ({
      field_name: f.field_name,
      direction: f.direction,
      data_type: f.data_type,
      drift_metric: f.drift_metric || undefined,
      alert_threshold: f.alert_threshold || undefined,
    }))
    const versionId = selectedVersionForSchema.value.id
    await modelsApi.updateVersionSchema(modelId.value, versionId, schemaData)
    editingSchema.value = false
    // Update the field count in the summary
    const versions = model.value?.versions
    if (versions) {
      const versionIndex = versions.findIndex(v => v.id === versionId)
      const versionToUpdate = versions[versionIndex]
      if (versionIndex >= 0 && versionToUpdate) {
        versionToUpdate.schema_field_count = versionSchema.value.length
      }
    }
  } catch (error) {
    console.error('Failed to save schema:', error)
  } finally {
    savingSchema.value = false
  }
}

async function fetchModel() {
  loading.value = true
  try {
    model.value = await modelsApi.get(modelId.value)
  } catch (error) {
    console.error('Failed to fetch model:', error)
  } finally {
    loading.value = false
  }
}

async function handleUpdateModel() {
  if (!model.value) return
  try {
    await modelsApi.update(modelId.value, {
      name: editedName.value,
      description: editedDescription.value || undefined,
    })
    model.value.name = editedName.value
    model.value.description = editedDescription.value
    editingName.value = false
  } catch (error) {
    console.error('Failed to update model:', error)
  }
}

function startEditing() {
  if (!model.value) return
  editedName.value = model.value.name
  editedDescription.value = model.value.description || ''
  editingName.value = true
}

function addSchemaField() {
  newVersion.value.schema.push({
    field_name: '',
    direction: 'input',
    data_type: 'numerical',
  })
}

function removeSchemaField(index: number) {
  newVersion.value.schema.splice(index, 1)
}

async function handleCreateVersion() {
  if (!newVersion.value.version || newVersion.value.schema.length === 0) return
  creatingVersion.value = true
  try {
    const created = await modelsApi.createVersion(modelId.value, {
      version: newVersion.value.version,
      schema: newVersion.value.schema,
    })
    if (model.value) {
      if (!model.value.versions) {
        model.value.versions = []
      }
      // Add the new version as a summary
      model.value.versions.push({
        id: created.id,
        version: created.version,
        is_active: created.is_active,
        created_at: created.created_at,
        schema_field_count: created.schema_fields?.length ?? 0,
      })
    }
    showCreateVersionDialog.value = false
    newVersion.value = { version: '', schema: [] }
  } catch (error) {
    console.error('Failed to create version:', error)
  } finally {
    creatingVersion.value = false
  }
}

function navigateToVersion(version: ModelVersionSummary) {
  router.push(`/models/${modelId.value}/versions/${version.id}/dashboard`)
}

// Model Access (Owner only)
const modelAccess = ref<ModelAccessEntry[]>([])
const allServiceAccounts = ref<ServiceAccount[]>([])
const loadingAccess = ref(false)
const showGrantDialog = ref(false)
const grantSAId = ref<string | undefined>(undefined)
const grantingAccess = ref(false)
const showRevokeDialog = ref(false)
const accessToRevoke = ref<ModelAccessEntry | null>(null)
const revokingAccess = ref(false)

const availableSAs = computed(() => {
  const grantedIds = new Set(modelAccess.value.map(a => a.service_account_id))
  return allServiceAccounts.value
    .filter(sa => !grantedIds.has(sa.id))
    .map(sa => ({ title: sa.name, value: sa.id }))
})

function saNameById(saId: string): string {
  return allServiceAccounts.value.find(sa => sa.id === saId)?.name ?? saId.slice(0, 8) + '...'
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleDateString()
}

async function loadModelAccess() {
  loadingAccess.value = true
  try {
    const [access, sas] = await Promise.all([
      authApi.listModelAccess(modelId.value),
      authApi.listServiceAccounts(),
    ])
    modelAccess.value = access
    allServiceAccounts.value = sas
  } catch {
    console.error('Failed to load model access')
  } finally {
    loadingAccess.value = false
  }
}

async function grantAccess() {
  if (!grantSAId.value) return
  grantingAccess.value = true
  try {
    await authApi.grantModelAccess(modelId.value, grantSAId.value)
    showGrantDialog.value = false
    grantSAId.value = undefined
    await loadModelAccess()
  } catch {
    console.error('Failed to grant access')
  } finally {
    grantingAccess.value = false
  }
}

function confirmRevoke(entry: ModelAccessEntry) {
  accessToRevoke.value = entry
  showRevokeDialog.value = true
}

async function revokeAccess() {
  if (!accessToRevoke.value) return
  revokingAccess.value = true
  try {
    await authApi.revokeModelAccess(modelId.value, accessToRevoke.value.service_account_id)
    showRevokeDialog.value = false
    await loadModelAccess()
  } catch {
    console.error('Failed to revoke access')
  } finally {
    revokingAccess.value = false
  }
}

onMounted(() => {
  fetchModel()
  if (authStore.isOwner) {
    loadModelAccess()
  }
})
</script>

<template>
  <div v-if="loading">
    <v-progress-linear indeterminate color="primary" />
  </div>

  <div v-else-if="model">
    <!-- Breadcrumb -->
    <v-breadcrumbs :items="[{ title: 'Models', to: '/models' }, { title: model.name }]" />

    <!-- Model Header -->
    <v-card class="mb-4">
      <v-card-title class="d-flex align-center">
        <template v-if="!editingName">
          <v-icon start>mdi-cube-outline</v-icon>
          {{ model.name }}
          <v-btn icon="mdi-pencil" size="small" variant="text" class="ml-2" @click="startEditing" />
        </template>
        <template v-else>
          <v-text-field
            v-model="editedName"
            variant="outlined"
            density="compact"
            hide-details
            class="flex-grow-0"
            style="max-width: 300px; width: 100%;"
          />
        </template>
      </v-card-title>
      <v-card-text>
        <template v-if="!editingName">
          <p v-if="model.description">{{ model.description }}</p>
          <p v-else class="text-grey">No description</p>
        </template>
        <template v-else>
          <v-textarea
            v-model="editedDescription"
            label="Description"
            variant="outlined"
            rows="2"
            class="mt-2"
          />
          <div class="d-flex gap-2 mt-2">
            <v-btn variant="text" @click="editingName = false">Cancel</v-btn>
            <v-btn color="primary" @click="handleUpdateModel">Save</v-btn>
          </div>
        </template>
      </v-card-text>
    </v-card>

    <!-- Versions Section -->
    <div class="d-flex align-center mb-4">
      <h2 class="text-h5">Versions</h2>
      <v-spacer />
      <v-btn color="primary" prepend-icon="mdi-plus" @click="showCreateVersionDialog = true">
        New Version
      </v-btn>
    </div>

    <v-table v-if="model.versions && model.versions.length > 0">
      <thead>
        <tr>
          <th>Version</th>
          <th>Status</th>
          <th>Schema Fields</th>
          <th>Created</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="version in model.versions"
          :key="version.id"
          class="cursor-pointer"
          @click="navigateToVersion(version)"
        >
          <td>{{ version.version }}</td>
          <td>
            <v-chip :color="version.is_active ? 'success' : 'default'" size="small">
              {{ version.is_active ? 'Active' : 'Inactive' }}
            </v-chip>
          </td>
          <td>{{ version.schema_field_count ?? 0 }} fields</td>
          <td>{{ new Date(version.created_at).toLocaleDateString() }}</td>
          <td class="actions-cell">
            <v-btn
              size="small"
              variant="tonal"
              color="primary"
              class="mr-1"
              @click.stop="openSchemaDialog(version)"
            >
              <v-icon start size="16">mdi-file-tree</v-icon>
              Schema
            </v-btn>
            <v-btn
              size="small"
              variant="tonal"
              color="info"
              class="mr-1"
              @click.stop="router.push(`/models/${modelId}/versions/${version.id}/dashboard`)"
            >
              <v-icon start size="16">mdi-view-dashboard</v-icon>
              Dashboard
            </v-btn>
            <v-btn
              size="small"
              variant="tonal"
              color="secondary"
              class="mr-1"
              @click.stop="router.push(`/models/${modelId}/versions/${version.id}/compare`)"
            >
              <v-icon start size="16">mdi-compare</v-icon>
              Compare
            </v-btn>
            <v-btn
              size="small"
              variant="tonal"
              color="warning"
              class="mr-1"
              @click.stop="router.push(`/models/${modelId}/versions/${version.id}/drift`)"
            >
              <v-icon start size="16">mdi-chart-timeline</v-icon>
              Drift
            </v-btn>
            <v-btn
              size="small"
              variant="tonal"
              color="success"
              @click.stop="router.push(`/models/${modelId}/versions/${version.id}/jobs`)"
            >
              <v-icon start size="16">mdi-calendar-clock</v-icon>
              Jobs
            </v-btn>
          </td>
        </tr>
      </tbody>
    </v-table>

    <v-alert v-else type="info" variant="tonal">
      No versions yet. Create your first version to define the model schema.
    </v-alert>

    <!-- Create Version Dialog -->
    <v-dialog v-model="showCreateVersionDialog" max-width="700">
      <v-card>
        <v-card-title>Create New Version</v-card-title>
        <v-card-text>
          <v-text-field
            v-model="newVersion.version"
            label="Version Label"
            placeholder="e.g., v1.0, 2024-01"
            variant="outlined"
            required
            class="mb-4"
          />

          <h4 class="text-subtitle-1 mb-2">Schema Fields</h4>

          <div v-for="(field, index) in newVersion.schema" :key="index" class="d-flex gap-2 mb-2">
            <v-text-field
              v-model="field.field_name"
              label="Field Name"
              variant="outlined"
              density="compact"
              hide-details
              style="flex: 2"
            />
            <v-select
              v-model="field.direction"
              :items="['input', 'output']"
              label="Direction"
              variant="outlined"
              density="compact"
              hide-details
              style="flex: 1"
            />
            <v-select
              v-model="field.data_type"
              :items="['numerical', 'categorical']"
              label="Type"
              variant="outlined"
              density="compact"
              hide-details
              style="flex: 1"
            />
            <v-btn icon="mdi-delete" variant="text" color="error" @click="removeSchemaField(index)" />
          </div>

          <v-btn variant="outlined" prepend-icon="mdi-plus" @click="addSchemaField">
            Add Field
          </v-btn>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="showCreateVersionDialog = false">Cancel</v-btn>
          <v-btn
            color="primary"
            :loading="creatingVersion"
            :disabled="!newVersion.version || newVersion.schema.length === 0"
            @click="handleCreateVersion"
          >
            Create Version
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Schema View/Edit Dialog -->
    <v-dialog v-model="showSchemaDialog" max-width="800">
      <v-card>
        <v-card-title class="d-flex align-center pa-4 bg-primary">
          <v-icon start color="white">mdi-file-tree</v-icon>
          <span class="text-white font-weight-bold">
            Schema: {{ selectedVersionForSchema?.version }}
          </span>
          <v-spacer />
          <v-btn
            v-if="!editingSchema && !loadingSchema"
            icon
            variant="text"
            color="white"
            size="small"
            @click="editingSchema = true"
          >
            <v-icon>mdi-pencil</v-icon>
            <v-tooltip activator="parent" location="bottom">Edit Schema</v-tooltip>
          </v-btn>
        </v-card-title>
        <v-card-text class="pa-4">
          <v-progress-linear v-if="loadingSchema" indeterminate color="primary" />

          <template v-else-if="versionSchema.length > 0">
            <!-- View Mode -->
            <v-table v-if="!editingSchema" density="comfortable">
              <thead>
                <tr>
                  <th>Field Name</th>
                  <th>Direction</th>
                  <th>Data Type</th>
                  <th>Drift Metric</th>
                  <th>Threshold</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="field in versionSchema" :key="field.id">
                  <td class="font-weight-medium">{{ field.field_name }}</td>
                  <td>
                    <v-chip
                      size="small"
                      :color="field.direction === 'input' ? 'primary' : 'secondary'"
                      variant="tonal"
                    >
                      {{ field.direction }}
                    </v-chip>
                  </td>
                  <td>
                    <v-chip size="small" variant="outlined">
                      {{ field.data_type }}
                    </v-chip>
                  </td>
                  <td>{{ field.drift_metric || 'auto' }}</td>
                  <td>{{ field.alert_threshold ?? 'default' }}</td>
                </tr>
              </tbody>
            </v-table>

            <!-- Edit Mode -->
            <div v-else>
              <div v-for="(field, index) in versionSchema" :key="field.id" class="d-flex gap-2 mb-3 align-center">
                <v-text-field
                  v-model="field.field_name"
                  label="Field Name"
                  variant="outlined"
                  density="compact"
                  hide-details
                  style="flex: 2"
                />
                <v-select
                  v-model="field.direction"
                  :items="['input', 'output']"
                  label="Direction"
                  variant="outlined"
                  density="compact"
                  hide-details
                  style="flex: 1"
                />
                <v-select
                  v-model="field.data_type"
                  :items="['numerical', 'categorical']"
                  label="Type"
                  variant="outlined"
                  density="compact"
                  hide-details
                  style="flex: 1"
                />
                <v-text-field
                  v-model="field.drift_metric"
                  label="Drift Metric"
                  variant="outlined"
                  density="compact"
                  hide-details
                  placeholder="auto"
                  style="flex: 1"
                />
                <v-text-field
                  v-model.number="field.alert_threshold"
                  label="Threshold"
                  variant="outlined"
                  density="compact"
                  hide-details
                  type="number"
                  step="0.01"
                  placeholder="default"
                  style="flex: 0.8"
                />
                <v-btn
                  icon
                  variant="text"
                  color="error"
                  size="small"
                  @click="removeSchemaFieldFromVersion(index)"
                >
                  <v-icon>mdi-delete</v-icon>
                </v-btn>
              </div>
              <v-btn
                variant="outlined"
                color="primary"
                prepend-icon="mdi-plus"
                size="small"
                @click="addSchemaFieldToVersion"
              >
                Add Field
              </v-btn>
            </div>
          </template>

          <div v-else class="text-center py-8">
            <v-icon size="48" color="grey-lighten-1">mdi-file-tree-outline</v-icon>
            <p class="text-body-1 text-medium-emphasis mt-2">No schema fields defined</p>
            <v-btn
              v-if="!editingSchema"
              variant="outlined"
              color="primary"
              class="mt-2"
              @click="editingSchema = true"
            >
              <v-icon start>mdi-plus</v-icon>
              Add Fields
            </v-btn>
          </div>
        </v-card-text>
        <v-divider />
        <v-card-actions class="pa-4">
          <v-chip size="small" variant="tonal">
            {{ versionSchema.length }} field(s)
          </v-chip>
          <v-spacer />
          <template v-if="editingSchema">
            <v-btn variant="text" @click="editingSchema = false; openSchemaDialog(selectedVersionForSchema!)">
              Cancel
            </v-btn>
            <v-btn
              color="primary"
              variant="flat"
              :loading="savingSchema"
              @click="saveSchemaChanges"
            >
              <v-icon start>mdi-content-save</v-icon>
              Save Changes
            </v-btn>
          </template>
          <v-btn v-else variant="flat" color="primary" @click="showSchemaDialog = false">
            Close
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Service Account Access (Owner only) -->
    <template v-if="authStore.isOwner">
      <div class="d-flex align-center mb-4 mt-8">
        <h2 class="text-h5">Service Account Access</h2>
        <v-spacer />
        <v-btn color="primary" prepend-icon="mdi-plus" size="small" @click="showGrantDialog = true">
          Grant Access
        </v-btn>
      </div>

      <v-progress-linear v-if="loadingAccess" indeterminate color="primary" class="mb-4" />

      <v-card v-else-if="modelAccess.length > 0" variant="flat" rounded="lg" style="border: 1px solid rgba(13, 148, 136, 0.1);">
        <v-table density="comfortable" hover>
          <thead>
            <tr>
              <th>Service Account</th>
              <th>Granted</th>
              <th style="width: 80px;"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="entry in modelAccess" :key="entry.id">
              <td class="font-weight-medium">{{ saNameById(entry.service_account_id) }}</td>
              <td>{{ formatDate(entry.created_at) }}</td>
              <td>
                <v-btn icon size="small" variant="text" color="error" @click="confirmRevoke(entry)">
                  <v-icon size="18">mdi-delete-outline</v-icon>
                  <v-tooltip activator="parent" location="top">Revoke access</v-tooltip>
                </v-btn>
              </td>
            </tr>
          </tbody>
        </v-table>
      </v-card>

      <v-alert v-else type="info" variant="tonal">
        No service accounts have access to this model yet.
      </v-alert>

      <!-- Grant Access Dialog -->
      <v-dialog v-model="showGrantDialog" max-width="480">
        <v-card>
          <v-card-title class="pa-4" style="background: rgba(13, 148, 136, 1); color: white;">
            <v-icon start color="white">mdi-shield-plus-outline</v-icon>
            Grant Model Access
          </v-card-title>
          <v-card-text class="pa-6">
            <v-select
              v-model="grantSAId"
              :items="availableSAs"
              label="Service Account"
              variant="outlined"
              density="comfortable"
              no-data-text="No available service accounts"
            />
          </v-card-text>
          <v-divider />
          <v-card-actions class="pa-4">
            <v-spacer />
            <v-btn variant="text" @click="showGrantDialog = false">Cancel</v-btn>
            <v-btn color="primary" variant="flat" :loading="grantingAccess" :disabled="!grantSAId" @click="grantAccess">
              Grant
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-dialog>

      <!-- Revoke Access Confirmation -->
      <v-dialog v-model="showRevokeDialog" max-width="440">
        <v-card>
          <v-card-title class="pa-4">Revoke Access</v-card-title>
          <v-card-text>
            Are you sure you want to revoke access for
            <strong>{{ accessToRevoke ? saNameById(accessToRevoke.service_account_id) : '' }}</strong>
            to this model?
          </v-card-text>
          <v-card-actions class="pa-4">
            <v-spacer />
            <v-btn variant="text" @click="showRevokeDialog = false">Cancel</v-btn>
            <v-btn color="error" variant="flat" :loading="revokingAccess" @click="revokeAccess">Revoke</v-btn>
          </v-card-actions>
        </v-card>
      </v-dialog>
    </template>
  </div>

  <v-alert v-else type="error">Model not found</v-alert>
</template>

<style scoped>
.cursor-pointer {
  cursor: pointer;
}
.cursor-pointer:hover {
  background-color: rgba(0, 0, 0, 0.04);
}
.actions-cell {
  white-space: nowrap;
}
</style>
