<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { modelsApi } from '@/api/models'
import type { Model } from '@/types'

const router = useRouter()
const models = ref<Model[]>([])
const loading = ref(true)
const search = ref('')
const showCreateDialog = ref(false)
const showDeleteDialog = ref(false)
const modelToDelete = ref<Model | null>(null)
const newModel = ref({ name: '', description: '' })
const creating = ref(false)

// Health status: 'healthy' | 'drifted' | 'loading' | null
const modelHealth = reactive<Record<string, 'healthy' | 'drifted' | 'loading' | null>>({})

const filteredModels = computed(() => {
  if (!search.value) return models.value
  const q = search.value.toLowerCase()
  return models.value.filter(m => 
    m.name.toLowerCase().includes(q) || 
    m.description?.toLowerCase().includes(q)
  )
})

async function fetchModels() {
  loading.value = true
  try {
    models.value = await modelsApi.list()
  } catch (error) {
    console.error('Failed to fetch models:', error)
  } finally {
    loading.value = false
  }
}

async function checkModelHealth(model: Model) {
  const activeVersion = model.active_version || model.versions?.find(v => v.is_active)
  if (!activeVersion) {
    modelHealth[model.id] = null
    return
  }
  modelHealth[model.id] = 'loading'
  try {
    const results = await modelsApi.getDriftResults(model.id, activeVersion.id)
    if (results.length === 0) {
      modelHealth[model.id] = null
      return
    }
    const hasDrift = results.some(r => r.is_drifted)
    modelHealth[model.id] = hasDrift ? 'drifted' : 'healthy'
  } catch {
    modelHealth[model.id] = null
  }
}

async function handleCreate() {
  if (!newModel.value.name) return
  creating.value = true
  try {
    const created = await modelsApi.create({
      name: newModel.value.name,
      description: newModel.value.description || undefined,
    })
    models.value.push(created)
    showCreateDialog.value = false
    newModel.value = { name: '', description: '' }
    router.push(`/models/${created.id}`)
  } catch (error) {
    console.error('Failed to create model:', error)
  } finally {
    creating.value = false
  }
}

async function handleDelete() {
  if (!modelToDelete.value) return
  try {
    await modelsApi.delete(modelToDelete.value.id)
    models.value = models.value.filter((m) => m.id !== modelToDelete.value!.id)
    showDeleteDialog.value = false
    modelToDelete.value = null
  } catch (error) {
    console.error('Failed to delete model:', error)
  }
}

function getActiveVersion(model: Model) {
  if (model.active_version) {
    return model.active_version.version
  }
  return model.versions?.find((v) => v.is_active)?.version || null
}

