<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { modelsApi } from '@/api/models'
import { dashboardApi } from '@/api/dashboard'
import OverlaidHistogram from '@/components/OverlaidHistogram.vue'
import GroupedBarChart from '@/components/GroupedBarChart.vue'
import StatsSummary from '@/components/StatsSummary.vue'
import VersionNavTabs from '@/components/VersionNavTabs.vue'
import type { Model, ModelVersion, ComparisonPanel, HistogramData, CategoricalData } from '@/types'

const route = useRoute()

const modelId = computed(() => route.params.modelId as string)
const versionId = computed(() => route.params.versionId as string)

const model = ref<Model | null>(null)
const version = ref<ModelVersion | null>(null)
const panels = ref<ComparisonPanel[]>([])
const loading = ref(true)

// Comparison mode
const mode = ref<'time_window' | 'vs_reference'>('time_window')

watch(mode, () => {
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

async function fetchComparison() {
  loading.value = true
  try {
    const params = mode.value === 'time_window'
      ? {
          mode: 'time_window' as const,
          from_a: periodA.value.from,
          to_a: periodA.value.to,
          from_b: periodB.value.from,
          to_b: periodB.value.to,
        }
      : {
          mode: 'vs_reference' as const,
          from_a: periodA.value.from,
          to_a: periodA.value.to,
        }

    const data = await dashboardApi.getComparison(modelId.value, versionId.value, params)
    panels.value = data.panels
  } catch (error) {
    console.error('Failed to fetch comparison:', error)
  } finally {
    loading.value = false
  }
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
        <v-btn-toggle v-model="mode" mandatory color="primary" class="mb-4" density="comfortable">
          <v-btn value="time_window">Time Window</v-btn>
          <v-btn value="vs_reference">vs Reference</v-btn>
        </v-btn-toggle>

        <div class="mb-4" v-if="mode === 'time_window'">
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

        <v-row>
          <v-col cols="12" md="6">
            <h4 class="text-subtitle-2 mb-2">Period A (Current)</h4>
            <div class="d-flex gap-2">
              <v-text-field v-model="periodA.from" type="date" label="From" variant="outlined" density="compact" />
              <v-text-field v-model="periodA.to" type="date" label="To" variant="outlined" density="compact" />
            </div>
          </v-col>
          <v-col v-if="mode === 'time_window'" cols="12" md="6">
            <h4 class="text-subtitle-2 mb-2">Period B (Baseline)</h4>
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

    <v-row v-else>
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
                label-a="Period A"
                :label-b="mode === 'vs_reference' ? 'Reference' : 'Period B'"
              />
            </template>
            <template v-else>
              <GroupedBarChart
                :data-a="panel.data_a"
                :data-b="panel.data_b as CategoricalData"
                :field-name="panel.field_name"
                label-a="Period A"
                :label-b="mode === 'vs_reference' ? 'Reference' : 'Period B'"
              />
            </template>

            <v-row class="mt-2">
              <v-col cols="6">
                <div class="text-caption text-grey mb-1">Period A</div>
                <StatsSummary :statistics="panel.data_a.statistics" :data-type="panel.data_type" />
              </v-col>
              <v-col cols="6">
                <div class="text-caption text-grey mb-1">{{ mode === 'vs_reference' ? 'Reference' : 'Period B' }}</div>
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
