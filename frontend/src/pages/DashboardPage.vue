<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { modelsApi } from '@/api/models'
import { dashboardApi } from '@/api/dashboard'
import DashboardPanel from '@/components/DashboardPanel.vue'
import InferenceVolumeChart from '@/components/InferenceVolumeChart.vue'
import VersionNavTabs from '@/components/VersionNavTabs.vue'
import type { Model, ModelVersion, DashboardPanel as DashboardPanelType, InferenceVolumeBucket } from '@/types'

const route = useRoute()

const modelId = computed(() => route.params.modelId as string)
const versionId = computed(() => route.params.versionId as string)

const model = ref<Model | null>(null)
const version = ref<ModelVersion | null>(null)
const panels = ref<DashboardPanelType[]>([])
const volumeData = ref<InferenceVolumeBucket[]>([])
const loading = ref(true)

// Filters
const activeTab = ref<'all' | 'input' | 'output'>('all')
const dateRange = ref<[string, string] | null>(null)

// Date range picker
const showDateMenu = ref(false)
const dateFrom = ref('')
const dateTo = ref('')

const dateRangeLabel = computed(() => {
  if (!dateFrom.value && !dateTo.value) return 'All time'
  if (dateFrom.value && dateTo.value) return `${dateFrom.value} — ${dateTo.value}`
  if (dateFrom.value) return `From ${dateFrom.value}`
  return `Until ${dateTo.value}`
})

function applyDateRange() {
  if (dateFrom.value || dateTo.value) {
    dateRange.value = [dateFrom.value || '', dateTo.value || '']
  } else {
    dateRange.value = null
  }
  showDateMenu.value = false
}

function clearDateRange() {
  dateFrom.value = ''
  dateTo.value = ''
  dateRange.value = null
  showDateMenu.value = false
}

const filteredPanels = computed(() => {
  if (activeTab.value === 'all') return panels.value
  return panels.value.filter((p) => p.direction === activeTab.value)
})

const inputPanels = computed(() => panels.value.filter((p) => p.direction === 'input'))
const outputPanels = computed(() => panels.value.filter((p) => p.direction === 'output'))

async function fetchData() {
  loading.value = true
  try {
    const [modelData, versionData, dashboardData, volume] = await Promise.all([
      modelsApi.get(modelId.value),
      modelsApi.getVersion(modelId.value, versionId.value),
      dashboardApi.getDashboard(modelId.value, versionId.value, {
        from: dateRange.value?.[0],
        to: dateRange.value?.[1],
      }),
      modelsApi.getInferenceVolume(modelId.value, versionId.value),
    ])
    model.value = modelData
    version.value = versionData
    panels.value = dashboardData.panels
    volumeData.value = volume
  } catch (error) {
    console.error('Failed to fetch dashboard data:', error)
  } finally {
    loading.value = false
  }
}

onMounted(fetchData)

watch([dateRange], fetchData)
</script>

