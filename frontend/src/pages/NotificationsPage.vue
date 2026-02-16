<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { notificationsApi } from '@/api/notifications'
import type { Notification } from '@/types'

interface SingleItem {
  type: 'single'
  key: string
  notification: Notification
}

interface GroupItem {
  type: 'group'
  key: string
  title: string
  severity: string
  hasUnread: boolean
  notifications: Notification[]
}

type DisplayItem = SingleItem | GroupItem

const notifications = ref<Notification[]>([])
const loading = ref(false)
const severityFilter = ref<string | null>(null)
const readFilter = ref<string | null>(null)

const severityOptions = ['info', 'warning', 'error', 'critical']
const readOptions = [
  { title: 'Unread', value: 'unread' },
  { title: 'Read', value: 'read' },
]

const unreadCount = computed(() => {
  return notifications.value.filter(n => !n.is_read).length
})

const filteredNotifications = computed(() => {
  let result = [...notifications.value]

  if (severityFilter.value) {
    result = result.filter(n => n.severity === severityFilter.value)
  }

  if (readFilter.value === 'unread') {
    result = result.filter(n => !n.is_read)
  } else if (readFilter.value === 'read') {
    result = result.filter(n => n.is_read)
  }

  // Sort by date, newest first
  result.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())

  return result
})

// Group notifications that are within 5 seconds of each other and have the same severity
const displayItems = computed<DisplayItem[]>(() => {
  const items: DisplayItem[] = []
  const sorted = filteredNotifications.value
  let i = 0

  while (i < sorted.length) {
    const current = sorted[i]!
    const cluster: Notification[] = [current]
    let j = i + 1

    // Collect all notifications within 5 seconds and same severity
    while (j < sorted.length) {
      const next = sorted[j]!
      const timeDiff = Math.abs(
        new Date(current.created_at).getTime() - new Date(next.created_at).getTime()
      )
      if (timeDiff <= 5000 && next.severity === current.severity) {
        cluster.push(next)
        j++
      } else {
        break
      }
    }

    if (cluster.length > 1) {
      // Create a group
      const driftCount = cluster.filter(n => n.title.toLowerCase().includes('drift')).length
      const title = driftCount > 0
        ? `Drift detected in ${driftCount} field${driftCount > 1 ? 's' : ''}`
        : `${cluster.length} ${current.severity} notifications`

      items.push({
        type: 'group',
        key: `group-${current.id}`,
        title,
        severity: current.severity,
        hasUnread: cluster.some(n => !n.is_read),
        notifications: cluster,
      })
    } else {
      items.push({
        type: 'single',
        key: current.id,
        notification: current,
      })
    }

    i = j
  }

  return items
})

function getSeverityColor(severity: string): string {
  switch (severity) {
    case 'critical': return 'error'
    case 'error': return 'error'
    case 'warning': return 'warning'
    case 'info': return 'info'
    default: return 'grey'
  }
}

function getSeverityIcon(severity: string): string {
  switch (severity) {
    case 'critical': return 'mdi-alert-octagon'
    case 'error': return 'mdi-alert-circle'
    case 'warning': return 'mdi-alert'
    case 'info': return 'mdi-information'
    default: return 'mdi-bell'
  }
}

async function loadNotifications() {
  loading.value = true
  try {
    notifications.value = await notificationsApi.list()
  } catch (error) {
    console.error('Failed to load notifications:', error)
  } finally {
    loading.value = false
  }
}

async function markAsRead(notification: Notification) {
  try {
    await notificationsApi.markAsRead(notification.id)
    notification.is_read = true
  } catch (error) {
    console.error('Failed to mark notification as read:', error)
  }
}

async function markAllAsRead() {
  try {
    await notificationsApi.markAllAsRead()
    notifications.value.forEach(n => { n.is_read = true })
  } catch (error) {
    console.error('Failed to mark all notifications as read:', error)
  }
}

async function deleteNotification(notification: Notification) {
  try {
    await notificationsApi.delete(notification.id)
    notifications.value = notifications.value.filter(n => n.id !== notification.id)
  } catch (error) {
    console.error('Failed to delete notification:', error)
  }
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return 'Just now'
  if (diffMins < 60) return `${diffMins} min ago`
  if (diffHours < 24) return `${diffHours} hours ago`
  if (diffDays < 7) return `${diffDays} days ago`
  return date.toLocaleDateString()
}

onMounted(() => {
  loadNotifications()
})
</script>

