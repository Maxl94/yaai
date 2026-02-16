<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { isApiError } from '@/types'

const router = useRouter()
const authStore = useAuthStore()

const username = ref('')
const password = ref('')
const showPassword = ref(false)
const error = ref('')

async function handleLogin() {
  error.value = ''
  try {
    await authStore.login(username.value, password.value)
    router.replace('/')
  } catch (err) {
    if (isApiError(err)) {
      error.value = err.detail || err.message || 'Login failed'
    } else {
      error.value = 'An unexpected error occurred'
    }
  }
}

function handleGoogleLogin() {
  window.location.href = '/api/v1/auth/oauth/google'
}
</script>

<template>
  <v-app>
    <v-main class="login-background">
      <v-container class="fill-height" fluid>
        <v-row align="center" justify="center">
          <v-col cols="12" sm="8" md="5" lg="4" xl="3">
            <!-- Logo -->
            <div class="text-center mb-8">
              <div class="logo-icon mx-auto mb-2">
                <img src="@/assets/banner-bordered.svg" alt="YAAI Logo" width="600px"/>
              </div>
              <!-- <h1 class="app-title">YAAI Monitoring</h1>e -->
              <p class="app-subtitle">Sign in to continue</p>
            </div>

            <v-card class="login-card pa-6">
              <!-- Error Alert -->
              <v-alert
                v-if="error"
                type="error"
                variant="tonal"
                density="compact"
                closable
                class="mb-4"
                @click:close="error = ''"
              >
                {{ error }}
              </v-alert>

              <!-- Local Login Form -->
              <v-form
                v-if="authStore.authConfig?.local_enabled"
                @submit.prevent="handleLogin"
              >
                <v-text-field
                  v-model="username"
                  label="Username"
                  prepend-inner-icon="mdi-account-outline"
                  autofocus
                  class="mb-2"
                />
                <v-text-field
                  v-model="password"
                  :type="showPassword ? 'text' : 'password'"
                  label="Password"
                  prepend-inner-icon="mdi-lock-outline"
                  :append-inner-icon="showPassword ? 'mdi-eye-off' : 'mdi-eye'"
                  class="mb-4"
                  @click:append-inner="showPassword = !showPassword"
                />
                <v-btn
                  type="submit"
                  color="primary"
                  size="large"
                  block
                  :loading="authStore.loading"
                  :disabled="!username || !password"
                >
                  Sign In
                </v-btn>
              </v-form>

              <!-- Divider between local and OAuth -->
              <div
                v-if="authStore.authConfig?.local_enabled && authStore.authConfig?.google_oauth_enabled"
                class="divider-row my-5"
              >
                <v-divider />
                <span class="divider-text">or</span>
                <v-divider />
              </div>

              <!-- Google OAuth -->
              <v-btn
                v-if="authStore.authConfig?.google_oauth_enabled"
                variant="outlined"
                size="large"
                block
                class="google-btn"
                @click="handleGoogleLogin"
              >
                <template #prepend>
                  <v-icon>mdi-google</v-icon>
                </template>
                Sign in with Google
              </v-btn>
            </v-card>
          </v-col>
        </v-row>
      </v-container>
    </v-main>
  </v-app>
</template>

<style scoped>
.login-background {
  background: rgb(var(--v-theme-background));
  min-height: 100vh;
}

.logo-icon {
  margin-top: 64px;
  margin-bottom: 32px;
  width: 360px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.app-title {
  font-size: 1.75rem;
  font-weight: 700;
  background: linear-gradient(135deg, rgb(var(--v-theme-primary)), rgb(var(--v-theme-secondary)));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.app-subtitle {
  color: rgb(var(--v-theme-on-surface-variant));
  margin-top: 4px;
  font-size: 0.95rem;
}

.login-card {
  border: 1px solid rgba(var(--v-border-color), 0.08);
  background: rgb(var(--v-theme-surface)) !important;
}

.divider-row {
  display: flex;
  align-items: center;
  gap: 16px;
}

.divider-text {
  color: rgb(var(--v-theme-on-surface-variant));
  font-size: 0.85rem;
  white-space: nowrap;
}

.google-btn {
  text-transform: none;
  letter-spacing: 0;
  font-weight: 500;
}
</style>
