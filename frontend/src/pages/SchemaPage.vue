<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { modelsApi } from '@/api/models'
import { jobsApi } from '@/api/jobs'
import VersionNavTabs from '@/components/VersionNavTabs.vue'
import type { Model, ModelVersion, SchemaField } from '@/types'

const route = useRoute()

const modelId = computed(() => route.params.modelId as string)
const versionId = computed(() => route.params.versionId as string)

const loading = ref(false)
const model = ref<Model | null>(null)
const version = ref<ModelVersion | null>(null)
const schemaFields = ref<SchemaField[]>([])

const editingFieldId = ref<string | null>(null)
const editThreshold = ref<number | null>(null)
const savingThreshold = ref(false)
const thresholdsChanged = ref(false)
const rerunning = ref(false)

function startEditThreshold(field: SchemaField) {
  editingFieldId.value = field.id
  editThreshold.value = field.alert_threshold
}

function cancelEditThreshold() {
  editingFieldId.value = null
  editThreshold.value = null
}

async function saveThreshold(field: SchemaField) {
  savingThreshold.value = true
  try {
    await modelsApi.updateFieldThreshold(
      modelId.value,
      versionId.value,
      field.id,
      editThreshold.value,
    )
    // Update local field
    const existing = schemaFields.value.find(f => f.id === field.id)
    if (existing) {
      existing.alert_threshold = editThreshold.value
    }
    thresholdsChanged.value = true
    editingFieldId.value = null
    editThreshold.value = null
  } catch (error) {
    console.error('Failed to update threshold:', error)
  } finally {
    savingThreshold.value = false
  }
}

async function rerunJobs() {
  rerunning.value = true
  try {
    await jobsApi.triggerAllForVersion(modelId.value, versionId.value)
    // Reload version data
    const [modelData, versionData] = await Promise.all([
      modelsApi.get(modelId.value),
      modelsApi.getVersion(modelId.value, versionId.value),
    ])
    model.value = modelData
    version.value = versionData
    schemaFields.value = versionData.schema_fields
    thresholdsChanged.value = false
  } catch (error) {
    console.error('Failed to re-run jobs:', error)
  } finally {
    rerunning.value = false
  }
}

