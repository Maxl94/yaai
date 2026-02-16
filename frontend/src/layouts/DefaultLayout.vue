<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useTheme } from 'vuetify'
import { notificationsApi } from '@/api/notifications'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const theme = useTheme()
const authStore = useAuthStore()

const rail = ref(true)
const unreadCount = ref(0)
let pollInterval: number | null = null

const isDark = computed(() => theme.global.current.value.dark)

function toggleTheme() {
  theme.global.name.value = isDark.value ? 'light' : 'dark'
}

function handleLogout() {
  authStore.logout()
  router.push('/login')
}

const navigationItems = computed(() => {
  const items = [
    { title: 'Models', icon: 'mdi-cube-outline', to: '/models', description: 'ML models & versions' },
    { title: 'Jobs', icon: 'mdi-timer-sync-outline', to: '/jobs', description: 'Scheduled drift jobs' },
    { title: 'Drift', icon: 'mdi-chart-timeline-variant-shimmer', to: '/drift', description: 'Detection results' },
    { title: 'Alerts', icon: 'mdi-bell-ring-outline', to: '/notifications', description: 'Notifications' },
  ]
  if (authStore.isOwner) {
    items.push({ title: 'Settings', icon: 'mdi-cog-outline', to: '/settings', description: 'Users & access' })
  }
  return items
})

async function fetchUnreadCount() {
  try {
    unreadCount.value = await notificationsApi.getUnreadCount()
  } catch (error) {
    console.error('Failed to fetch notification count:', error)
  }
}

onMounted(() => {
  fetchUnreadCount()
  pollInterval = window.setInterval(fetchUnreadCount, 30000)
})

onUnmounted(() => {
  if (pollInterval) {
    clearInterval(pollInterval)
  }
})
</script>

<template>
  <v-app>
    <!-- Modern Navigation Rail -->
    <v-navigation-drawer
      :rail="rail"
      permanent
      class="nav-drawer"
      :width="240"
      rail-width="72"
    >
      <!-- Logo Area -->
      <div class="nav-header" @click="rail = !rail">
        <div class="logo-container">
          <div class="logo-icon">
            <img src="@/assets/logo.svg" alt="YAAI Logo" width="36" height="36" />
          </div>
          <transition name="fade">
            <span v-if="!rail" class="logo-text">YAAI</span>
          </transition>
        </div>
      </div>

      <v-divider class="mx-3 my-2" />

      <!-- Navigation Items -->
      <v-list nav class="nav-list px-2">
        <v-list-item
          v-for="item in navigationItems"
          :key="item.title"
          :to="item.to"
          :active="route.path.startsWith(item.to)"
          rounded="lg"
          class="nav-item mb-1"
        >
          <template #prepend>
            <v-badge
              v-if="item.to === '/notifications' && unreadCount > 0"
              :content="unreadCount"
              color="error"
              floating
            >
              <v-icon>{{ item.icon }}</v-icon>
            </v-badge>
            <v-icon v-else>{{ item.icon }}</v-icon>
          </template>
          <v-list-item-title class="nav-title">{{ item.title }}</v-list-item-title>
          <v-list-item-subtitle v-if="!rail" class="nav-subtitle">
            {{ item.description }}
          </v-list-item-subtitle>
        </v-list-item>
      </v-list>

      <template #append>
        <v-divider class="mx-3 my-2" />
        <div class="nav-footer px-2 pb-4">
          <!-- Theme Toggle -->
          <v-list-item
            rounded="lg"
            class="nav-item"
            @click="toggleTheme"
          >
            <template #prepend>
              <v-icon>{{ isDark ? 'mdi-weather-sunny' : 'mdi-moon-waning-crescent' }}</v-icon>
            </template>
            <v-list-item-title class="nav-title">
              {{ isDark ? 'Light Mode' : 'Dark Mode' }}
            </v-list-item-title>
          </v-list-item>

          <!-- User / Logout (only when auth is enabled) -->
          <template v-if="authStore.authEnabled && authStore.isAuthenticated">
            <v-divider class="mx-1 my-2" />
            <v-list-item
              rounded="lg"
              class="nav-item"
              @click="handleLogout"
            >
              <template #prepend>
                <v-icon>mdi-logout</v-icon>
              </template>
              <v-list-item-title class="nav-title">
                Sign Out
              </v-list-item-title>
              <v-list-item-subtitle v-if="!rail" class="nav-subtitle">
                {{ authStore.user?.username }}
              </v-list-item-subtitle>
            </v-list-item>
          </template>
        </div>
      </template>
    </v-navigation-drawer>

    <!-- Main Content Area -->
    <v-main class="main-content">
      <div class="content-wrapper">
        <router-view />
      </div>
    </v-main>
  </v-app>
</template>

<style scoped>
.nav-drawer {
  border-right: 1px solid rgba(var(--v-border-color), 0.08) !important;
  background: rgb(var(--v-theme-surface)) !important;
}

.nav-header {
  padding: 20px 16px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.logo-container {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: linear-gradient(135deg, #0d9488, #0f766e);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.logo-text {
  font-size: 1.25rem;
  font-weight: 700;
  background: linear-gradient(135deg, rgb(var(--v-theme-primary)), rgb(var(--v-theme-secondary)));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  white-space: nowrap;
}

.nav-list {
  padding-top: 8px;
}

.nav-item {
  min-height: 48px;
  transition: all 0.2s ease;
}

.nav-item:hover {
  background: rgba(var(--v-theme-primary), 0.08);
}

.nav-item.v-list-item--active {
  background: rgba(var(--v-theme-primary), 0.12);
}

.nav-item.v-list-item--active .v-icon {
  color: rgb(var(--v-theme-primary));
}

.nav-title {
  font-weight: 500;
  font-size: 0.9rem;
}

.nav-subtitle {
  font-size: 0.75rem;
  opacity: 0.6;
}

.main-content {
  background: rgb(var(--v-theme-background));
  min-height: 100vh;
}

.content-wrapper {
  padding: 24px 32px;
  max-width: 1600px;
  margin: 0 auto;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@media (max-width: 960px) {
  .content-wrapper {
    padding: 16px;
  }
}
</style>