function getInferenceCount(model: Model) {
  const count = model.total_inferences ?? 0
  if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`
  if (count >= 1000) return `${(count / 1000).toFixed(1)}K`
  return count.toString()
}

onMounted(async () => {
  await fetchModels()
  // Fire background health checks for all models
  models.value.forEach(m => checkModelHealth(m))
})
</script>

<template>
  <div class="models-page">
    <!-- Page Header -->
    <div class="page-header">
      <div class="header-content">
        <h1 class="page-title">Models</h1>
        <p class="page-subtitle">Manage your ML models and monitor for data drift</p>
      </div>
      <v-btn
        color="primary"
        size="large"
        prepend-icon="mdi-plus"
        @click="showCreateDialog = true"
      >
        New Model
      </v-btn>
    </div>

    <!-- Search Bar -->
    <v-text-field
      v-model="search"
      placeholder="Search models..."
      prepend-inner-icon="mdi-magnify"
      clearable
      hide-details
      class="search-field mb-6"
      bg-color="surface-variant"
    />

    <!-- Loading State -->
    <div v-if="loading" class="loading-state">
      <v-progress-circular indeterminate color="primary" size="48" />
      <p class="mt-4 text-medium-emphasis">Loading models...</p>
    </div>

    <!-- Models Grid -->
    <v-row v-else-if="filteredModels.length > 0">
      <v-col 
        v-for="model in filteredModels" 
        :key="model.id" 
        cols="12" 
        sm="6" 
        md="4" 
        lg="3"
      >
        <v-card
          class="model-card h-100"
          @click="router.push(`/models/${model.id}`)"
        >
          <!-- Card Header with Icon -->
          <div class="card-header">
            <div class="model-icon-wrapper">
              <div class="model-icon">
                <v-icon size="24">mdi-cube-outline</v-icon>
              </div>
              <div
                v-if="modelHealth[model.id] === 'healthy' || modelHealth[model.id] === 'drifted'"
                class="health-dot"
                :class="modelHealth[model.id] === 'drifted' ? 'health-drifted' : 'health-healthy'"
              />
            </div>
            <v-btn
              icon="mdi-dots-vertical"
              size="small"
              variant="text"
              class="menu-btn"
              @click.stop
            >
              <v-icon>mdi-dots-vertical</v-icon>
              <v-menu activator="parent" location="bottom end">
                <v-list density="compact" rounded="lg">
                  <v-list-item
                    prepend-icon="mdi-pencil-outline"
                    title="Edit"
                    @click.stop="router.push(`/models/${model.id}`)"
                  />
                  <v-list-item
                    prepend-icon="mdi-delete-outline"
                    title="Delete"
                    base-color="error"
                    @click.stop="modelToDelete = model; showDeleteDialog = true"
                  />
                </v-list>
              </v-menu>
            </v-btn>
          </div>

          <!-- Card Content -->
          <v-card-text class="card-content">
            <h3 class="model-name">{{ model.name }}</h3>
            <p v-if="model.description" class="model-description">
              {{ model.description }}
            </p>
            <p v-else class="model-description text-disabled">
              No description
            </p>
          </v-card-text>

          <!-- Card Footer Stats -->
          <div class="card-footer">
            <div class="stat-item">
              <v-icon size="16" class="stat-icon">mdi-tag-outline</v-icon>
              <span v-if="getActiveVersion(model)" class="stat-value">
                {{ getActiveVersion(model) }}
              </span>
              <span v-else class="stat-value text-disabled">No version</span>
            </div>
            <div class="stat-item">
              <v-icon size="16" class="stat-icon">mdi-lightning-bolt</v-icon>
              <span class="stat-value">{{ getInferenceCount(model) }}</span>
            </div>
          </div>
        </v-card>
      </v-col>
    </v-row>

    <!-- Empty State -->
    <div v-else class="empty-state">
      <div class="empty-icon">
        <v-icon size="48" color="primary">mdi-cube-outline</v-icon>
      </div>
      <h3 class="empty-title">No models yet</h3>
      <p class="empty-description">
        Create your first model to start monitoring for data drift
      </p>
      <v-btn
        color="primary"
        prepend-icon="mdi-plus"
        @click="showCreateDialog = true"
      >
        Create Model
      </v-btn>
    </div>

    <!-- Create Dialog -->
    <v-dialog v-model="showCreateDialog" max-width="480">
      <v-card class="dialog-card">
        <v-card-title class="dialog-title">
          <v-icon start color="primary">mdi-cube-outline</v-icon>
          Create New Model
        </v-card-title>
        <v-card-text class="pt-4">
          <v-text-field
            v-model="newModel.name"
            label="Model Name"
            placeholder="e.g., fraud-detection-v2"
            autofocus
            class="mb-4"
          />
          <v-textarea
            v-model="newModel.description"
            label="Description"
            placeholder="Brief description of your model..."
            rows="3"
          />
        </v-card-text>
        <v-card-actions class="dialog-actions">
          <v-btn variant="text" @click="showCreateDialog = false">Cancel</v-btn>
          <v-btn
            color="primary"
            :loading="creating"
            :disabled="!newModel.name"
            @click="handleCreate"
          >
            Create Model
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Delete Dialog -->
    <v-dialog v-model="showDeleteDialog" max-width="400">
      <v-card class="dialog-card">
        <v-card-title class="dialog-title text-error">
          <v-icon start color="error">mdi-alert-circle-outline</v-icon>
          Delete Model
        </v-card-title>
        <v-card-text class="pt-4">
          Are you sure you want to delete <strong>{{ modelToDelete?.name }}</strong>? 
          This action cannot be undone and will remove all versions, inferences, and drift results.
        </v-card-text>
        <v-card-actions class="dialog-actions">
          <v-btn variant="text" @click="showDeleteDialog = false">Cancel</v-btn>
          <v-btn color="error" @click="handleDelete">Delete</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<style scoped>
.models-page {
  max-width: 1400px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 32px;
  gap: 16px;
  flex-wrap: wrap;
}

.page-title {
  font-size: 2rem;
  font-weight: 700;
  margin: 0;
  letter-spacing: -0.02em;
}

.page-subtitle {
  margin: 4px 0 0;
  color: rgb(var(--v-theme-on-surface-variant));
  font-size: 0.95rem;
}

.search-field {
  max-width: 400px;
}

.search-field :deep(.v-field) {
  border: none;
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
}

.model-card {
  cursor: pointer;
  transition: all 0.2s ease;
  border: 1px solid rgba(var(--v-border-color), 0.08);
  background: rgb(var(--v-theme-surface));
}

.model-card:hover {
  border-color: rgba(var(--v-theme-primary), 0.3);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 16px 0;
}

.model-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(13, 148, 136, 0.15), rgba(20, 184, 166, 0.15));
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgb(var(--v-theme-primary));
}

.model-icon-wrapper {
  position: relative;
}

.health-dot {
  position: absolute;
  top: -2px;
  right: -2px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid rgb(var(--v-theme-surface));
}

.health-healthy {
  background: #10b981;
}

.health-drifted {
  background: #f59e0b;
}

.menu-btn {
  opacity: 0;
  transition: opacity 0.2s ease;
}

.model-card:hover .menu-btn {
  opacity: 1;
}

.card-content {
  padding: 16px !important;
}

.model-name {
  font-size: 1.1rem;
  font-weight: 600;
  margin: 0 0 8px;
  line-height: 1.3;
}

.model-description {
  font-size: 0.875rem;
  color: rgb(var(--v-theme-on-surface-variant));
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-footer {
  display: flex;
  gap: 16px;
  padding: 12px 16px;
  border-top: 1px solid rgba(var(--v-border-color), 0.08);
  background: rgba(var(--v-theme-surface-variant), 0.3);
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
}

.stat-icon {
  opacity: 0.6;
}

.stat-value {
  font-weight: 500;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  text-align: center;
}

.empty-icon {
  width: 80px;
  height: 80px;
  border-radius: 20px;
  background: linear-gradient(135deg, rgba(13, 148, 136, 0.1), rgba(20, 184, 166, 0.1));
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 24px;
}

.empty-title {
  font-size: 1.25rem;
  font-weight: 600;
  margin: 0 0 8px;
}

.empty-description {
  color: rgb(var(--v-theme-on-surface-variant));
  margin: 0 0 24px;
  max-width: 300px;
}

.dialog-card {
  background: rgb(var(--v-theme-surface)) !important;
}

.dialog-title {
  font-size: 1.25rem !important;
  font-weight: 600 !important;
  padding: 20px 24px !important;
  border-bottom: 1px solid rgba(var(--v-border-color), 0.08);
}

.dialog-actions {
  padding: 16px 24px !important;
  border-top: 1px solid rgba(var(--v-border-color), 0.08);
  gap: 8px;
}
</style>
