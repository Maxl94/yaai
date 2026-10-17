<script setup lang="ts">
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { modelsApi } from '@/api/models'
import { dashboardApi } from '@/api/dashboard'
import OverlaidHistogram from '@/components/OverlaidHistogram.vue'
import GroupedBarChart from '@/components/GroupedBarChart.vue'
import StatsSummary from '@/components/StatsSummary.vue'
import VersionNavTabs from '@/components/VersionNavTabs.vue'
import type { Model, ModelVersion, ComparisonPanel, HistogramData, CategoricalData, SchemaDiffItem } from '@/types'

const route = useRoute()

const modelId = computed(() => route.params.modelId as string)
const versionId = computed(() => route.params.versionId as string)

const model = ref<Model | null>(null)
const version = ref<ModelVersion | null>(null)
const panels = ref<ComparisonPanel[]>([])
const schemaDiff = ref<SchemaDiffItem[]>([])
const loading = ref(true)
const logScale = ref(false)

// Comparison mode
const mode = ref<'time_window' | 'vs_reference' | 'vs_version'>('time_window')

// Other version (vs_version mode)
const allModels = ref<Model[]>([])
const otherModelId = ref<string | null>(null)
const otherVersions = ref<ModelVersion[]>([])
const otherVersionId = ref<string | null>(null)

// Returns false when a newer model selection superseded this one.
async function selectOtherModel(id: string): Promise<boolean> {
  otherModelId.value = id
  otherVersionId.value = null
  let versions: ModelVersion[] = []
  try {
    versions = await modelsApi.listVersions(id)
  } catch (error) {
    console.error('Failed to fetch versions:', error)
  }
  if (otherModelId.value !== id) return false
  otherVersions.value = versions
  const fallback = otherVersions.value.find((v) => v.id !== versionId.value)
    ?? otherVersions.value.find((v) => v.id === versionId.value)
  otherVersionId.value = fallback?.id ?? null
  return true
}

async function onOtherModelChange(id: string) {
  if (!(await selectOtherModel(id))) return
  fetchComparison()
}

function onOtherVersionChange(id: string) {
  otherVersionId.value = id
  fetchComparison()
}

// Time-window baseline, restored when leaving vs_version
let savedPeriodB: { from: string; to: string } | null = null

watch(mode, async (newMode, oldMode) => {
  if (oldMode === 'vs_version' && savedPeriodB) {
    periodB.value = savedPeriodB
    savedPeriodB = null
  }
  if (newMode === 'vs_version') {
    savedPeriodB = { ...periodB.value }
    periodB.value = { ...periodA.value }
    try {
      if (!allModels.value.length) allModels.value = await modelsApi.listAll()
    } catch (error) {
      console.error('Failed to fetch models:', error)
    }
    if (!otherModelId.value) await selectOtherModel(modelId.value)
  }
  // Let the period watcher run first so fetchComparison cancels its debounce timer
  await nextTick()
  fetchComparison()
})

// Date ranges
const periodA = ref({
  from: getDefaultDate(-7),
  to: getDefaultDate(0),
})
const periodB = ref({
  from: getDefaultDate(-14),
  to: getDefaultDate(-7),
})

function getDefaultDate(daysOffset: number): string {
  const date = new Date()
  date.setDate(date.getDate() + daysOffset)
  return date.toISOString().split('T')[0] || ''
}

// Debounced auto-fetch on date changes
let debounceTimer: number | null = null
function debouncedFetch() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = window.setTimeout(() => {
    fetchComparison()
  }, 600)
}

watch(
  [() => periodA.value.from, () => periodA.value.to, () => periodB.value.from, () => periodB.value.to],
  () => { debouncedFetch() }
)

// Presets
const presets = [
  { label: 'Today vs Yesterday', periodA: { from: -1, to: 0 }, periodB: { from: -2, to: -1 } },
  { label: 'This Week vs Last Week', periodA: { from: -7, to: 0 }, periodB: { from: -14, to: -7 } },
  { label: 'This Month vs Last Month', periodA: { from: -30, to: 0 }, periodB: { from: -60, to: -30 } },
]

function applyPreset(preset: typeof presets[0]) {
  periodA.value.from = getDefaultDate(preset.periodA.from)
  periodA.value.to = getDefaultDate(preset.periodA.to)
  periodB.value.from = getDefaultDate(preset.periodB.from)
  periodB.value.to = getDefaultDate(preset.periodB.to)
}