<template>
  <v-container fluid>
    <div class="d-flex align-center mb-4">
      <h1 class="text-h4 font-weight-bold">Notifications</h1>
      <v-chip v-if="unreadCount > 0" color="error" class="ml-4" size="small">
        {{ unreadCount }} unread
      </v-chip>
      <v-spacer />
      <v-btn
        v-if="unreadCount > 0"
        variant="outlined"
        color="primary"
        size="small"
        @click="markAllAsRead"
      >
        <v-icon start size="16">mdi-check-all</v-icon>
        Mark All Read
      </v-btn>
    </div>

    <!-- Filters -->
    <v-card class="mb-4 filter-card" variant="flat">
      <v-card-text class="d-flex align-center flex-wrap ga-4 py-3">
        <v-select
          v-model="severityFilter"
          :items="severityOptions"
          label="Severity"
          clearable
          variant="outlined"
          density="compact"
          hide-details
          style="max-width: 200px"
        />
        <v-select
          v-model="readFilter"
          :items="readOptions"
          label="Status"
          clearable
          variant="outlined"
          density="compact"
          hide-details
          style="max-width: 200px"
        />
      </v-card-text>
    </v-card>

    <!-- Notifications List -->
    <v-card class="notifications-card" variant="flat">
      <v-list v-if="displayItems.length > 0" lines="three">
        <template v-for="(item, index) in displayItems" :key="item.key">
          <!-- Grouped Notification -->
          <template v-if="item.type === 'group'">
            <v-list-group>
              <template #activator="{ props: groupProps }">
                <v-list-item
                  v-bind="groupProps"
                  class="grouped-notification"
                  :class="{ 'unread-notification': item.hasUnread }"
                >
                  <template #prepend>
                    <v-icon
                      :color="getSeverityColor(item.severity)"
                      :icon="getSeverityIcon(item.severity)"
                      size="large"
                    />
                  </template>
                  <v-list-item-title :class="{ 'font-weight-bold': item.hasUnread }">
                    {{ item.title }}
                  </v-list-item-title>
                  <v-list-item-subtitle>
                    {{ item.notifications.length }} notifications
                    <span class="text-medium-emphasis ml-1">{{ formatDate(item.notifications[0]!.created_at) }}</span>
                  </v-list-item-subtitle>
                  <template #append>
                    <v-chip size="x-small" :color="getSeverityColor(item.severity)" class="mr-2">
                      {{ item.severity }}
                    </v-chip>
                  </template>
                </v-list-item>
              </template>

              <v-list-item
                v-for="notification in item.notifications"
                :key="notification.id"
                :class="{ 'unread-notification': !notification.is_read }"
                class="pl-12"
              >
                <v-list-item-title :class="{ 'font-weight-bold': !notification.is_read }" class="text-body-2">
                  {{ notification.title }}
                </v-list-item-title>
                <v-list-item-subtitle class="text-caption">
                  {{ notification.message }}
                </v-list-item-subtitle>
                <v-list-item-subtitle class="text-caption mt-1">
                  <span class="text-medium-emphasis">{{ formatDate(notification.created_at) }}</span>
                </v-list-item-subtitle>
                <template #append>
                  <div class="d-flex">
                    <v-btn
                      v-if="!notification.is_read"
                      icon
                      size="x-small"
                      variant="text"
                      @click.stop="markAsRead(notification)"
                    >
                      <v-icon size="16">mdi-check</v-icon>
                      <v-tooltip activator="parent" location="left">Mark as read</v-tooltip>
                    </v-btn>
                    <v-btn
                      icon
                      size="x-small"
                      variant="text"
                      color="error"
                      @click.stop="deleteNotification(notification)"
                    >
                      <v-icon size="16">mdi-delete</v-icon>
                      <v-tooltip activator="parent" location="left">Delete</v-tooltip>
                    </v-btn>
                  </div>
                </template>
              </v-list-item>
            </v-list-group>
          </template>

          <!-- Single Notification -->
          <template v-else>
            <v-list-item
              :class="{ 'unread-notification': !item.notification.is_read }"
            >
              <template #prepend>
                <v-icon
                  :color="getSeverityColor(item.notification.severity)"
                  :icon="getSeverityIcon(item.notification.severity)"
                  size="large"
                />
              </template>
              <v-list-item-title :class="{ 'font-weight-bold': !item.notification.is_read }">
                {{ item.notification.title }}
              </v-list-item-title>
              <v-list-item-subtitle>
                {{ item.notification.message }}
              </v-list-item-subtitle>
              <v-list-item-subtitle class="mt-1">
                <v-chip size="x-small" :color="getSeverityColor(item.notification.severity)">
                  {{ item.notification.severity }}
                </v-chip>
                <span class="text-medium-emphasis ml-2">{{ formatDate(item.notification.created_at) }}</span>
              </v-list-item-subtitle>
              <template #append>
                <div class="d-flex flex-column">
                  <v-btn
                    v-if="!item.notification.is_read"
                    icon
                    size="small"
                    variant="text"
                    @click.stop="markAsRead(item.notification)"
                  >
                    <v-icon>mdi-check</v-icon>
                    <v-tooltip activator="parent" location="left">Mark as read</v-tooltip>
                  </v-btn>
                  <v-btn
                    icon
                    size="small"
                    variant="text"
                    color="error"
                    @click.stop="deleteNotification(item.notification)"
                  >
                    <v-icon>mdi-delete</v-icon>
                    <v-tooltip activator="parent" location="left">Delete</v-tooltip>
                  </v-btn>
                </div>
              </template>
            </v-list-item>
          </template>

          <v-divider v-if="index < displayItems.length - 1" />
        </template>
      </v-list>

      <!-- Empty State -->
      <v-card-text v-else class="text-center py-8">
        <v-icon size="64" color="primary" style="opacity: 0.3">mdi-bell-off-outline</v-icon>
        <p class="text-h6 mt-4">No notifications</p>
        <p class="text-medium-emphasis">You're all caught up!</p>
      </v-card-text>
    </v-card>
  </v-container>
</template>

<style scoped>
.filter-card,
.notifications-card {
  border: 1px solid rgba(13, 148, 136, 0.1);
  border-radius: 16px;
}

.unread-notification {
  border-left: 3px solid rgb(var(--v-theme-primary));
  background: rgba(var(--v-theme-primary), 0.06);
}

.grouped-notification {
  background: rgba(var(--v-theme-surface-variant), 0.3);
}
</style>
