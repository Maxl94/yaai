import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import type { AuthUser, Project, ProjectRole } from '@/types'

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

export function createTestVuetify() {
  globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver
  // Vuetify overlays (dialogs, menus) subscribe to visualViewport, which happy-dom does not provide
  if (!('visualViewport' in globalThis) || !globalThis.visualViewport) {
    Object.defineProperty(globalThis, 'visualViewport', {
      value: { addEventListener() {}, removeEventListener() {}, width: 1024, height: 768, offsetTop: 0, offsetLeft: 0 },
      configurable: true,
    })
  }
  return createVuetify({ components, directives })
}

export function makeUser(overrides: Partial<AuthUser> = {}): AuthUser {
  return {
    id: 'u1',
    username: 'alice',
    email: null,
    role: 'viewer',
    auth_provider: 'local',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

export function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: 'p1',
    name: 'Project One',
    description: null,
    is_default: false,
    model_count: 0,
    my_role: 'viewer' as ProjectRole,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}