async function fetchModel() {
  try {
    const [modelData, versionData] = await Promise.all([
      modelsApi.get(modelId.value),
      modelsApi.getVersion(modelId.value, versionId.value),
    ])
    model.value = modelData
    version.value = versionData
  } catch (error) {
    console.error('Failed to fetch model:', error)
  }
}

let latestRequestId = 0

async function fetchComparison() {
  if (debounceTimer) clearTimeout(debounceTimer)
  const requestId = ++latestRequestId
  if (mode.value === 'vs_version' && (!otherModelId.value || !otherVersionId.value)) {
    panels.value = []
    schemaDiff.value = []
    loading.value = false
    return
  }
  loading.value = true
  try {
    const periodAParams = { from_a: periodA.value.from, to_a: periodA.value.to }
    const periodBParams = { from_b: periodB.value.from, to_b: periodB.value.to }
    const params = mode.value === 'time_window'
      ? { mode: 'time_window' as const, ...periodAParams, ...periodBParams }
      : mode.value === 'vs_version'
        ? {
            mode: 'vs_version' as const,
            ...periodAParams,
            ...periodBParams,
            other_model_id: otherModelId.value!,
            other_version_id: otherVersionId.value!,
          }
        : { mode: 'vs_reference' as const, ...periodAParams }

    const data = await dashboardApi.getComparison(modelId.value, versionId.value, params)
    if (requestId !== latestRequestId) return
    panels.value = data.panels
    schemaDiff.value = data.schema_diff
  } catch (error) {
    console.error('Failed to fetch comparison:', error)
    if (requestId !== latestRequestId) return
    panels.value = []
    schemaDiff.value = []
  } finally {
    if (requestId === latestRequestId) loading.value = false
  }
}

function versionLabel(m: { name: string } | null | undefined, v: { version: string } | null | undefined): string {
  return v ? `${m ? m.name + ' ' : ''}${v.version}` : ''
}

const labelA = computed(() =>
  mode.value === 'vs_version' ? versionLabel(null, version.value) : 'Period A',
)
const labelB = computed(() => {
  if (mode.value === 'vs_reference') return 'Reference'
  if (mode.value !== 'vs_version') return 'Period B'
  const otherModel = allModels.value.find((m) => m.id === otherModelId.value)
  const otherVersion = otherVersions.value.find((v) => v.id === otherVersionId.value)
  return versionLabel(otherModelId.value === modelId.value ? null : otherModel, otherVersion) || 'Other version'
})

function diffReason(item: SchemaDiffItem): string {
  if (item.status === 'only_in_a') return `only in ${labelA.value}`
  if (item.status === 'only_in_b') return `only in ${labelB.value}`
  return `type changed: ${item.data_type_a} → ${item.data_type_b}`
}

function isHistogramData(data: HistogramData | CategoricalData): data is HistogramData {
  return 'buckets' in data
}

function getDriftColor(panel: ComparisonPanel): string {
  if (!panel.drift_score) return 'grey'
  return panel.drift_score.is_drifted ? 'warning' : 'success'
}

onMounted(async () => {
  await fetchModel()
  await fetchComparison()
})
</script>

