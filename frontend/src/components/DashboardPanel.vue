<script setup lang="ts">
import HistogramChart from './HistogramChart.vue'
import BarChart from './BarChart.vue'
import StatsSummary from './StatsSummary.vue'
import type { DashboardPanel, HistogramData, CategoricalData } from '@/types'

defineProps<{
  panel: DashboardPanel
}>()

function isHistogramData(data: HistogramData | CategoricalData): data is HistogramData {
  return 'buckets' in data
}

function getDriftStatus(panel: DashboardPanel): { color: string; icon: string; label: string } {
  if (!panel.latest_drift) {
    return { color: 'grey-lighten-1', icon: 'mdi-minus-circle-outline', label: 'No Data' }
  }
  return panel.latest_drift.is_drifted 
    ? { color: 'warning', icon: 'mdi-alert-circle', label: 'Drift Detected' }
    : { color: 'success', icon: 'mdi-check-circle', label: 'Healthy' }
}
</script>

<template>
  <v-card class="panel-card h-100" variant="flat">
    <!-- Header -->
    <div class="panel-header">
      <div class="d-flex align-center">
        <v-icon 
          size="20" 
          :color="panel.direction === 'input' ? 'primary' : 'secondary'"
          class="mr-2"
        >
          {{ panel.direction === 'input' ? 'mdi-arrow-right-bold-box' : 'mdi-arrow-left-bold-box' }}
        </v-icon>
        <span class="field-name">{{ panel.field_name }}</span>
        <v-chip
          size="x-small"
          :color="panel.direction === 'input' ? 'primary' : 'secondary'"
          variant="tonal"
          class="ml-2"
        >
          {{ panel.direction }}
        </v-chip>
      </div>
      <v-spacer />
      <v-tooltip v-if="panel.latest_drift" location="top">
        <template #activator="{ props: tooltipProps }">
          <v-chip
            v-bind="tooltipProps"
            size="small"
            :color="getDriftStatus(panel).color"
            variant="flat"
            :prepend-icon="getDriftStatus(panel).icon"
            class="drift-chip"
          >
            {{ panel.latest_drift.metric_value.toFixed(3) }}
          </v-chip>
        </template>
        <div class="text-center">
          <div class="font-weight-bold">{{ panel.latest_drift.metric_name }}</div>
          <div>{{ getDriftStatus(panel).label }}</div>
        </div>
      </v-tooltip>
      <v-chip 
        v-else 
        size="small" 
        color="grey-lighten-1" 
        variant="tonal"
        prepend-icon="mdi-minus-circle-outline"
      >
        No drift data
      </v-chip>
    </div>

    <!-- Chart Area -->
    <v-card-text class="chart-area">
      <template v-if="isHistogramData(panel.data)">
        <div v-if="panel.data.buckets.length > 0" class="chart-container">
          <HistogramChart
            :data="panel.data"
            :field-name="panel.field_name"
          />
        </div>
        <div v-else class="empty-chart">
          <v-icon size="40" color="grey-lighten-2">mdi-chart-bar</v-icon>
          <span class="text-body-2 text-medium-emphasis mt-2">No data available</span>
        </div>
        <StatsSummary :statistics="panel.data.statistics" data-type="numerical" class="mt-3" />
      </template>
      <template v-else>
        <div v-if="panel.data.categories.length > 0" class="chart-container">
          <BarChart
            :data="panel.data"
            :field-name="panel.field_name"
          />
        </div>
        <div v-else class="empty-chart">
          <v-icon size="40" color="grey-lighten-2">mdi-chart-pie</v-icon>
          <span class="text-body-2 text-medium-emphasis mt-2">No data available</span>
        </div>
        <StatsSummary :statistics="panel.data.statistics" data-type="categorical" class="mt-3" />
      </template>
    </v-card-text>
  </v-card>
</template>

<style scoped>
.panel-card {
  border: 1px solid rgba(13, 148, 136, 0.1);
  border-radius: 16px;
  overflow: hidden;
  transition: all 0.3s ease;
}

.panel-card:hover {
  border-color: rgba(13, 148, 136, 0.2);
}

.panel-header {
  display: flex;
  align-items: center;
  padding: 16px 20px;
  background: linear-gradient(135deg, rgba(13, 148, 136, 0.03) 0%, rgba(20, 184, 166, 0.03) 100%);
  border-bottom: 1px solid rgba(13, 148, 136, 0.08);
}

.field-name {
  font-weight: 600;
  font-size: 0.95rem;
}

.drift-chip {
  font-weight: 600;
}

.chart-area {
  padding: 20px;
}

.chart-container {
  min-height: 180px;
}

.empty-chart {
  min-height: 180px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.02);
  border-radius: 12px;
}

/* Dark mode adjustments */
:deep(.v-theme--dark) .panel-card {
  border-color: rgba(13, 148, 136, 0.2);
}

:deep(.v-theme--dark) .panel-header {
  background: linear-gradient(135deg, rgba(13, 148, 136, 0.1) 0%, rgba(20, 184, 166, 0.1) 100%);
}

:deep(.v-theme--dark) .empty-chart {
  background: rgba(255, 255, 255, 0.02);
}
</style>
