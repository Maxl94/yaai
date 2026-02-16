import { createApp } from 'vue'
import { createPinia } from 'pinia'

// Vuetify
import 'vuetify/styles'
import '@mdi/font/css/materialdesignicons.css'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

import App from './App.vue'
import router from './router'

const vuetify = createVuetify({
  components,
  directives,
  theme: {
    defaultTheme: 'dark',
    themes: {
      dark: {
        dark: true,
        colors: {
          background: '#0c0f12',
          surface: '#131820',
          'surface-bright': '#1b2230',
          'surface-variant': '#1e2735',
          'on-surface-variant': '#94a3b8',
          primary: '#0d9488',
          'primary-darken-1': '#0f766e',
          secondary: '#f59e0b',
          accent: '#2dd4bf',
          error: '#f43f5e',
          info: '#38bdf8',
          success: '#10b981',
          warning: '#f59e0b',
        },
      },
      light: {
        dark: false,
        colors: {
          background: '#f8faf9',
          surface: '#ffffff',
          'surface-bright': '#ffffff',
          'surface-variant': '#f0f5f4',
          'on-surface-variant': '#5f7a74',
          primary: '#0d9488',
          'primary-darken-1': '#0f766e',
          secondary: '#d97706',
          accent: '#14b8a6',
          error: '#ef4444',
          info: '#0ea5e9',
          success: '#10b981',
          warning: '#f59e0b',
        },
      },
    },
  },
  defaults: {
    VCard: {
      rounded: 'lg',
      elevation: 0,
    },
    VBtn: {
      rounded: 'lg',
    },
    VTextField: {
      variant: 'outlined',
      density: 'comfortable',
      rounded: 'lg',
    },
    VSelect: {
      variant: 'outlined',
      density: 'comfortable',
      rounded: 'lg',
    },
    VChip: {
      rounded: 'lg',
    },
  },
})

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(vuetify)

app.mount('#app')
