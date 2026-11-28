<script setup lang="ts">
import { ChevronLeft, ChevronRight, RefreshCw } from 'lucide-vue-next'
import type { AiGenerationLogItem, AiGenerationLogListResponse, AiPromptLogDetail, AiProviderItem } from '~/types/api'
import { extractErrorMessage, formatDateTime } from '~/utils/format'

const { request } = useApiClient()
const timezone = String(useRuntimeConfig().public.defaultTimezone || 'Asia/Manila')
const uiStore = useUiStore()
const pageSize = 20
const page = ref(1)
const providers = ref<AiProviderItem[]>([])
const logs = ref<AiGenerationLogListResponse | null>(null)
const loading = ref(true)
const listError = ref<string | null>(null)
const modelSearch = ref('')
const providerFilter = ref('all')
const taskFilter = ref('all')
const statusFilter = ref('all')
let listRequest = 0

const detailOpen = ref(false)
const selected = ref<AiGenerationLogItem | null>(null)
const detail = ref<AiPromptLogDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref<string | null>(null)
let detailRequest = 0

const providerItems = computed(() => [
  { label: 'All providers', value: 'all' },
  ...providers.value.map(provider => ({ label: provider.name, value: String(provider.id) })),
])
const taskLabels: Record<string, string> = {
  social_generation: 'Social drafts',
  knowledge_analysis: 'Website knowledge',
  keyword_refinement: 'Keyword refinement',
  connection_probe: 'Connection test',
}
const taskItems = [
  { label: 'All tasks', value: 'all' },
  ...Object.entries(taskLabels).map(([value, label]) => ({ label, value })),
]
const statusItems = [
  { label: 'All statuses', value: 'all' },
  { label: 'Succeeded', value: 'succeeded' },
  { label: 'Failed', value: 'failed' },
  { label: 'Invalid response', value: 'invalid_response' },
  { label: 'Timed out', value: 'timeout' },
  { label: 'Rate limited', value: 'rate_limited' },
  { label: 'Quota blocked', value: 'quota_blocked' },
]

function displayProvider(log: AiGenerationLogItem) {
  const type = log.provider_type === 'localai' ? 'LocalAI' : log.provider_type === 'gemini' ? 'Gemini' : log.provider_type
  const name = log.provider_name || `Provider #${log.ai_provider_id}`
  return type && type.toLowerCase() !== name.toLowerCase() ? `${name} · ${type}` : name
}

function displayStatus(status: string) {
  return statusItems.find(item => item.value === status)?.label || status.replaceAll('_', ' ')
}

function tokenCount(value: number | null) {
  return value === null ? '—' : value.toLocaleString()
}

