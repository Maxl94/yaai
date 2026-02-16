<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { jobsApi } from '@/api/jobs'
import { modelsApi } from '@/api/models'
import VersionNavTabs from '@/components/VersionNavTabs.vue'
import type { JobConfig, Model, ModelVersion } from '@/types'

interface JobHistoryItem {
  id: string
  status: string
  drifts_detected: number
  run_at: string
}

const route = useRoute()

const modelId = computed(() => route.params.modelId as string | undefined)
const versionId = computed(() => route.params.versionId as string | undefined)
const hasRouteParams = computed(() => !!modelId.value && !!versionId.value)

const model = ref<Model | null>(null)
const version = ref<ModelVersion | null>(null)

const loading = ref(false)
const saving = ref(false)
const loadingHistory = ref(false)
const triggeringJob = ref<string | null>(null)
const backfillingJob = ref<string | null>(null)
const jobs = ref<JobConfig[]>([])
const jobHistory = ref<JobHistoryItem[]>([])

const showEditDialog = ref(false)
const showHistoryDialog = ref(false)
const selectedJob = ref<JobConfig | null>(null)

const editFormRef = ref()
const editFormValid = ref(false)

// Schedule presets
const schedulePresets = [
  { label: 'Hourly', value: '0 * * * *', description: 'Runs every hour at minute 0' },
  { label: 'Every 6h', value: '0 */6 * * *', description: 'Runs every 6 hours' },
  { label: 'Daily', value: '0 2 * * *', description: 'Runs daily at 2:00 AM' },
  { label: 'Weekly', value: '0 2 * * 1', description: 'Runs every Monday at 2:00 AM' },
  { label: 'Custom', value: 'custom', description: 'Enter a custom cron expression' },
]

const editSelectedPreset = ref('0 2 * * *')

const editScheduleDescription = computed(() => {
  if (editSelectedPreset.value === 'custom') {
    return `Cron: ${editJob.value.schedule}`
  }
  const preset = schedulePresets.find(p => p.value === editSelectedPreset.value)
  return preset?.description || ''
})

const editJob = ref({
  name: '',
  schedule: '0 2 * * *',
  comparison_type: 'vs_reference' as 'vs_reference' | 'rolling_window',
  window_size: '7d',
  min_samples: 200,
  is_active: true,
})

const comparisonTypeOptions = [
  { title: 'vs Reference Data', value: 'vs_reference' },
  { title: 'Rolling Window', value: 'rolling_window' },
]

const activeJobsCount = computed(() => jobs.value.filter(j => j.is_active).length)
const inactiveJobsCount = computed(() => jobs.value.filter(j => !j.is_active).length)

const headers = [
  { title: 'Job', key: 'name' },
  { title: 'Status', key: 'is_active', width: '120px' },
  { title: 'Schedule', key: 'schedule', width: '160px' },
  { title: 'Actions', key: 'actions', sortable: false, width: '180px' },
]

const historyHeaders = [
  { title: 'Status', key: 'status' },
  { title: 'Drifts', key: 'drifts' },
  { title: 'Run At', key: 'run_at' },
]

function describeSchedule(cron: string): string {
  const map: Record<string, string> = {
    '0 * * * *': 'Hourly',
    '0 */6 * * *': 'Every 6h',
    '0 2 * * *': 'Daily 2am',
    '0 0 * * *': 'Daily midnight',
    '0 2 * * 1': 'Weekly Mon',
  }
  return map[cron] || cron
}

async function loadJobs() {
  loading.value = true
  try {
    if (hasRouteParams.value) {
      jobs.value = await jobsApi.listForVersion(modelId.value!, versionId.value!)
    } else {
      jobs.value = await jobsApi.list()
    }
  } catch (error) {
    console.error('Failed to load jobs:', error)
  } finally {
    loading.value = false
  }
}

function openEditDialog(job: JobConfig) {
  selectedJob.value = job
  editJob.value = {
    name: job.name,
    schedule: job.schedule,
    comparison_type: job.comparison_type as 'vs_reference' | 'rolling_window',
    window_size: job.window_size || '7d',
    min_samples: job.min_samples ?? 200,
    is_active: job.is_active,
  }
  // Set schedule preset
  const matchingPreset = schedulePresets.find(p => p.value === job.schedule)
  editSelectedPreset.value = matchingPreset ? matchingPreset.value : 'custom'
  showEditDialog.value = true
}

