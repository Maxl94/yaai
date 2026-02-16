<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const props = defineProps<{
  modelId: string
  versionId: string
}>()

const route = useRoute()

const tabs = computed(() => [
  { title: 'Dashboard', icon: 'mdi-view-dashboard-outline', routeName: 'dashboard',
    to: `/models/${props.modelId}/versions/${props.versionId}/dashboard` },
  { title: 'Compare', icon: 'mdi-compare', routeName: 'comparison',
    to: `/models/${props.modelId}/versions/${props.versionId}/compare` },
  { title: 'Drift', icon: 'mdi-chart-timeline-variant-shimmer', routeName: 'version-drift-results',
    to: `/models/${props.modelId}/versions/${props.versionId}/drift` },
  { title: 'Jobs', icon: 'mdi-timer-sync-outline', routeName: 'version-jobs',
    to: `/models/${props.modelId}/versions/${props.versionId}/jobs` },
  { title: 'Schema', icon: 'mdi-file-tree', routeName: 'version-schema',
    to: `/models/${props.modelId}/versions/${props.versionId}/schema` },
])

const activeTab = computed(() => {
  const idx = tabs.value.findIndex(t => t.routeName === route.name)
  return idx >= 0 ? idx : 0
})
</script>

<template>
  <div class="version-nav mb-4">
    <v-tabs
      :model-value="activeTab"
      color="primary"
      density="comfortable"
    >
      <v-tab
        v-for="tab in tabs"
        :key="tab.routeName"
        :to="tab.to"
        :prepend-icon="tab.icon"
        class="nav-tab"
      >
        {{ tab.title }}
      </v-tab>
    </v-tabs>
  </div>
</template>

<style scoped>
.version-nav {
  border-bottom: 1px solid rgba(13, 148, 136, 0.15);
}

.nav-tab {
  text-transform: none !important;
  letter-spacing: 0 !important;
  font-weight: 500;
}
</style>
