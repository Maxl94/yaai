<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { modelsApi } from '@/api/models'
import { jobsApi } from '@/api/jobs'
import type { Model, ModelVersion, DriftResult, SchemaField, DriftOverviewItem } from '@/types'
import DriftTimelineChart from '@/components/DriftTimelineChart.vue'
import VersionNavTabs from '@/components/VersionNavTabs.vue'

const route = useRoute()

// Route params (when navigating from model/version page)
const modelId = computed(() => route.params.modelId as string | undefined)
const versionId = computed(() => route.params.versionId as string | undefined)
const hasRouteParams = computed(() => !!modelId.value && !!versionId.value)

const loading = ref(false)
const selectedField = ref<string | null>(null)
const driftResults = ref<DriftResult[]>([])
const driftThreshold = ref(0.1)

// Model and version details when using route params
const model = ref<Model | null>(null)
const version = ref<ModelVersion | null>(null)

// Schema fields from the loaded version
const schemaFields = ref<SchemaField[]>([])

// Threshold editing state
const editingThresholdField = ref<string | null>(null)
const editThresholdValue = ref<number | null>(null)
const savingThreshold = ref(false)
const thresholdsChanged = ref(false)
const rerunning = ref(false)

// Global overview state
const overviewItems = ref<DriftOverviewItem[]>([])
const overviewPage = ref(1)
const overviewTotal = ref(0)
const overviewTotalPages = computed(() => Math.ceil(overviewTotal.value / 10))

// Computed: map field_name -> SchemaField for quick lookup
const fieldSchemaMap = computed(() => {
  const map: Record<string, SchemaField> = {}
  for (const sf of schemaFields.value) {
    map[sf.field_name] = sf
  }
  return map
})

const availableFields = computed(() => {
  const fields = new Set<string>()
  driftResults.value.forEach(r => fields.add(r.field_name))
  return Array.from(fields).sort()
})

const filteredResults = computed(() => {
  if (!selectedField.value) return driftResults.value
  return driftResults.value.filter(r => r.field_name === selectedField.value)
})

const driftCount = computed(() => {
  return driftResults.value.filter(r => r.is_drifted).length
})

const healthPercentage = computed(() => {
  if (driftResults.value.length === 0) return 100
  return Math.round(((driftResults.value.length - driftCount.value) / driftResults.value.length) * 100)
})

function getFieldResults(fieldName: string): DriftResult[] {
  return driftResults.value
    .filter(r => r.field_name === fieldName)
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
}

function getFieldDriftStatus(fieldName: string): boolean {
  const fieldResults = getFieldResults(fieldName)
  const latestResult = fieldResults[0]
  return !!latestResult && latestResult.is_drifted
}

function getFieldLatestScore(fieldName: string): number {
  const results = getFieldResults(fieldName)
  return results[0]?.score ?? 0
}

function getFieldAvgScore(fieldName: string): number {
  const results = getFieldResults(fieldName)
  if (results.length === 0) return 0
  return results.reduce((sum, r) => sum + r.score, 0) / results.length
}

function getFieldMaxScore(fieldName: string): number {
  const results = getFieldResults(fieldName)
  if (results.length === 0) return 0
  return Math.max(...results.map(r => r.score))
}

// Threshold editing

function startEditingThreshold(fieldName: string) {
  editingThresholdField.value = fieldName
  const sf = fieldSchemaMap.value[fieldName]
  editThresholdValue.value = sf?.alert_threshold ?? null
}

function cancelEditingThreshold() {
  editingThresholdField.value = null
  editThresholdValue.value = null
}

async function saveThreshold(fieldName: string) {
  const mId = modelId.value
  const vId = versionId.value
  const sf = fieldSchemaMap.value[fieldName]
  if (!mId || !vId || !sf) return

  savingThreshold.value = true
  try {
    await modelsApi.updateFieldThreshold(mId, vId, sf.id, editThresholdValue.value)
    sf.alert_threshold = editThresholdValue.value
    thresholdsChanged.value = true
    cancelEditingThreshold()
  } catch (error) {
    console.error('Failed to update threshold:', error)
  } finally {
    savingThreshold.value = false
  }
}

