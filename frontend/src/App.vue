<script setup lang="ts">
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import DefaultLayout from './layouts/DefaultLayout.vue'

const route = useRoute()
const authStore = useAuthStore()
</script>

<template>
  <!-- Show loading spinner while auth initializes -->
  <v-app v-if="!authStore.initialized">
    <v-main class="d-flex align-center justify-center" style="min-height: 100vh; background: rgb(var(--v-theme-background))">
      <v-progress-circular indeterminate color="primary" size="48" />
    </v-main>
  </v-app>

  <!-- Login page renders its own layout -->
  <router-view v-else-if="route.name === 'login'" />

  <!-- All other pages use the default layout -->
  <DefaultLayout v-else />
</template>
