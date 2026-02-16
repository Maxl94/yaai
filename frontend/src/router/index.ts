import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      redirect: '/models',
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/pages/LoginPage.vue'),
      meta: { public: true },
    },
    {
      path: '/models',
      name: 'models',
      component: () => import('@/pages/ModelsPage.vue'),
    },
    {
      path: '/models/:modelId',
      name: 'model-detail',
      component: () => import('@/pages/ModelDetailPage.vue'),
    },
    {
      path: '/models/:modelId/versions/:versionId/dashboard',
      name: 'dashboard',
      component: () => import('@/pages/DashboardPage.vue'),
    },
    {
      path: '/models/:modelId/versions/:versionId/compare',
      name: 'comparison',
      component: () => import('@/pages/ComparisonPage.vue'),
    },
    {
      path: '/models/:modelId/versions/:versionId/drift',
      name: 'version-drift-results',
      component: () => import('@/pages/DriftResultsPage.vue'),
    },
    {
      path: '/models/:modelId/versions/:versionId/schema',
      name: 'version-schema',
      component: () => import('@/pages/SchemaPage.vue'),
    },
    {
      path: '/drift',
      name: 'drift-results',
      component: () => import('@/pages/DriftResultsPage.vue'),
    },
    {
      path: '/models/:modelId/versions/:versionId/jobs',
      name: 'version-jobs',
      component: () => import('@/pages/JobsPage.vue'),
    },
    {
      path: '/jobs',
      name: 'jobs',
      component: () => import('@/pages/JobsPage.vue'),
    },
    {
      path: '/notifications',
      name: 'notifications',
      component: () => import('@/pages/NotificationsPage.vue'),
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/pages/SettingsPage.vue'),
      meta: { requiresOwner: true },
    },
  ],
})

router.beforeEach(async (to) => {
  const authStore = useAuthStore()

  // Ensure auth config is loaded
  if (!authStore.initialized) {
    await authStore.initialize()
  }

  // If auth is disabled, allow all routes
  if (!authStore.authEnabled) {
    // Redirect away from login page when auth is disabled
    if (to.name === 'login') return '/'
    return
  }

  // Allow public routes (login page)
  if (to.meta.public) {
    // Redirect authenticated users away from login
    if (to.name === 'login' && authStore.isAuthenticated) return '/'
    return
  }

  // Require authentication for all other routes
  if (!authStore.isAuthenticated) {
    return { name: 'login' }
  }

  // Owner-only routes
  if (to.meta.requiresOwner && !authStore.isOwner) {
    return '/models'
  }
})

export default router