// Re-run jobs

async function rerunAllJobs() {
  const mId = modelId.value
  const vId = versionId.value
  if (!mId || !vId) return

  rerunning.value = true
  try {
    await jobsApi.triggerAllForVersion(mId, vId)
    thresholdsChanged.value = false
    setTimeout(async () => {
      await loadDriftResults()
      rerunning.value = false
    }, 2000)
  } catch (error) {
    console.error('Failed to re-run jobs:', error)
    rerunning.value = false
  }
}

// Data loading

async function loadDriftResults() {
  const mId = modelId.value
  const vId = versionId.value
  if (!mId || !vId) return

  loading.value = true
  try {
    driftResults.value = await modelsApi.getDriftResults(mId, vId)
  } catch (error) {
    console.error('Failed to load drift results:', error)
  } finally {
    loading.value = false
  }
}

async function loadFromRouteParams() {
  if (!modelId.value || !versionId.value) return

  loading.value = true
  try {
    const [modelData, versionData, results] = await Promise.all([
      modelsApi.get(modelId.value),
      modelsApi.getVersion(modelId.value, versionId.value),
      modelsApi.getDriftResults(modelId.value, versionId.value),
    ])
    model.value = modelData
    version.value = versionData
    driftResults.value = results
    schemaFields.value = versionData.schema_fields ?? []

    const firstResult = results[0]
    if (firstResult) {
      driftThreshold.value = firstResult.threshold
    }
  } catch (error) {
    console.error('Failed to load drift data:', error)
  } finally {
    loading.value = false
  }
}

async function loadOverview() {
  loading.value = true
  try {
    const response = await jobsApi.getDriftOverview(overviewPage.value, 10)
    overviewItems.value = response.data
    overviewTotal.value = response.meta.total
  } catch (error) {
    console.error('Failed to load drift overview:', error)
  } finally {
    loading.value = false
  }
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function getOverviewLatestScore(item: DriftOverviewItem): number | null {
  if (item.results.length === 0) return null
  const sorted = [...item.results].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  )
  return sorted[0]!.score
}

function getOverviewAvgScore(item: DriftOverviewItem): number {
  if (item.results.length === 0) return 0
  return item.results.reduce((sum, r) => sum + r.score, 0) / item.results.length
}

function getOverviewMaxScore(item: DriftOverviewItem): number {
  if (item.results.length === 0) return 0
  return Math.max(...item.results.map(r => r.score))
}