<template>
  <!-- Loading State -->
  <div v-if="loading" class="d-flex justify-center align-center" style="min-height: 400px">
    <div class="text-center">
      <v-progress-circular
        :size="60"
        :width="4"
        indeterminate
        color="primary"
      />
      <p class="text-body-1 text-medium-emphasis mt-4">Loading dashboard...</p>
    </div>
  </div>

  <div v-else-if="model && version">
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

    <!-- Request Volume Chart -->
    <v-card v-if="volumeData.length > 0" class="mb-6 volume-card" variant="flat">
      <v-card-title class="d-flex align-center pa-4">
        <v-icon start color="teal">mdi-chart-bar</v-icon>
        <span class="font-weight-bold">Request Volume</span>
        <v-spacer />
        <v-chip size="small" variant="tonal" color="teal">
          {{ volumeData.reduce((sum, d) => sum + d.count, 0).toLocaleString() }} total
        </v-chip>
      </v-card-title>
      <v-divider />
      <v-card-text class="pa-4">
        <InferenceVolumeChart :data="volumeData" :height="200" />
      </v-card-text>
    </v-card>

    <!-- Filters Card -->
    <v-card class="mb-6 filter-card" variant="flat">
      <v-card-text class="d-flex align-center flex-wrap ga-4 py-3">
        <v-btn-toggle
          v-model="activeTab"
          mandatory
          color="primary"
          variant="outlined"
          divided
          density="comfortable"
        >
          <v-btn value="all" size="small">
            <v-icon start size="small">mdi-view-grid</v-icon>
            All ({{ panels.length }})
          </v-btn>
          <v-btn value="input" size="small">
            <v-icon start size="small">mdi-arrow-right-bold</v-icon>
            Inputs ({{ inputPanels.length }})
          </v-btn>
          <v-btn value="output" size="small">
            <v-icon start size="small">mdi-arrow-left-bold</v-icon>
            Outputs ({{ outputPanels.length }})
          </v-btn>
        </v-btn-toggle>

        <v-spacer />

        <v-menu v-model="showDateMenu" :close-on-content-click="false" location="bottom end">
          <template #activator="{ props: menuProps }">
            <v-btn
              v-bind="menuProps"
              variant="outlined"
              density="comfortable"
              prepend-icon="mdi-calendar-range"
              class="date-picker-btn"
            >
              {{ dateRangeLabel }}
              <v-icon v-if="dateRange" end size="small" @click.stop="clearDateRange">mdi-close-circle</v-icon>
            </v-btn>
          </template>
          <v-card min-width="300">
            <v-card-text>
              <v-text-field
                v-model="dateFrom"
                type="date"
                label="From"
                variant="outlined"
                density="compact"
                hide-details
                class="mb-3"
              />
              <v-text-field
                v-model="dateTo"
                type="date"
                label="To"
                variant="outlined"
                density="compact"
                hide-details
              />
            </v-card-text>
            <v-card-actions>
              <v-btn variant="text" size="small" @click="clearDateRange">Clear</v-btn>
              <v-spacer />
              <v-btn color="primary" variant="flat" size="small" @click="applyDateRange">Apply</v-btn>
            </v-card-actions>
          </v-card>
        </v-menu>
      </v-card-text>
    </v-card>

    <!-- Panels Grid -->
    <v-row>
      <v-col
        v-for="(panel, index) in filteredPanels"
        :key="panel.field_name"
        cols="12"
        sm="6"
        lg="4"
        :style="{ animationDelay: `${index * 50}ms` }"
        class="panel-col"
      >
        <DashboardPanel :panel="panel" class="panel-card" />
      </v-col>
    </v-row>

    <!-- Empty State -->
    <v-card
      v-if="filteredPanels.length === 0"
      variant="flat"
      class="empty-state text-center pa-8"
    >
      <v-icon size="80" color="primary" class="mb-4" style="opacity: 0.3">
        mdi-chart-box-outline
      </v-icon>
      <h3 class="text-h6 mb-2">No Panels Available</h3>
      <p class="text-body-2 text-medium-emphasis mb-4">
        No data panels match your current filters. Try adjusting the filter or ingest some data first.
      </p>
      <v-btn
        v-if="activeTab !== 'all'"
        variant="outlined"
        color="primary"
        @click="activeTab = 'all'"
      >
        Show All Panels
      </v-btn>
    </v-card>
  </div>

  <!-- Error State -->
  <v-card v-else variant="flat" class="error-state text-center pa-8">
    <v-icon size="80" color="error" class="mb-4" style="opacity: 0.5">
      mdi-alert-circle-outline
    </v-icon>
    <h3 class="text-h6 mb-2">Failed to Load Dashboard</h3>
    <p class="text-body-2 text-medium-emphasis mb-4">
      There was an error loading the dashboard data. Please try again.
    </p>
    <v-btn variant="flat" color="primary" @click="fetchData">
      <v-icon start>mdi-refresh</v-icon>
      Retry
    </v-btn>
  </v-card>
</template>

<style scoped>
.compact-header {
  padding: 4px 0;
}

.filter-card,
.volume-card {
  border: 1px solid rgba(13, 148, 136, 0.1);
  border-radius: 16px;
}

.date-picker-btn {
  text-transform: none !important;
}

.panel-col {
  animation: fadeInUp 0.5s ease forwards;
  opacity: 0;
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.panel-card {
  height: 100%;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}

.panel-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 40px rgba(13, 148, 136, 0.15);
}

.empty-state,
.error-state {
  border-radius: 16px;
  border: 2px dashed rgba(13, 148, 136, 0.2);
}
</style>