<template>
  <div v-if="model && version">
    <!-- Compact Header -->
    <div class="compact-header mb-2">
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
    <VersionNavTabs :model-id="modelId" :version-id="versionId" />

    <!-- Controls -->
    <v-card class="mb-4 controls-card" variant="flat">
      <v-card-text>
        <div class="d-flex align-center flex-wrap ga-4 mb-4">
          <v-btn-toggle v-model="mode" mandatory color="primary" density="comfortable">
            <v-btn value="time_window">Time Window</v-btn>
            <v-btn value="vs_reference">vs Reference</v-btn>
            <v-btn value="vs_version">Other version</v-btn>
          </v-btn-toggle>
          <v-switch v-model="logScale" label="Log scale" color="primary" density="compact" hide-details />
        </div>

        <div class="mb-4" v-if="mode !== 'vs_reference'">
          <span class="text-subtitle-2 mr-2">Presets:</span>
          <v-btn
            v-for="preset in presets"
            :key="preset.label"
            variant="outlined"
            size="small"
            class="mr-2"
            @click="applyPreset(preset)"
          >
            {{ preset.label }}
          </v-btn>
        </div>

        <v-row v-if="mode === 'vs_version'">
          <v-col cols="12" md="6">
            <v-select
              :model-value="otherModelId"
              :items="allModels"
              item-title="name"
              item-value="id"
              label="Model"
              variant="outlined"
              density="compact"
              hide-details
              @update:model-value="onOtherModelChange"
            />
          </v-col>
          <v-col cols="12" md="6">
            <v-select
              :model-value="otherVersionId"
              :items="otherVersions"
              item-title="version"
              item-value="id"
              label="Version"
              variant="outlined"
              density="compact"
              hide-details
              @update:model-value="onOtherVersionChange"
            />
          </v-col>
        </v-row>

        <v-row>
          <v-col cols="12" md="6">
            <h4 class="text-subtitle-2 mb-2">
              {{ mode === 'vs_version' ? `Period A (${labelA})` : 'Period A (Current)' }}
            </h4>
            <div class="d-flex gap-2">
              <v-text-field v-model="periodA.from" type="date" label="From" variant="outlined" density="compact" />
              <v-text-field v-model="periodA.to" type="date" label="To" variant="outlined" density="compact" />
            </div>
          </v-col>
          <v-col v-if="mode !== 'vs_reference'" cols="12" md="6">
            <h4 class="text-subtitle-2 mb-2">
              {{ mode === 'vs_version' ? `Period B (${labelB})` : 'Period B (Baseline)' }}
            </h4>
            <div class="d-flex gap-2">
              <v-text-field v-model="periodB.from" type="date" label="From" variant="outlined" density="compact" />
              <v-text-field v-model="periodB.to" type="date" label="To" variant="outlined" density="compact" />
            </div>
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>

    <!-- Comparison Panels -->
    <v-progress-linear v-if="loading" indeterminate color="primary" class="mb-4" />

    <v-alert v-if="!loading && schemaDiff.length" type="warning" variant="tonal" density="compact" class="mb-4" title="Fields not compared">
      <p class="text-caption mb-1">
        These fields are not comparable between the two versions. Renamed fields appear as removed + added.
      </p>
      <ul class="pl-4">
        <li v-for="item in schemaDiff" :key="`${item.direction}-${item.field_name}`">
          <strong>{{ item.field_name }}</strong> ({{ item.direction }}): {{ diffReason(item) }}
        </li>
      </ul>
    </v-alert>

    <v-row v-if="!loading">
      <v-col v-for="panel in panels" :key="panel.field_name" cols="12" md="6">
        <v-card>
          <v-card-title class="d-flex align-center text-body-1">
            {{ panel.field_name }}
            <v-chip size="x-small" :color="panel.direction === 'input' ? 'primary' : 'secondary'" class="ml-2">
              {{ panel.direction }}
            </v-chip>
            <v-spacer />
            <v-chip
              v-if="panel.drift_score"
              size="small"
              :color="getDriftColor(panel)"
              :prepend-icon="panel.drift_score.is_drifted ? 'mdi-alert' : 'mdi-check-circle'"
            >
              {{ panel.drift_score.metric_name }}: {{ panel.drift_score.metric_value.toFixed(3) }}
            </v-chip>
          </v-card-title>

          <v-card-text>
            <template v-if="isHistogramData(panel.data_a)">
              <OverlaidHistogram
                :data-a="panel.data_a"
                :data-b="panel.data_b as HistogramData"
                :field-name="panel.field_name"
                :log-scale="logScale"
                :label-a="labelA"
                :label-b="labelB"
              />
            </template>
            <template v-else>
              <GroupedBarChart
                :data-a="panel.data_a"
                :data-b="panel.data_b as CategoricalData"
                :field-name="panel.field_name"
                :log-scale="logScale"
                :label-a="labelA"
                :label-b="labelB"
              />
            </template>

            <v-row class="mt-2">
              <v-col cols="6">
                <div class="text-caption text-grey mb-1">{{ labelA }}</div>
                <StatsSummary :statistics="panel.data_a.statistics" :data-type="panel.data_type" />
              </v-col>
              <v-col cols="6">
                <div class="text-caption text-grey mb-1">{{ labelB }}</div>
                <StatsSummary :statistics="panel.data_b.statistics" :data-type="panel.data_type" />
              </v-col>
            </v-row>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-alert v-if="!loading && panels.length === 0" type="info" variant="tonal">
      No data available for the selected time ranges.
    </v-alert>
  </div>

  <v-progress-linear v-else indeterminate color="primary" />
</template>

<style scoped>
.compact-header {
  padding: 4px 0;
}

.controls-card {
  border: 1px solid rgba(13, 148, 136, 0.1);
  border-radius: 16px;
}
</style>