function formatRelativeDate(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

onMounted(() => {
  if (hasRouteParams.value) {
    loadFromRouteParams()
  } else {
    loadOverview()
  }
})

// Watch for route changes (handles component reuse between /drift and /models/.../drift)
watch([modelId, versionId], () => {
  if (hasRouteParams.value) {
    thresholdsChanged.value = false
    loadFromRouteParams()
  } else {
    driftResults.value = []
    model.value = null
    version.value = null
    loadOverview()
  }
})

// Watch overview page changes
watch(overviewPage, () => {
  if (!hasRouteParams.value) {
    loadOverview()
  }
})
</script>

<template>
  <div>
    <!-- Loading State -->
    <div v-if="loading" class="d-flex justify-center align-center" style="min-height: 400px">
      <div class="text-center">
        <v-progress-circular :size="60" :width="4" indeterminate color="primary" />
        <p class="text-body-1 text-medium-emphasis mt-4">Analyzing drift data...</p>
      </div>
    </div>

    <div v-else>
      <!-- Version-Specific View -->
      <template v-if="hasRouteParams">
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

        <VersionNavTabs
          :model-id="modelId!"
          :version-id="versionId!"
        />

        <!-- Results Section -->
        <div v-if="driftResults.length > 0">
          <!-- Re-run Banner -->
          <v-alert
            v-if="thresholdsChanged"
            type="info"
            variant="tonal"
            color="teal"
            class="mb-4 rerun-banner"
            prominent
            closable
            @click:close="thresholdsChanged = false"
          >
            <div class="d-flex align-center justify-space-between flex-wrap ga-3" style="width: 100%">
              <div>
                <div class="font-weight-bold">Thresholds Updated</div>
                <div class="text-body-2">
                  Field thresholds have been changed. Re-run all drift jobs to recalculate results with the new thresholds.
                </div>
              </div>
              <v-btn
                color="teal"
                variant="flat"
                :loading="rerunning"
                prepend-icon="mdi-refresh"
                @click="rerunAllJobs"
              >
                Re-run all jobs
              </v-btn>
            </div>
          </v-alert>

          <!-- Field Filter + Stats Chips -->
          <v-card class="mb-4 filter-card" variant="flat">
            <v-card-text class="d-flex align-center flex-wrap ga-4 py-3">
              <v-select
                v-model="selectedField"
                :items="availableFields"
                label="Filter by Field"
                clearable
                variant="outlined"
                density="compact"
                hide-details
                prepend-inner-icon="mdi-filter-variant"
                style="max-width: 300px"
                bg-color="surface"
              />
              <v-spacer />
              <v-chip-group>
                <v-chip size="small" variant="tonal" color="teal">
                  <v-icon start size="small">mdi-clipboard-check-outline</v-icon>
                  {{ driftResults.length }} Checks
                </v-chip>
                <v-chip
                  size="small"
                  variant="tonal"
                  :color="driftCount === 0 ? 'success' : 'warning'"
                  :prepend-icon="driftCount === 0 ? 'mdi-check-circle' : 'mdi-alert-circle'"
                >
                  {{ driftCount === 0 ? 'All Healthy' : `${driftCount} Drifts` }}
                </v-chip>
                <v-chip size="small" variant="tonal" color="teal">
                  <v-icon start size="small">mdi-format-list-bulleted</v-icon>
                  {{ availableFields.length }} Fields
                </v-chip>
                <v-chip
                  size="small"
                  variant="tonal"
                  :color="healthPercentage >= 80 ? 'success' : healthPercentage >= 50 ? 'warning' : 'error'"
                >
                  <v-icon start size="small">mdi-heart-pulse</v-icon>
                  {{ healthPercentage }}% Health
                </v-chip>
              </v-chip-group>
            </v-card-text>
          </v-card>

          <!-- Timeline Chart -->
          <v-card class="mb-6 chart-card" variant="flat">
            <v-card-text class="pa-4">
              <DriftTimelineChart
                :results="filteredResults"
                :threshold="driftThreshold"
                :height="600"
              />
            </v-card-text>
          </v-card>

          <!-- Results by Field -->
          <v-card class="results-card" variant="flat">
            <v-card-title class="d-flex align-center pa-4">
              <v-icon start color="teal">mdi-view-list</v-icon>
              <span class="font-weight-bold">Detailed Results by Field</span>
            </v-card-title>
            <v-divider />
            <v-card-text class="pa-0">
              <v-expansion-panels variant="accordion" class="field-panels">
                <v-expansion-panel
                  v-for="field in availableFields"
                  :key="field"
                  class="field-panel"
                >
                  <v-expansion-panel-title class="px-4">
                    <div class="d-flex align-center" style="width: 100%">
                      <v-icon
                        size="20"
                        :color="getFieldDriftStatus(field) ? 'warning' : 'success'"
                        class="mr-3"
                      >
                        {{ getFieldDriftStatus(field) ? 'mdi-alert-circle' : 'mdi-check-circle' }}
                      </v-icon>
                      <span class="field-name">{{ field }}</span>

                      <!-- Inline Threshold Chip / Editor -->
                      <div class="ml-3 d-flex align-center" @click.stop>
                        <v-chip
                          v-if="editingThresholdField !== field"
                          size="small"
                          variant="outlined"
                          color="teal"
                          class="threshold-chip"
                          @click="startEditingThreshold(field)"
                        >
                          <v-icon start size="small">mdi-tune-vertical</v-icon>
                          {{
                            fieldSchemaMap[field]?.alert_threshold != null
                              ? fieldSchemaMap[field]!.alert_threshold!.toFixed(4)
                              : 'default'
                          }}
                        </v-chip>

                        <div v-else class="d-flex align-center ga-2 threshold-editor">
                          <v-text-field
                            v-model.number="editThresholdValue"
                            type="number"
                            step="0.01"
                            min="0"
                            max="1"
                            variant="outlined"
                            density="compact"
                            hide-details
                            placeholder="e.g. 0.1"
                            style="max-width: 120px"
                            autofocus
                            @keyup.enter="saveThreshold(field)"
                            @keyup.escape="cancelEditingThreshold"
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
                            color="grey"
                            variant="text"
                            @click="cancelEditingThreshold"
                          />
                        </div>
                      </div>

                      <v-spacer />
                      <span class="field-stats text-body-2 mr-3">
                        <span class="text-medium-emphasis">Latest:</span>
                        <strong :class="getFieldLatestScore(field) > driftThreshold ? 'text-warning' : 'text-success'">
                          {{ getFieldLatestScore(field).toFixed(4) }}
                        </strong>
                        <span class="text-medium-emphasis mx-1">|</span>
                        <span class="text-medium-emphasis">Avg:</span>
                        <strong class="text-medium-emphasis">{{ getFieldAvgScore(field).toFixed(4) }}</strong>
                        <span class="text-medium-emphasis mx-1">|</span>
                        <span class="text-medium-emphasis">Max:</span>
                        <strong :class="getFieldMaxScore(field) > driftThreshold ? 'text-warning' : 'text-success'">
                          {{ getFieldMaxScore(field).toFixed(4) }}
                        </strong>
                      </span>
                      <v-chip
                        :color="getFieldDriftStatus(field) ? 'warning' : 'success'"
                        size="small"
                        variant="tonal"
                        class="mr-3"
                      >
                        {{ getFieldDriftStatus(field) ? 'Drift' : 'Stable' }}
                      </v-chip>
                      <span class="text-body-2 text-medium-emphasis">
                        {{ getFieldResults(field).length }} checks
                      </span>
                    </div>
                  </v-expansion-panel-title>
                  <v-expansion-panel-text>
                    <v-table density="comfortable" class="results-table">
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>Metric</th>
                          <th>Score</th>
                          <th>Threshold</th>
                          <th>Samples</th>
                          <th class="text-center">Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr
                          v-for="result in getFieldResults(field)"
                          :key="result.id"
                          :class="{ 'drift-row': result.is_drifted }"
                        >
                          <td>
                            <div class="d-flex align-center">
                              <v-icon size="16" class="mr-2" color="grey">mdi-clock-outline</v-icon>
                              {{ formatDate(result.created_at) }}
                            </div>
                          </td>
                          <td>
                            <v-chip size="small" variant="outlined" color="teal">
                              {{ result.metric_name }}
                            </v-chip>
                          </td>
                          <td>
                            <span
                              class="score-value"
                              :class="result.is_drifted ? 'text-warning font-weight-bold' : 'text-success'"
                            >
                              {{ result.score.toFixed(4) }}
                            </span>
                          </td>
                          <td class="text-medium-emphasis">{{ result.threshold.toFixed(4) }}</td>
                          <td>
                            <span v-if="result.details?.window" class="text-body-2">
                              {{ result.details.window.sample_count }} samples
                              <v-tooltip v-if="result.details.window.window_extended" location="top">
                                <template #activator="{ props: tipProps }">
                                  <v-icon v-bind="tipProps" size="14" color="info" class="ml-1">mdi-information-outline</v-icon>
                                </template>
                                Window extended from {{ Math.round(result.details.window.configured_window_days) }}d
                                to {{ Math.round(result.details.window.actual_window_days) }}d
                                (min {{ result.details.window.min_samples }} samples)
                              </v-tooltip>
                            </span>
                            <span v-else class="text-medium-emphasis">-</span>
                          </td>
                          <td class="text-center">
                            <v-chip
                              :color="result.is_drifted ? 'warning' : 'success'"
                              size="small"
                              variant="flat"
                              :prepend-icon="result.is_drifted ? 'mdi-alert' : 'mdi-check'"
                            >
                              {{ result.is_drifted ? 'Drifted' : 'OK' }}
                            </v-chip>
                          </td>
                        </tr>
                      </tbody>
                    </v-table>
                  </v-expansion-panel-text>
                </v-expansion-panel>
              </v-expansion-panels>
            </v-card-text>
          </v-card>
        </div>

        <!-- Empty State (version-specific, no results) -->
        <v-card
          v-else
          class="empty-state text-center pa-12"
          variant="flat"
        >
          <v-icon size="80" color="teal" style="opacity: 0.3">mdi-chart-timeline-variant</v-icon>
          <h3 class="text-h5 mt-6 mb-2">No Drift Results Yet</h3>
          <p class="text-body-1 text-medium-emphasis mb-6" style="max-width: 400px; margin: 0 auto">
            Run a drift detection job to start monitoring data distribution changes.
          </p>
          <v-btn color="teal" variant="flat" to="/jobs">
            <v-icon start>mdi-plus</v-icon>
            Create Drift Job
          </v-btn>
        </v-card>
      </template>

      <!-- Global Overview -->
      <template v-else>
        <div class="d-flex align-center mb-6">
          <h2 class="text-h5 font-weight-bold">Drift Overview</h2>
        </div>

        <!-- Overview Cards -->
        <div v-if="overviewItems.length > 0">
          <v-card
            v-for="item in overviewItems"
            :key="item.model_id"
            class="mb-4 overview-card"
            variant="flat"
          >
            <!-- Header row: model name + version + action -->
            <div class="d-flex align-center px-4 pt-3 pb-2">
              <v-avatar size="32" color="teal" variant="tonal" class="mr-3">
                <v-icon size="18">mdi-cube</v-icon>
              </v-avatar>
              <h3 class="text-subtitle-1 font-weight-bold mr-3">{{ item.model_name }}</h3>
              <v-chip size="x-small" variant="tonal" color="teal">{{ item.version }}</v-chip>
              <v-spacer />
              <v-btn
                color="teal"
                variant="flat"
                size="small"
                :to="`/models/${item.model_id}/versions/${item.version_id}/drift`"
              >
                <v-icon start size="small">mdi-arrow-right</v-icon>
                Details
              </v-btn>
            </div>

            <!-- Stats row -->
            <div class="d-flex align-center flex-wrap ga-3 px-4 pb-2">
              <v-chip
                size="small"
                variant="tonal"
                :color="item.health_percentage >= 80 ? 'success' : item.health_percentage >= 50 ? 'warning' : 'error'"
              >
                <v-icon start size="small">mdi-heart-pulse</v-icon>
                {{ item.health_percentage }}%
              </v-chip>
              <v-chip
                size="small"
                variant="tonal"
                :color="item.drifted_fields > 0 ? 'warning' : 'success'"
              >
                <v-icon start size="small">{{ item.drifted_fields > 0 ? 'mdi-alert' : 'mdi-check-circle' }}</v-icon>
                {{ item.drifted_fields }}/{{ item.total_fields }} drifted
              </v-chip>
              <v-chip size="small" variant="outlined" color="teal">
                {{ item.total_inferences.toLocaleString() }} inferences
              </v-chip>
              <v-chip v-if="item.last_check" size="small" variant="outlined" color="grey">
                <v-icon start size="small">mdi-clock-outline</v-icon>
                {{ formatRelativeDate(item.last_check) }}
              </v-chip>
              <span
                v-if="getOverviewLatestScore(item) !== null"
                class="text-body-2 ml-auto"
              >
                Latest: <strong :class="getOverviewLatestScore(item)! > 0.1 ? 'text-warning' : 'text-success'">
                  {{ getOverviewLatestScore(item)!.toFixed(4) }}
                </strong>
                <span class="text-medium-emphasis mx-1">|</span>
                Avg: <strong class="text-medium-emphasis">{{ getOverviewAvgScore(item).toFixed(4) }}</strong>
                <span class="text-medium-emphasis mx-1">|</span>
                Max: <strong :class="getOverviewMaxScore(item) > 0.1 ? 'text-warning' : 'text-success'">
                  {{ getOverviewMaxScore(item).toFixed(4) }}
                </strong>
              </span>
            </div>

            <!-- Chart -->
            <div class="px-4 pb-4">
              <DriftTimelineChart
                v-if="item.results.length > 0"
                :results="item.results"
                :height="320"
              />
              <div
                v-else
                class="d-flex justify-center align-center text-medium-emphasis"
                style="height: 200px"
              >
                <div class="text-center">
                  <v-icon size="40" color="grey" style="opacity: 0.3">mdi-chart-line</v-icon>
                  <p class="text-caption mt-2">No drift data yet</p>
                </div>
              </div>
            </div>
          </v-card>

          <!-- Pagination -->
          <div v-if="overviewTotalPages > 1" class="d-flex justify-center mt-4">
            <v-pagination
              v-model="overviewPage"
              :length="overviewTotalPages"
              :total-visible="5"
              color="teal"
              density="comfortable"
            />
          </div>
        </div>

        <!-- Empty State (no models) -->
        <v-card
          v-else
          class="empty-state text-center pa-12"
          variant="flat"
        >
          <v-icon size="80" color="teal" style="opacity: 0.3">mdi-chart-timeline-variant-shimmer</v-icon>
          <h3 class="text-h5 mt-6 mb-2">No Models Found</h3>
          <p class="text-body-1 text-medium-emphasis" style="max-width: 400px; margin: 0 auto">
            Create a model and upload data to start monitoring for drift.
          </p>
          <v-btn color="teal" variant="flat" to="/models" class="mt-4">
            <v-icon start>mdi-cube-outline</v-icon>
            Go to Models
          </v-btn>
        </v-card>
      </template>
    </div>
  </div>
</template>

<style scoped>
.compact-header {
  padding: 4px 0;
}

.filter-card,
.chart-card,
.results-card {
  border: 1px solid rgba(13, 148, 136, 0.1);
  border-radius: 16px;
}

.overview-card {
  border: 1px solid rgba(13, 148, 136, 0.1);
  border-radius: 16px;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.overview-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(13, 148, 136, 0.12);
}

.field-panels {
  border-radius: 0;
}

.field-panel {
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
}

.field-panel:last-child {
  border-bottom: none;
}

.field-name {
  font-weight: 600;
  font-size: 0.95rem;
}

.field-stats {
  font-family: 'Monaco', 'Menlo', monospace;
  font-size: 0.8rem;
  white-space: nowrap;
}

.results-table th {
  font-weight: 600 !important;
  text-transform: uppercase;
  font-size: 0.7rem !important;
  letter-spacing: 0.5px;
  color: rgba(0, 0, 0, 0.5) !important;
}

.drift-row {
  background: rgba(255, 152, 0, 0.05);
}

.score-value {
  font-family: 'Monaco', 'Menlo', monospace;
  font-size: 0.9rem;
}

.empty-state {
  border-radius: 16px;
  border: 2px dashed rgba(13, 148, 136, 0.2);
}

.threshold-chip {
  cursor: pointer;
  font-family: 'Monaco', 'Menlo', monospace;
  font-size: 0.8rem;
}

.threshold-chip:hover {
  border-color: rgba(13, 148, 136, 0.6);
  background: rgba(13, 148, 136, 0.05);
}

.threshold-editor {
  min-width: 200px;
}

.rerun-banner {
  border-radius: 16px;
}

/* Dark mode adjustments */
:deep(.v-theme--dark) .filter-card,
:deep(.v-theme--dark) .chart-card,
:deep(.v-theme--dark) .results-card,
:deep(.v-theme--dark) .overview-card {
  border-color: rgba(13, 148, 136, 0.2);
}

:deep(.v-theme--dark) .field-panel {
  border-color: rgba(255, 255, 255, 0.05);
}

:deep(.v-theme--dark) .results-table th {
  color: rgba(255, 255, 255, 0.5) !important;
}

:deep(.v-theme--dark) .drift-row {
  background: rgba(255, 152, 0, 0.1);
}

:deep(.v-theme--dark) .threshold-chip:hover {
  background: rgba(13, 148, 136, 0.15);
}
</style>