async function loadLogs() {
  const requestId = ++listRequest
  loading.value = true
  listError.value = null
  try {
    const result = await request<AiGenerationLogListResponse>('/api/v1/ai/history', {
      query: {
        page: page.value,
        page_size: pageSize,
        website_id: uiStore.selectedWebsiteId ?? undefined,
        provider_id: providerFilter.value === 'all' ? undefined : Number(providerFilter.value),
        task_type: taskFilter.value === 'all' ? undefined : taskFilter.value,
        status: statusFilter.value === 'all' ? undefined : statusFilter.value,
        model_search: modelSearch.value.trim() || undefined,
      },
    })
    if (requestId === listRequest) logs.value = result
  }
  catch (err) {
    if (requestId === listRequest) listError.value = extractErrorMessage(err, 'Could not load prompt logs.')
  }
  finally {
    if (requestId === listRequest) loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  void loadLogs()
}

function goToPage(nextPage: number) {
  page.value = nextPage
  void loadLogs()
}

async function openLog(log: AiGenerationLogItem) {
  const requestId = ++detailRequest
  selected.value = log
  detail.value = null
  detailError.value = null
  detailOpen.value = true
  detailLoading.value = true
  try {
    const result = await request<AiPromptLogDetail>(`/api/v1/ai/prompt-logs/${log.id}`)
    if (requestId === detailRequest) detail.value = result
  }
  catch (err) {
    if (requestId === detailRequest) detailError.value = extractErrorMessage(err, 'Could not open the exchange.')
  }
  finally {
    if (requestId === detailRequest) detailLoading.value = false
  }
}

watch([providerFilter, taskFilter, statusFilter, () => uiStore.selectedWebsiteId], applyFilters)
watch(detailOpen, (open) => {
  if (!open) {
    detailRequest++
    detail.value = null
  }
})
onMounted(async () => {
  void loadLogs()
  try {
    providers.value = await request<AiProviderItem[]>('/api/v1/ai/providers')
  }
  catch {
    // The history remains available if the provider filter cannot be populated.
  }
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">Prompt Logs</h1>
        <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          Review AI prompts and responses with model, token usage, and request status.
        </p>
      </div>
      <UButton color="neutral" variant="outline" size="sm" :loading="loading" @click="loadLogs">
        <RefreshCw class="h-3.5 w-3.5" /> Refresh
      </UButton>
    </div>

    <form class="flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900" @submit.prevent="applyFilters">
      <UFormField label="Search model" class="min-w-44 flex-1">
        <UInput v-model="modelSearch" placeholder="e.g. qwen or gemini" :maxlength="120" class="w-full" />
      </UFormField>
      <UFormField label="Provider" class="w-40">
        <USelect v-model="providerFilter" :items="providerItems" class="w-full" />
      </UFormField>
      <UFormField label="Task" class="w-40">
        <USelect v-model="taskFilter" :items="taskItems" class="w-full" />
      </UFormField>
      <UFormField label="Status" class="w-36">
        <USelect v-model="statusFilter" :items="statusItems" class="w-full" />
      </UFormField>
      <UButton type="submit" size="sm">Apply</UButton>
    </form>

    <AppErrorState v-if="listError && !loading" title="Could not load logs" :message="listError" retryable @retry="loadLogs" />
    <div v-else class="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <div v-if="loading" class="space-y-3 p-4">
        <USkeleton v-for="index in 6" :key="index" class="h-8 w-full" />
      </div>
      <div v-else-if="!logs?.items.length" class="p-6">
        <AppEmptyState title="No matching prompt logs" description="Try clearing a filter or run an AI task to create an exchange." />
      </div>
      <template v-else>
        <div class="overflow-x-auto">
          <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
            <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
              <tr>
                <th v-for="heading in ['Timestamp', 'Provider / Model', 'Task / Website', 'Status', 'Input tokens', 'Output tokens', 'Total tokens', 'Latency', 'Exchange']" :key="heading" scope="col" class="px-4 py-2.5 font-medium whitespace-nowrap">{{ heading }}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
              <tr v-for="log in logs.items" :key="log.id" class="hover:bg-slate-50/70 dark:hover:bg-slate-800/40">
                <td class="px-4 py-2.5 whitespace-nowrap text-slate-500 dark:text-slate-400">{{ formatDateTime(log.created_at, timezone) }}</td>
                <td class="px-4 py-2.5">
                  <div>{{ displayProvider(log) }}</div>
                  <div class="font-mono text-slate-500 dark:text-slate-400">{{ log.model_name }}</div>
                </td>
                <td class="px-4 py-2.5">
                  <div>{{ taskLabels[log.task_type] || log.task_type.replaceAll('_', ' ') }}</div>
                  <div v-if="log.website_name" class="text-slate-500 dark:text-slate-400">{{ log.website_name }}</div>
                </td>
                <td class="px-4 py-2.5">
                  <UBadge :color="log.cache_hit ? 'info' : log.status === 'succeeded' ? 'success' : ['quota_blocked', 'rate_limited'].includes(log.status) ? 'warning' : 'error'" variant="subtle" size="xs">
                    {{ log.cache_hit ? 'Cache hit' : displayStatus(log.status) }}
                  </UBadge>
                </td>
                <td class="px-4 py-2.5 whitespace-nowrap tabular-nums">
                  {{ tokenCount(log.measured_input_tokens) }}
                  <span v-if="log.measured_input_tokens === null && log.estimated_input_tokens !== null" class="block text-slate-500 dark:text-slate-400">{{ tokenCount(log.estimated_input_tokens) }} est.</span>
                </td>
                <td class="px-4 py-2.5 tabular-nums">{{ tokenCount(log.measured_output_tokens) }}</td>
                <td class="px-4 py-2.5 tabular-nums">{{ tokenCount(log.total_measured_tokens) }}</td>
                <td class="px-4 py-2.5 whitespace-nowrap tabular-nums">{{ log.latency_ms === null ? '—' : `${log.latency_ms} ms` }}</td>
                <td class="px-4 py-2.5">
                  <UButton color="neutral" variant="outline" size="xs" :aria-label="`View AI exchange ${log.id}`" @click="openLog(log)">View</UButton>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="flex items-center justify-between gap-3 border-t border-slate-200 px-4 py-3 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
          <span>Page {{ page }} of {{ logs.meta.total_pages }} · {{ logs.meta.total_items }} entries</span>
          <div class="flex gap-2">
            <UButton color="neutral" variant="outline" size="xs" :disabled="page <= 1" @click="goToPage(page - 1)"><ChevronLeft class="h-3.5 w-3.5" /> Previous</UButton>
            <UButton color="neutral" variant="outline" size="xs" :disabled="page >= logs.meta.total_pages" @click="goToPage(page + 1)">Next <ChevronRight class="h-3.5 w-3.5" /></UButton>
          </div>
        </div>
      </template>
    </div>

    <UModal v-model:open="detailOpen" :title="selected ? `AI exchange #${selected.id}` : 'AI exchange'" :description="selected ? `${displayProvider(selected)} · ${selected.model_name}` : undefined" :ui="{ content: 'sm:max-w-4xl' }">
      <template #body>
        <div v-if="selected" class="space-y-4 text-sm">
          <dl class="grid grid-cols-2 gap-3 rounded-lg bg-slate-50 p-3 text-xs sm:grid-cols-4 dark:bg-slate-950/60">
            <div><dt class="text-slate-500 dark:text-slate-400">Status</dt><dd>{{ selected.cache_hit ? 'Cache hit' : displayStatus(selected.status) }}</dd></div>
            <div><dt class="text-slate-500 dark:text-slate-400">Estimated input</dt><dd>{{ tokenCount(selected.estimated_input_tokens) }}</dd></div>
            <div><dt class="text-slate-500 dark:text-slate-400">Measured input</dt><dd>{{ tokenCount(selected.measured_input_tokens) }}</dd></div>
            <div><dt class="text-slate-500 dark:text-slate-400">Measured output</dt><dd>{{ tokenCount(selected.measured_output_tokens) }}</dd></div>
            <div><dt class="text-slate-500 dark:text-slate-400">Measured total</dt><dd>{{ tokenCount(selected.total_measured_tokens) }}</dd></div>
            <div><dt class="text-slate-500 dark:text-slate-400">Latency</dt><dd>{{ selected.latency_ms === null ? '—' : `${selected.latency_ms} ms` }}</dd></div>
            <div><dt class="text-slate-500 dark:text-slate-400">Context</dt><dd>{{ selected.context_mode.replaceAll('_', ' ') }}</dd></div>
            <div v-if="selected.estimated_cost_usd !== null"><dt class="text-slate-500 dark:text-slate-400">Estimated cost</dt><dd>${{ selected.estimated_cost_usd }}</dd></div>
          </dl>
          <UAlert v-if="selected.error_message" color="error" :title="selected.error_code || 'AI request error'" :description="selected.error_message" />
          <p v-if="selected.cache_hit" class="text-xs text-slate-500 dark:text-slate-400">ContentHub reused a saved response for this request.</p>
          <p v-if="selected.truncated_input" class="text-xs text-slate-500 dark:text-slate-400">{{ selected.truncation_note || 'The input context was shortened before generation.' }}</p>
          <USkeleton v-if="detailLoading" class="h-28 w-full" />
          <UAlert v-else-if="detailError" color="error" title="Could not load prompt text" :description="detailError" />
          <div v-else-if="detail?.capture_status === 'captured'" class="space-y-4">
            <p v-if="detail.truncated" class="text-xs text-amber-700 dark:text-amber-400">A long text field was shortened in this log.</p>
            <section v-if="detail.system_instruction">
              <h3 class="mb-1 font-medium">System instruction</h3>
              <pre class="max-h-48 overflow-auto rounded-lg bg-slate-50 p-3 text-xs wrap-anywhere whitespace-pre-wrap dark:bg-slate-950/60">{{ detail.system_instruction }}</pre>
            </section>
            <section>
              <h3 class="mb-1 font-medium">Prompt</h3>
              <pre class="max-h-64 overflow-auto rounded-lg bg-slate-50 p-3 text-xs wrap-anywhere whitespace-pre-wrap dark:bg-slate-950/60">{{ detail.user_prompt || 'Prompt unavailable.' }}</pre>
            </section>
            <section>
              <h3 class="mb-1 font-medium">{{ selected.cache_hit ? 'Cached result' : 'AI response' }}</h3>
              <pre class="max-h-72 overflow-auto rounded-lg bg-slate-50 p-3 text-xs wrap-anywhere whitespace-pre-wrap dark:bg-slate-950/60">{{ detail.response || 'No response text was captured.' }}</pre>
            </section>
          </div>
          <p v-else class="text-slate-500 dark:text-slate-400">
            {{ detail?.capture_status === 'unavailable' ? 'The stored exchange could not be decrypted.' : 'Prompt and response text were not captured for this entry.' }}
          </p>
        </div>
      </template>
    </UModal>
  </div>
</template>