async function saveJob() {
  if (!editFormValid.value || !selectedJob.value) return
  saving.value = true
  try {
    await jobsApi.update(selectedJob.value.id, {
      name: editJob.value.name,
      schedule: editJob.value.schedule,
      comparison_type: editJob.value.comparison_type,
      window_size: editJob.value.window_size,
      min_samples: editJob.value.min_samples,
      is_active: editJob.value.is_active,
    })
    showEditDialog.value = false
    await loadJobs()
  } catch (error) {
    console.error('Failed to update job:', error)
  } finally {
    saving.value = false
  }
}

async function toggleJobActive(job: JobConfig) {
  const newState = !job.is_active
  try {
    await jobsApi.update(job.id, { is_active: newState })
    job.is_active = newState
  } catch (error) {
    console.error('Failed to update job:', error)
  }
}

async function triggerJob(job: JobConfig) {
  triggeringJob.value = job.id
  try {
    await jobsApi.trigger(job.id)
    await loadJobs()
  } catch (error) {
    console.error('Failed to trigger job:', error)
  } finally {
    triggeringJob.value = null
  }
}

async function backfillJob(job: JobConfig) {
  backfillingJob.value = job.id
  try {
    await jobsApi.backfill(job.id)
    await loadJobs()
  } catch (error) {
    console.error('Failed to backfill job:', error)
  } finally {
    backfillingJob.value = null
  }
}

async function showJobHistory(job: JobConfig) {
  selectedJob.value = job
  showHistoryDialog.value = true
  loadingHistory.value = true
  try {
    jobHistory.value = await jobsApi.getHistory(job.id)
  } catch (error) {
    console.error('Failed to load job history:', error)
    jobHistory.value = []
  } finally {
    loadingHistory.value = false
  }
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleString()
}

async function loadModelVersion() {
  if (!modelId.value || !versionId.value) return
  try {
    const [modelData, versionData] = await Promise.all([
      modelsApi.get(modelId.value),
      modelsApi.getVersion(modelId.value, versionId.value),
    ])
    model.value = modelData
    version.value = versionData
  } catch (error) {
    console.error('Failed to load model/version:', error)
  }
}

onMounted(() => {
  loadJobs()
  if (hasRouteParams.value) {
    loadModelVersion()
  }
})
</script>

