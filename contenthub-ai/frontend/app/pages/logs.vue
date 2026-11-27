<script setup lang="ts">
import { ChevronLeft, ChevronRight, RefreshCw, Search } from 'lucide-vue-next'
import type { ActivityLogListResponse } from '~/types/api'
import { extractErrorMessage, formatDateTime } from '~/utils/format'

const { request } = useApiClient()
const runtimeConfig = useRuntimeConfig()

const logsResponse = ref<ActivityLogListResponse | null>(null)
const loading = ref(true)
const errorMessage = ref<string | null>(null)

const page = ref(1)
const pageSize = ref(20)
const selectedCategory = ref('all')
const selectedLevel = ref('all')
const searchQuery = ref('')

const categoryItems = [
  { label: 'All Categories', value: 'all' },
  { label: 'Authentication', value: 'auth' },
  { label: 'Settings', value: 'settings' },
  { label: 'System', value: 'system' },
]

const levelItems = [
  { label: 'All Levels', value: 'all' },
  { label: 'Info', value: 'info' },
  { label: 'Warning', value: 'warning' },
  { label: 'Error', value: 'error' },
]

const defaultTimezone = computed(() => String(runtimeConfig.public.defaultTimezone || 'Asia/Manila'))

async function fetchLogs() {
  loading.value = true
  errorMessage.value = null
  try {
    const query: Record<string, string | number> = {
      page: page.value,
      page_size: pageSize.value,
    }
    if (selectedCategory.value !== 'all') {
      query.category = selectedCategory.value
    }
    if (selectedLevel.value !== 'all') {
      query.level = selectedLevel.value
    }
    if (searchQuery.value.trim()) {
      query.search = searchQuery.value.trim()
    }
    logsResponse.value = await request<ActivityLogListResponse>('/api/v1/logs/activity', { query })
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to fetch activity logs.')
  }
  finally {
    loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  void fetchLogs()
}

function goPrevious() {
  if (page.value > 1) {
    page.value -= 1
    void fetchLogs()
  }
}

function goNext() {
  if (logsResponse.value && page.value < logsResponse.value.meta.total_pages) {
    page.value += 1
    void fetchLogs()
  }
}

onMounted(() => {
  void fetchLogs()
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">
          Activity & Audit Logs
        </h1>
        <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          Redacted chronological audit trail stored in MySQL. Sensitive keys and credentials are never recorded.
        </p>
      </div>
      <UButton
        color="neutral"
        variant="outline"
        size="sm"
        :loading="loading"
        @click="fetchLogs()"
      >
        <RefreshCw class="mr-1.5 h-3.5 w-3.5" />
        Refresh
      </UButton>
    </div>

    <!-- Filters -->
    <form
      class="flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
      @submit.prevent="applyFilters"
    >
      <div class="min-w-44 flex-1">
        <label class="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">
          Search message or action
        </label>
        <div class="relative">
          <Search class="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
          <UInput
            v-model="searchQuery"
            placeholder="e.g. auth.login_succeeded"
            class="w-full pl-8"
          />
        </div>
      </div>

      <div class="w-40">
        <label class="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">
          Category
        </label>
        <USelect
          v-model="selectedCategory"
          :items="categoryItems"
          value-key="value"
          class="w-full"
          @update:model-value="applyFilters"
        />
      </div>

      <div class="w-36">
        <label class="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">
          Level
        </label>
        <USelect
          v-model="selectedLevel"
          :items="levelItems"
          value-key="value"
          class="w-full"
          @update:model-value="applyFilters"
        />
      </div>

      <UButton
        type="submit"
        color="primary"
        size="sm"
      >
        Apply
      </UButton>
    </form>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="Could not load logs"
      :message="errorMessage"
      retryable
      @retry="fetchLogs()"
    />

    <div class="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <div
        v-if="loading"
        class="space-y-3 p-4"
      >
        <USkeleton
          v-for="idx in 6"
          :key="idx"
          class="h-8 w-full"
        />
      </div>

      <div
        v-else-if="!logsResponse || logsResponse.items.length === 0"
        class="p-6"
      >
        <AppEmptyState
          title="No matching log entries"
          description="Try broadening your search filters or perform an administrative action to generate audit records."
        />
      </div>

      <template v-else>
        <div class="overflow-x-auto">
          <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
            <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
              <tr>
                <th class="px-4 py-2.5 font-medium">Timestamp</th>
                <th class="px-4 py-2.5 font-medium">Actor</th>
                <th class="px-4 py-2.5 font-medium">Category</th>
                <th class="px-4 py-2.5 font-medium">Level</th>
                <th class="px-4 py-2.5 font-medium">Action</th>
                <th class="px-4 py-2.5 font-medium">Message</th>
                <th class="px-4 py-2.5 font-medium">IP</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
              <tr
                v-for="entry in logsResponse.items"
                :key="entry.id"
                class="hover:bg-slate-50/70 dark:hover:bg-slate-800/40"
              >
                <td class="px-4 py-2.5 whitespace-nowrap text-slate-500 dark:text-slate-400">
                  {{ formatDateTime(entry.created_at, defaultTimezone) }}
                </td>
                <td class="px-4 py-2.5 whitespace-nowrap text-slate-600 dark:text-slate-300">
                  {{ entry.actor_type }}
                </td>
                <td class="px-4 py-2.5 whitespace-nowrap">
                  <UBadge
                    color="neutral"
                    variant="subtle"
                    size="sm"
                  >
                    {{ entry.category }}
                  </UBadge>
                </td>
                <td class="px-4 py-2.5 whitespace-nowrap">
                  <HealthStatusBadge
                    :status="entry.level === 'info' ? 'ok' : entry.level"
                    :label="entry.level"
                  />
                </td>
                <td class="px-4 py-2.5 font-mono text-[11px] whitespace-nowrap text-slate-700 dark:text-slate-300">
                  {{ entry.action }}
                </td>
                <td class="px-4 py-2.5 text-slate-700 dark:text-slate-200">
                  {{ entry.message }}
                </td>
                <td class="px-4 py-2.5 font-mono text-[11px] whitespace-nowrap text-slate-500 dark:text-slate-400">
                  {{ entry.ip_address || '-' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Pagination -->
        <div class="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-4 py-3 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
          <span>
            Page {{ logsResponse.meta.page }} of {{ Math.max(1, logsResponse.meta.total_pages) }}
            ({{ logsResponse.meta.total_items }} total records)
          </span>
          <div class="flex items-center gap-2">
            <UButton
              color="neutral"
              variant="outline"
              size="xs"
              :disabled="page <= 1"
              @click="goPrevious"
            >
              <ChevronLeft class="mr-1 h-3.5 w-3.5" />
              Previous
            </UButton>
            <UButton
              color="neutral"
              variant="outline"
              size="xs"
              :disabled="page >= logsResponse.meta.total_pages"
              @click="goNext"
            >
              Next
              <ChevronRight class="ml-1 h-3.5 w-3.5" />
            </UButton>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