async function loadData() {
  loading.value = true
  try {
    const [modelData, versionData] = await Promise.all([
      modelsApi.get(modelId.value),
      modelsApi.getVersion(modelId.value, versionId.value),
    ])
    model.value = modelData
    version.value = versionData
    schemaFields.value = versionData.schema_fields
  } catch (error) {
    console.error('Failed to load schema data:', error)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <div>
    <!-- Loading State -->
    <div v-if="loading" class="d-flex justify-center align-center" style="min-height: 400px">
      <div class="text-center">
        <v-progress-circular :size="60" :width="4" indeterminate color="primary" />
        <p class="text-body-1 text-medium-emphasis mt-4">Loading schema...</p>
      </div>
    </div>

    <div v-else>
      <!-- Breadcrumbs -->
      <div v-if="model && version" class="compact-header mb-2">
        <v-breadcrumbs
          :items="[
            { title: 'Models', to: '/models' },
            { title: model.name, to: `/models/${modelId}` },
            { title: version.version, disabled: true },
          ]"
          density="compact"
          class="pa-0"
        />
      </div>

      <!-- Version Navigation Tabs -->
      <VersionNavTabs
        :model-id="modelId"
        :version-id="versionId"
      />

      <!-- Re-run banner -->
      <v-alert
        v-if="thresholdsChanged"
        type="info"
        variant="tonal"
        color="teal"
        class="mb-4 rerun-alert"
        prominent
      >
        <div class="d-flex align-center justify-space-between flex-wrap ga-3">
          <div>
            <div class="font-weight-bold">Thresholds updated</div>
            <div class="text-body-2">Re-run all jobs with new thresholds to see updated drift results.</div>
          </div>
          <v-btn
            color="teal"
            variant="flat"
            :loading="rerunning"
            prepend-icon="mdi-refresh"
            @click="rerunJobs"
          >
            Re-run All Jobs
          </v-btn>
        </div>
      </v-alert>

      <!-- Schema Fields Table -->
      <v-card class="schema-card" variant="flat">
        <v-card-title class="d-flex align-center pa-4">
          <v-icon start color="teal">mdi-file-tree</v-icon>
          <span class="font-weight-bold">Schema Fields</span>
          <v-spacer />
          <v-chip size="small" variant="tonal" color="teal">
            {{ schemaFields.length }} fields
          </v-chip>
        </v-card-title>
        <v-divider />
        <v-card-text class="pa-0">
          <v-table density="comfortable" class="schema-table">
            <thead>
              <tr>
                <th>Field Name</th>
                <th>Direction</th>
                <th>Data Type</th>
                <th>Drift Metric</th>
                <th>Alert Threshold</th>
                <th class="text-center">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="field in schemaFields" :key="field.id">
                <td>
                  <span class="field-name">{{ field.field_name }}</span>
                </td>
                <td>
                  <v-chip
                    size="small"
                    variant="flat"
                    :color="field.direction === 'input' ? 'primary' : 'secondary'"
                  >
                    {{ field.direction }}
                  </v-chip>
                </td>
                <td>
                  <v-chip size="small" variant="outlined" color="teal">
                    {{ field.data_type }}
                  </v-chip>
                </td>
                <td>
                  <span :class="field.drift_metric ? '' : 'text-medium-emphasis'">
                    {{ field.drift_metric || 'auto' }}
                  </span>
                </td>
                <td>
                  <template v-if="editingFieldId === field.id">
                    <div class="d-flex align-center ga-2">
                      <v-text-field
                        v-model.number="editThreshold"
                        type="number"
                        step="0.01"
                        min="0"
                        max="1"
                        variant="outlined"
                        density="compact"
                        hide-details
                        style="max-width: 120px"
                        autofocus
                        @keyup.enter="saveThreshold(field)"
                        @keyup.escape="cancelEditThreshold"
                      />
                      <v-btn
                        icon="mdi-check"
                        size="x-small"
                        color="teal"
                        variant="flat"
                        :loading="savingThreshold"
                        @click="saveThreshold(field)"
                      />
                      <v-btn
                        icon="mdi-close"
                        size="x-small"
                        variant="text"
                        @click="cancelEditThreshold"
                      />
                    </div>
                  </template>
                  <template v-else>
                    <span :class="field.alert_threshold != null ? '' : 'text-medium-emphasis'">
                      {{ field.alert_threshold != null ? field.alert_threshold : 'default' }}
                    </span>
                  </template>
                </td>
                <td class="text-center">
                  <v-btn
                    v-if="editingFieldId !== field.id"
                    icon="mdi-pencil-outline"
                    size="x-small"
                    variant="text"
                    color="teal"
                    @click="startEditThreshold(field)"
                  />
                </td>
              </tr>
            </tbody>
          </v-table>

          <!-- Empty state -->
          <div v-if="schemaFields.length === 0" class="text-center pa-12">
            <v-icon size="60" color="teal" style="opacity: 0.3">mdi-file-tree</v-icon>
            <h3 class="text-h6 mt-4 mb-2">No Schema Fields</h3>
            <p class="text-body-2 text-medium-emphasis">
              This version does not have any schema fields defined.
            </p>
          </div>
        </v-card-text>
      </v-card>
    </div>
  </div>
</template>

<style scoped>
.compact-header {
  padding: 4px 0;
}

.schema-card {
  border: 1px solid rgba(13, 148, 136, 0.1);
  border-radius: 16px;
}

.rerun-alert {
  border-radius: 16px;
}

.schema-table th {
  font-weight: 600 !important;
  text-transform: uppercase;
  font-size: 0.7rem !important;
  letter-spacing: 0.5px;
  background: rgba(13, 148, 136, 0.03);
}

.field-name {
  font-weight: 600;
  font-size: 0.95rem;
}

/* Dark mode adjustments */
:deep(.v-theme--dark) .schema-card {
  border-color: rgba(13, 148, 136, 0.2);
}

:deep(.v-theme--dark) .schema-table th {
  color: rgba(255, 255, 255, 0.5) !important;
  background: rgba(13, 148, 136, 0.06);
}
</style>