<template>
  <div>
    <!-- Compact Breadcrumb Header (when navigated via model/version route) -->
    <div v-if="hasRouteParams && model && version" class="compact-header mb-2">
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
      v-if="hasRouteParams"
      :model-id="modelId!"
      :version-id="versionId!"
    />

    <!-- Action Bar -->
    <div class="d-flex align-center flex-wrap ga-3 mb-4">
      <v-chip-group>
        <v-chip size="small" variant="tonal" color="teal">
          {{ jobs.length }} total
        </v-chip>
        <v-chip size="small" variant="tonal" color="success">
          {{ activeJobsCount }} active
        </v-chip>
        <v-chip size="small" variant="tonal" color="grey">
          {{ inactiveJobsCount }} paused
        </v-chip>
      </v-chip-group>
    </div>

    <!-- Jobs List -->
    <v-card class="jobs-card" variant="flat">
      <v-card-text class="pa-0">
        <v-data-table
          :headers="headers"
          :items="jobs"
          :loading="loading"
          hover
          class="jobs-table"
        >
          <template #item.name="{ item }">
            <div class="d-flex align-center py-2">
              <v-avatar size="36" color="teal" variant="tonal" class="mr-3">
                <v-icon size="20">mdi-clock-check</v-icon>
              </v-avatar>
              <div>
                <div class="font-weight-medium">{{ item.name }}</div>
                <div class="text-caption text-medium-emphasis">
                  {{ item.comparison_type === 'vs_reference' ? 'vs Reference' : 'Rolling Window' }}
                  <span v-if="item.window_size"> &middot; {{ item.window_size }}</span>
                </div>
              </div>
            </div>
          </template>
          <template #item.is_active="{ item }">
            <v-chip
              :color="item.is_active ? 'success' : 'grey'"
              size="small"
              variant="flat"
              @click="toggleJobActive(item)"
              style="cursor: pointer"
            >
              <v-icon start size="14">
                {{ item.is_active ? 'mdi-check-circle' : 'mdi-pause-circle' }}
              </v-icon>
              {{ item.is_active ? 'Active' : 'Paused' }}
            </v-chip>
          </template>
          <template #item.schedule="{ item }">
            <v-chip size="small" variant="tonal" color="teal">
              <v-icon start size="14">mdi-timer-outline</v-icon>
              {{ describeSchedule(item.schedule) }}
            </v-chip>
          </template>
          <template #item.actions="{ item }">
            <div class="d-flex ga-1">
              <v-btn
                icon
                size="small"
                variant="tonal"
                color="teal"
                @click="openEditDialog(item)"
              >
                <v-icon size="18">mdi-pencil</v-icon>
                <v-tooltip activator="parent" location="top">Edit</v-tooltip>
              </v-btn>
              <v-btn
                icon
                size="small"
                variant="tonal"
                color="teal"
                :loading="triggeringJob === item.id"
                @click="triggerJob(item)"
              >
                <v-icon size="18">mdi-play</v-icon>
                <v-tooltip activator="parent" location="top">Run Now</v-tooltip>
              </v-btn>
              <v-btn
                icon
                size="small"
                variant="tonal"
                color="warning"
                :loading="backfillingJob === item.id"
                @click="backfillJob(item)"
              >
                <v-icon size="18">mdi-database-clock</v-icon>
                <v-tooltip activator="parent" location="top">Backfill</v-tooltip>
              </v-btn>
              <v-btn
                icon
                size="small"
                variant="tonal"
                color="info"
                @click="showJobHistory(item)"
              >
                <v-icon size="18">mdi-history</v-icon>
                <v-tooltip activator="parent" location="top">View History</v-tooltip>
              </v-btn>
            </div>
          </template>

          <!-- Empty state -->
          <template #no-data>
            <div class="text-center pa-8">
              <v-icon size="64" color="teal" style="opacity: 0.3">mdi-calendar-blank</v-icon>
              <h3 class="text-h6 mt-4 mb-2">No Jobs</h3>
              <p class="text-body-2 text-medium-emphasis mb-4">
                Jobs are automatically created when a model version is deployed.
              </p>
            </div>
          </template>
        </v-data-table>
      </v-card-text>
    </v-card>

    <!-- Edit Job Dialog -->
    <v-dialog v-model="showEditDialog" max-width="600">
      <v-card class="edit-dialog">
        <v-card-title class="d-flex align-center pa-4" style="background: rgba(13, 148, 136, 1); color: white;">
          <v-icon start color="white">mdi-pencil</v-icon>
          <span class="font-weight-bold">Edit Drift Detection Job</span>
        </v-card-title>
        <v-card-text class="pa-6">
          <v-form ref="editFormRef" v-model="editFormValid">
            <v-text-field
              v-model="editJob.name"
              label="Job Name"
              variant="outlined"
              prepend-inner-icon="mdi-label"
              :rules="[v => !!v || 'Name is required']"
              class="mb-2"
            />

            <!-- Schedule Presets -->
            <div class="mb-4">
              <label class="text-body-2 font-weight-medium text-medium-emphasis d-block mb-2">Schedule</label>
              <v-btn-toggle
                v-model="editSelectedPreset"
                mandatory
                color="teal"
                variant="outlined"
                density="comfortable"
                divided
                class="schedule-toggle"
                @update:model-value="(val: string) => { if (val !== 'custom') editJob.schedule = val }"
              >
                <v-btn v-for="preset in schedulePresets" :key="preset.value" :value="preset.value" size="small">
                  {{ preset.label }}
                </v-btn>
              </v-btn-toggle>
              <div class="text-caption text-medium-emphasis mt-1">
                <v-icon size="12" class="mr-1">mdi-information-outline</v-icon>
                {{ editScheduleDescription }}
              </div>
              <!-- Custom cron input -->
              <v-text-field
                v-if="editSelectedPreset === 'custom'"
                v-model="editJob.schedule"
                label="Cron Expression"
                variant="outlined"
                density="compact"
                prepend-inner-icon="mdi-timer"
                placeholder="0 0 * * *"
                hint="Standard 5-field cron: minute hour day month weekday"
                persistent-hint
                :rules="[v => !!v || 'Schedule is required']"
                class="mt-3"
              />
            </div>

            <v-row>
              <v-col cols="12" sm="6">
                <v-select
                  v-model="editJob.comparison_type"
                  :items="comparisonTypeOptions"
                  item-title="title"
                  item-value="value"
                  label="Comparison Type"
                  variant="outlined"
                  prepend-inner-icon="mdi-compare"
                  :rules="[v => !!v || 'Comparison type is required']"
                />
              </v-col>
              <v-col cols="12" sm="6">
                <v-text-field
                  v-model="editJob.window_size"
                  label="Window Size"
                  variant="outlined"
                  prepend-inner-icon="mdi-calendar-range"
                  placeholder="7d"
                  hint="e.g., '7d' = 7 days, '24h' = 24 hours"
                  persistent-hint
                  :rules="[v => !!v || 'Window size is required']"
                />
              </v-col>
            </v-row>

            <v-row>
              <v-col cols="12" sm="6">
                <v-text-field
                  v-model.number="editJob.min_samples"
                  label="Min Samples"
                  type="number"
                  variant="outlined"
                  prepend-inner-icon="mdi-numeric"
                  hint="Minimum inference samples required to run drift detection"
                  persistent-hint
                  :rules="[v => v > 0 || 'Must be greater than 0']"
                />
              </v-col>
              <v-col cols="12" sm="6" class="d-flex align-center">
                <v-switch
                  v-model="editJob.is_active"
                  :label="editJob.is_active ? 'Active' : 'Paused'"
                  color="teal"
                  hide-details
                />
              </v-col>
            </v-row>
          </v-form>
        </v-card-text>
        <v-divider />
        <v-card-actions class="pa-4">
          <v-spacer />
          <v-btn variant="text" @click="showEditDialog = false">Cancel</v-btn>
          <v-btn
            color="teal"
            variant="flat"
            :loading="saving"
            :disabled="!editFormValid"
            @click="saveJob"
          >
            <v-icon start>mdi-content-save</v-icon>
            Save
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Job History Dialog -->
    <v-dialog v-model="showHistoryDialog" max-width="800">
      <v-card class="history-dialog">
        <v-card-title class="d-flex align-center pa-4 bg-info">
          <v-icon start color="white">mdi-history</v-icon>
          <span class="text-white font-weight-bold">Job History: {{ selectedJob?.name }}</span>
        </v-card-title>
        <v-card-text class="pa-0">
          <v-data-table
            :headers="historyHeaders"
            :items="jobHistory"
            :loading="loadingHistory"
            hover
            class="history-table"
          >
            <template #item.status="{ item }">
              <v-chip
                :color="item.status === 'completed' ? 'success' : item.status === 'failed' ? 'error' : 'warning'"
                size="small"
                variant="flat"
                :prepend-icon="item.status === 'completed' ? 'mdi-check' : item.status === 'failed' ? 'mdi-close' : 'mdi-clock'"
              >
                {{ item.status }}
              </v-chip>
            </template>
            <template #item.drifts="{ item }">
              <v-chip
                v-if="item.drifts_detected > 0"
                color="warning"
                size="small"
                variant="flat"
                prepend-icon="mdi-alert"
              >
                {{ item.drifts_detected }} drifts
              </v-chip>
              <v-chip v-else color="success" size="small" variant="tonal" prepend-icon="mdi-check">
                No drift
              </v-chip>
            </template>
            <template #item.run_at="{ item }">
              <div class="d-flex align-center">
                <v-icon size="14" class="mr-1" color="grey">mdi-clock-outline</v-icon>
                {{ formatDate(item.run_at) }}
              </div>
            </template>
          </v-data-table>
        </v-card-text>
        <v-divider />
        <v-card-actions class="pa-4">
          <v-spacer />
          <v-btn variant="flat" color="info" @click="showHistoryDialog = false">Close</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<style scoped>
.compact-header {
  padding: 4px 0;
}

.jobs-card {
  border: 1px solid rgba(13, 148, 136, 0.1);
  border-radius: 16px;
  overflow: hidden;
}

.jobs-table {
  border-radius: 0;
}

.jobs-table :deep(thead th) {
  font-weight: 600 !important;
  text-transform: uppercase;
  font-size: 0.7rem !important;
  letter-spacing: 0.5px;
  background: rgba(13, 148, 136, 0.03);
}

.schedule-toggle {
  width: 100%;
}

.schedule-toggle .v-btn {
  flex: 1;
}

.edit-dialog,
.history-dialog {
  border-radius: 16px !important;
  overflow: hidden;
}

.history-table :deep(thead th) {
  font-weight: 600 !important;
  text-transform: uppercase;
  font-size: 0.7rem !important;
  letter-spacing: 0.5px;
}

/* Dark mode adjustments */
:deep(.v-theme--dark) .jobs-card {
  border-color: rgba(13, 148, 136, 0.2);
}

:deep(.v-theme--dark) .jobs-table thead th {
  background: rgba(13, 148, 136, 0.1);
}

:deep(.v-theme--dark) .compact-header {
  border-bottom-color: rgba(13, 148, 136, 0.2);
}
</style>
