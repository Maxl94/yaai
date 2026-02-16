<script setup lang="ts">
import type { NumericalStatistics, CategoricalStatistics } from '@/types'

defineProps<{
  statistics: NumericalStatistics | CategoricalStatistics
  dataType: string
}>()

function isNumerical(
  stats: NumericalStatistics | CategoricalStatistics
): stats is NumericalStatistics {
  return 'mean' in stats
}
</script>

<template>
  <div class="stats-grid">
    <template v-if="isNumerical(statistics)">
      <div class="stat-item">
        <span class="stat-label">Mean</span>
        <span class="stat-value">{{ statistics.mean.toFixed(2) }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">Median</span>
        <span class="stat-value">{{ statistics.median.toFixed(2) }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">Std</span>
        <span class="stat-value">{{ statistics.std.toFixed(2) }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">Min</span>
        <span class="stat-value">{{ statistics.min.toFixed(2) }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">Max</span>
        <span class="stat-value">{{ statistics.max.toFixed(2) }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">Count</span>
        <span class="stat-value">{{ statistics.count }}</span>
      </div>
    </template>
    <template v-else>
      <div class="stat-item">
        <span class="stat-label">Unique</span>
        <span class="stat-value">{{ statistics.unique_count }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">Total</span>
        <span class="stat-value">{{ statistics.total_count }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">Top</span>
        <span class="stat-value">{{ statistics.top_category || '–' }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">Nulls</span>
        <span class="stat-value">{{ statistics.null_count }}</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  font-size: 12px;
}

.stat-item {
  display: flex;
  flex-direction: column;
}

.stat-label {
  color: rgb(var(--v-theme-on-surface-variant));
  font-size: 10px;
  text-transform: uppercase;
}

.stat-value {
  font-weight: 500;
}
</style>
