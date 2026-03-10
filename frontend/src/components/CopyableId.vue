<script setup lang="ts">
import { ref } from 'vue'

const props = withDefaults(defineProps<{
  value: string
  label?: string
  truncate?: boolean
}>(), {
  label: undefined,
  truncate: true,
})

const copied = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null

function displayValue(): string {
  if (props.truncate && props.value.length > 12) {
    return props.value.slice(0, 8) + '…'
  }
  return props.value
}

async function copy(event: Event) {
  event.stopPropagation()
  try {
    await navigator.clipboard.writeText(props.value)
    copied.value = true
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => { copied.value = false }, 2000)
  } catch {
    // Fallback for insecure contexts
    const el = document.createElement('textarea')
    el.value = props.value
    document.body.appendChild(el)
    el.select()
    document.execCommand('copy')
    document.body.removeChild(el)
    copied.value = true
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => { copied.value = false }, 2000)
  }
}
</script>

<template>
  <span class="copyable-id" :title="value" @click="copy">
    <span v-if="label" class="id-label">{{ label }}:</span>
    <code class="id-value">{{ displayValue() }}</code>
    <v-icon
      :icon="copied ? 'mdi-check' : 'mdi-content-copy'"
      :color="copied ? 'success' : undefined"
      size="14"
      class="copy-icon"
    />
    <v-tooltip activator="parent" location="top">
      <template v-if="copied">Copied!</template>
      <template v-else>{{ value }}</template>
    </v-tooltip>
  </span>
</template>

<style scoped>
.copyable-id {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.75rem;
  transition: background-color 0.15s ease;
  user-select: none;
}

.copyable-id:hover {
  background-color: rgba(var(--v-theme-on-surface), 0.06);
}

.id-label {
  color: rgb(var(--v-theme-on-surface-variant));
  font-weight: 500;
}

.id-value {
  font-family: 'Roboto Mono', 'Fira Code', monospace;
  font-size: 0.75rem;
  color: rgb(var(--v-theme-on-surface));
  opacity: 0.7;
}

.copy-icon {
  opacity: 0.4;
  transition: opacity 0.15s ease;
}

.copyable-id:hover .copy-icon {
  opacity: 0.8;
}
</style>
