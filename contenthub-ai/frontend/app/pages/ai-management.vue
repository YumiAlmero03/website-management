<script setup lang="ts">
import {
  CheckCircle2,
  Database,
  Download,
  Eye,
  History,
  KeyRound,
  PauseCircle,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Trash2,
  Zap,
} from 'lucide-vue-next'
import type {
  AiGenerationJob,
  AiGenerationJobListResponse,
  AiGenerationLogItem,
  AiGenerationLogListResponse,
  AiProviderItem,
  AiProviderModelsResponse,
  AiProviderTestResult,
  AiUsageSummary,
  CacheStatsResponse,
  ContentListItem,
  ContentListResponse,
  PromptPreviewResult,
  PromptTemplateItem,
  PromptTemplateRevision,
} from '~/types/api'
import {
  CONTEXT_MODE_OPTIONS,
  PROMPT_TASK_TYPE_OPTIONS,
  getJobStatusMeta,
  getQuotaStatusMeta,
} from '~/utils/ai'
import { extractErrorMessage, formatDateTime } from '~/utils/format'

type AiTab = 'overview' | 'providers' | 'prompts' | 'history' | 'usage' | 'cache'

const { request } = useApiClient()
const uiStore = useUiStore()
const toast = useToast()

const activeTab = ref<AiTab>('overview')
const loading = ref(true)
const errorMessage = ref<string | null>(null)

// Data stores
const providers = ref<AiProviderItem[]>([])
const prompts = ref<PromptTemplateItem[]>([])
const usage = ref<AiUsageSummary | null>(null)
const jobs = ref<AiGenerationJob[]>([])
const historyLogs = ref<AiGenerationLogItem[]>([])
const cacheStats = ref<CacheStatsResponse | null>(null)
const contentsSample = ref<ContentListItem[]>([])

// Provider Config Modal & Testing
const providerModalOpen = ref(false)
const savingProvider = ref(false)
const editingProvider = ref<AiProviderItem | null>(null)
const testingProviderId = ref<number | null>(null)
const refreshingModelsId = ref<number | null>(null)
const testResult = ref<AiProviderTestResult | null>(null)
const verifyGenOnTest = ref(false)

const providerForm = ref({
  name: 'Primary Gemini Free',
  provider_type: 'gemini',
  base_url: '',
  api_key: '',
  clear_api_key: false,
  selected_model: 'gemini-3.5-flash-lite',
  default_temperature: 0.4,
  max_output_tokens: 1500,
  request_timeout_seconds: 45,
  max_retry_attempts: 2,
  daily_request_limit: 100,
  daily_token_limit: 250000,
  per_minute_request_limit: 10,
  generation_enabled: true,
  response_caching_enabled: true,
  token_optimization_enabled: true,
  is_default: true,
  is_active: true,
})

// Prompt Modal & Offline Preview
const promptModalOpen = ref(false)
const savingPrompt = ref(false)
const editingPrompt = ref<PromptTemplateItem | null>(null)
const promptRevisionsOpen = ref(false)
const promptRevisions = ref<PromptTemplateRevision[]>([])

const promptForm = ref({
  template_key: '',
  name: '',
  task_type: 'multi_platform_social',
  platform_key: '',
  website_id: '',
  system_instructions: '',
  user_prompt_template: '',
  change_note: '',
  is_active: true,
})

const previewWebsiteId = ref('')
const previewContentId = ref('')
const previewContextMode = ref('optimized')
const previewLoading = ref(false)
const previewOutput = ref<PromptPreviewResult | null>(null)

// History Filters & Actions
const historyStatusFilter = ref('all')
const exportingCsv = ref(false)

// Cache Selection & Invalidation
const selectedCacheIds = ref<number[]>([])
const invalidatingCache = ref(false)

const quotaMeta = computed(() =>
  getQuotaStatusMeta(usage.value?.quota_status || 'unconfigured'),
)

function parseOptionalNumber(val: string): number | null {
  const clean = val.trim()
  return clean ? Number(clean) : null
}

async function loadOverviewAndProviders() {
  loading.value = true
  errorMessage.value = null
  try {
    const wid = uiStore.selectedWebsiteId ?? undefined
    const [provRes, usageRes, jobsRes, histRes, promptsRes, cacheRes] = await Promise.all([
      request<AiProviderItem[]>('/api/v1/ai/providers'),
      request<AiUsageSummary>('/api/v1/ai/usage'),
      request<AiGenerationJobListResponse>('/api/v1/ai/jobs', {
        query: { website_id: wid, page: 1, page_size: 20 },
      }),
      request<AiGenerationLogListResponse>('/api/v1/ai/history', {
        query: {
          website_id: wid,
          status: historyStatusFilter.value === 'all' ? undefined : historyStatusFilter.value,
          page: 1,
          page_size: 30,
        },
      }),
      request<PromptTemplateItem[]>('/api/v1/ai/prompts'),
      request<CacheStatsResponse>('/api/v1/ai/cache/stats', {
        query: { website_id: wid },
      }),
    ])
    providers.value = provRes
    usage.value = usageRes
    jobs.value = jobsRes.items
    historyLogs.value = histRes.items
    prompts.value = promptsRes
    cacheStats.value = cacheRes
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to load AI Management workspace.')
  }
  finally {
    loading.value = false
  }
}

function openCreateProvider() {
  editingProvider.value = null
  providerForm.value = {
    name: providers.value.length === 0 ? 'Primary Gemini Free' : `AI Provider ${providers.value.length + 1}`,
    provider_type: 'gemini',
    base_url: '',
    api_key: '',
    clear_api_key: false,
    selected_model: 'gemini-3.5-flash-lite',
    default_temperature: 0.4,
    max_output_tokens: 1500,
    request_timeout_seconds: 45,
    max_retry_attempts: 2,
    daily_request_limit: 100,
    daily_token_limit: 250000,
    per_minute_request_limit: 10,
    generation_enabled: true,
    response_caching_enabled: true,
    token_optimization_enabled: true,
    is_default: providers.value.length === 0,
    is_active: true,
  }
  providerModalOpen.value = true
}

function handleProviderTypeChange() {
  if (editingProvider.value) {
    return
  }
  if (providerForm.value.provider_type === 'localai') {
    if (!providerForm.value.base_url.trim()) {
      providerForm.value.base_url = 'http://127.0.0.1:8080/v1'
    }
    if (providerForm.value.selected_model === 'gemini-3.5-flash-lite') {
      providerForm.value.selected_model = 'qwen2.5-7b-instruct'
    }
    if (providerForm.value.name.startsWith('Primary Gemini') || providerForm.value.name.startsWith('AI Provider')) {
      providerForm.value.name = 'LocalAI Keyword Assistant'
    }
  }
  else {
    if (providerForm.value.selected_model === 'qwen2.5-7b-instruct') {
      providerForm.value.selected_model = 'gemini-3.5-flash-lite'
    }
    if (providerForm.value.name === 'LocalAI Keyword Assistant') {
      providerForm.value.name = providers.value.length === 0 ? 'Primary Gemini Free' : `AI Provider ${providers.value.length + 1}`
    }
  }
}

function openEditProvider(prov: AiProviderItem) {
  editingProvider.value = prov
  providerForm.value = {
    name: prov.name,
    provider_type: prov.provider_type,
    base_url: prov.base_url || '',
    api_key: '',
    clear_api_key: false,
    selected_model: prov.selected_model,
    default_temperature: prov.default_temperature,
    max_output_tokens: prov.max_output_tokens,
    request_timeout_seconds: prov.request_timeout_seconds,
    max_retry_attempts: prov.max_retry_attempts,
    daily_request_limit: prov.daily_request_limit,
    daily_token_limit: prov.daily_token_limit,
    per_minute_request_limit: prov.per_minute_request_limit,
    generation_enabled: prov.generation_enabled,
    response_caching_enabled: prov.response_caching_enabled,
    token_optimization_enabled: prov.token_optimization_enabled,
    is_default: prov.is_default,
    is_active: prov.is_active,
  }
  providerModalOpen.value = true
}

async function saveProvider() {
  savingProvider.value = true
  try {
    const f = providerForm.value
    if (editingProvider.value) {
      const updated = await request<AiProviderItem>(
        `/api/v1/ai/providers/${editingProvider.value.id}`,
        {
          method: 'PATCH',
          body: {
            name: f.name.trim(),
            provider_type: f.provider_type,
            base_url: f.base_url.trim() || null,
            api_key: f.api_key.trim() || null,
            clear_api_key: f.clear_api_key,
            selected_model: f.selected_model.trim(),
            default_temperature: Number(f.default_temperature),
            max_output_tokens: Number(f.max_output_tokens),
            request_timeout_seconds: Number(f.request_timeout_seconds),
            max_retry_attempts: Number(f.max_retry_attempts),
            daily_request_limit: Number(f.daily_request_limit),
            daily_token_limit: Number(f.daily_token_limit),
            per_minute_request_limit: Number(f.per_minute_request_limit),
            generation_enabled: f.generation_enabled,
            response_caching_enabled: f.response_caching_enabled,
            token_optimization_enabled: f.token_optimization_enabled,
            allow_paid_fallback: false,
            is_default: f.is_default,
            is_active: f.is_active,
          },
        },
      )
      providers.value = providers.value.map((p) => (p.id === updated.id ? updated : p))
      toast.add({ title: `Updated ${updated.name}`, color: 'success' })
    }
    else {
      const created = await request<AiProviderItem>('/api/v1/ai/providers', {
        method: 'POST',
        body: {
          name: f.name.trim(),
          provider_type: f.provider_type,
          base_url: f.base_url.trim() || null,
          api_key: f.api_key.trim() || null,
          selected_model: f.selected_model.trim(),
          default_temperature: Number(f.default_temperature),
          max_output_tokens: Number(f.max_output_tokens),
          request_timeout_seconds: Number(f.request_timeout_seconds),
          max_retry_attempts: Number(f.max_retry_attempts),
          daily_request_limit: Number(f.daily_request_limit),
          daily_token_limit: Number(f.daily_token_limit),
          per_minute_request_limit: Number(f.per_minute_request_limit),
          generation_enabled: f.generation_enabled,
          response_caching_enabled: f.response_caching_enabled,
          token_optimization_enabled: f.token_optimization_enabled,
          allow_paid_fallback: false,
          is_default: f.is_default,
          is_active: f.is_active,
        },
      })
      providers.value = [created, ...providers.value]
      toast.add({ title: `Saved ${created.name}`, color: 'success' })
    }
    providerModalOpen.value = false
    await loadOverviewAndProviders()
  }
  catch (err) {
    toast.add({
      title: 'Provider save failed',
      description: extractErrorMessage(err, 'Check API key format and quota bounds.'),
      color: 'error',
    })
  }
  finally {
    savingProvider.value = false
  }
}

async function runConnectionTest(prov: AiProviderItem) {
  testingProviderId.value = prov.id
  try {
    testResult.value = await request<AiProviderTestResult>(
      `/api/v1/ai/providers/${prov.id}/test`,
      {
        method: 'POST',
        body: { verify_generation: verifyGenOnTest.value },
      },
    )
    const svcLabel = prov.provider_type === 'localai' ? 'LocalAI' : 'Gemini'
    toast.add({
      title: testResult.value.connected ? `${svcLabel} connection verified` : `${svcLabel} test failed`,
      description: testResult.value.connected
        ? `Model ${testResult.value.selected_model} · ${testResult.value.discovered_model_count} models discovered`
        : (testResult.value.error_detail || 'Verify endpoint/credentials and network connectivity.'),
      color: testResult.value.connected ? 'success' : 'error',
    })
    await loadOverviewAndProviders()
  }
  catch (err) {
    toast.add({
      title: 'Test failed',
      description: extractErrorMessage(err, `Could not contact ${prov.provider_type === 'localai' ? 'LocalAI' : 'Gemini'} API.`),
      color: 'error',
    })
  }
  finally {
    testingProviderId.value = null
  }
}

async function refreshProviderModels(prov: AiProviderItem) {
  refreshingModelsId.value = prov.id
  try {
    const res = await request<AiProviderModelsResponse>(
      `/api/v1/ai/providers/${prov.id}/models`,
      { query: { refresh: true } },
    )
    providers.value = providers.value.map((p) =>
      p.id === prov.id ? { ...p, available_models: res.models } : p,
    )
    toast.add({
      title: `Refreshed ${res.models.length} compatible models`,
      description: 'Flash and Flash-Lite models are sorted first for Free-First usage.',
      color: 'success',
    })
  }
  catch (err) {
    toast.add({
      title: 'Model refresh failed',
      description: extractErrorMessage(err, 'Could not fetch Gemini models.'),
      color: 'error',
    })
  }
  finally {
    refreshingModelsId.value = null
  }
}

async function switchProviderModel(prov: AiProviderItem, modelName: string) {
  try {
    const updated = await request<AiProviderItem>(`/api/v1/ai/providers/${prov.id}`, {
      method: 'PATCH',
      body: { selected_model: modelName },
    })
    providers.value = providers.value.map((p) => (p.id === prov.id ? updated : p))
    toast.add({ title: `Selected ${updated.selected_model}`, color: 'success' })
  }
  catch (err) {
    toast.add({
      title: 'Model switch failed',
      description: extractErrorMessage(err, 'Could not update active model.'),
      color: 'error',
    })
  }
}

function openCreatePrompt() {
  editingPrompt.value = null
  previewOutput.value = null
  promptForm.value = {
    template_key: 'custom_multi_platform',
    name: '',
    task_type: 'multi_platform_social',
    platform_key: '',
    website_id: uiStore.selectedWebsiteId ? String(uiStore.selectedWebsiteId) : '',
    system_instructions:
      'Generate structured JSON social media drafts for {{ brand_name }} in {{ language }}. Write naturally without fabricated claims.',
    user_prompt_template:
      'Target Profiles:\n{{ target_profiles_summary }}\n\nWebsite Knowledge:\n{{ website_knowledge }}\n\n<source_content>\n{{ optimized_context }}\n</source_content>',
    change_note: 'Initial custom template',
    is_active: true,
  }
  promptModalOpen.value = true
  void loadSampleContents()
}

function openEditPrompt(tpl: PromptTemplateItem) {
  editingPrompt.value = tpl
  previewOutput.value = null
  promptForm.value = {
    template_key: tpl.template_key,
    name: tpl.name,
    task_type: tpl.task_type,
    platform_key: tpl.platform_key || '',
    website_id: tpl.website_id ? String(tpl.website_id) : '',
    system_instructions: tpl.system_instructions,
    user_prompt_template: tpl.user_prompt_template,
    change_note: '',
    is_active: tpl.is_active,
  }
  previewWebsiteId.value = tpl.website_id ? String(tpl.website_id) : ''
  promptModalOpen.value = true
  void loadSampleContents()
}

async function loadSampleContents() {
  try {
    const res = await request<ContentListResponse>('/api/v1/contents', {
      query: {
        website_id: parseOptionalNumber(previewWebsiteId.value) ?? undefined,
        extraction_status: 'extracted',
        page: 1,
        page_size: 20,
      },
    })
    contentsSample.value = res.items
  }
  catch {
    contentsSample.value = []
  }
}

async function savePrompt() {
  savingPrompt.value = true
  try {
    const f = promptForm.value
    if (editingPrompt.value) {
      const updated = await request<PromptTemplateItem>(
        `/api/v1/ai/prompts/${editingPrompt.value.id}`,
        {
          method: 'PATCH',
          body: {
            name: f.name.trim(),
            system_instructions: f.system_instructions,
            user_prompt_template: f.user_prompt_template,
            is_active: f.is_active,
            change_note: f.change_note.trim() || null,
          },
        },
      )
      prompts.value = prompts.value.map((p) => (p.id === updated.id ? updated : p))
      editingPrompt.value = updated
      toast.add({ title: `Updated ${updated.name} (v${updated.version})`, color: 'success' })
    }
    else {
      const created = await request<PromptTemplateItem>('/api/v1/ai/prompts', {
        method: 'POST',
        body: {
          template_key: f.template_key.trim(),
          name: f.name.trim(),
          task_type: f.task_type,
          platform_key: f.platform_key.trim() || null,
          website_id: parseOptionalNumber(f.website_id),
          system_instructions: f.system_instructions,
          user_prompt_template: f.user_prompt_template,
          is_active: f.is_active,
        },
      })
      prompts.value = [created, ...prompts.value]
      editingPrompt.value = created
      toast.add({ title: `Created ${created.name}`, color: 'success' })
    }
  }
  catch (err) {
    toast.add({
      title: 'Prompt validation failed',
      description: extractErrorMessage(err, 'Verify Jinja2 syntax and allowed variables.'),
      color: 'error',
    })
  }
  finally {
    savingPrompt.value = false
  }
}

async function runOfflinePromptPreview() {
  if (!editingPrompt.value) {
    toast.add({
      title: 'Save template first to preview',
      description: 'Create or open a template, then preview offline without calling Gemini.',
      color: 'warning',
    })
    return
  }
  previewLoading.value = true
  try {
    previewOutput.value = await request<PromptPreviewResult>(
      `/api/v1/ai/prompts/${editingPrompt.value.id}/preview`,
      {
        method: 'POST',
        body: {
          website_id: parseOptionalNumber(previewWebsiteId.value),
          website_content_id: parseOptionalNumber(previewContentId.value),
          context_mode: previewContextMode.value,
          system_instructions_override: promptForm.value.system_instructions,
          user_prompt_template_override: promptForm.value.user_prompt_template,
        },
      },
    )
  }
  catch (err) {
    toast.add({
      title: 'Preview blocked',
      description: extractErrorMessage(err, 'Invalid variable or syntax rejected by Jinja2 sandbox.'),
      color: 'error',
    })
  }
  finally {
    previewLoading.value = false
  }
}

async function openPromptRevisions(tpl: PromptTemplateItem) {
  promptRevisionsOpen.value = true
  try {
    promptRevisions.value = await request<PromptTemplateRevision[]>(
      `/api/v1/ai/prompts/${tpl.id}/revisions`,
    )
  }
  catch (err) {
    toast.add({
      title: 'Could not load prompt history',
      description: extractErrorMessage(err, 'Failed to fetch template revisions.'),
      color: 'error',
    })
  }
}

async function retryJob(jobId: number) {
  try {
    const updated = await request<AiGenerationJob>(`/api/v1/ai/jobs/${jobId}/retry`, {
      method: 'POST',
    })
    jobs.value = jobs.value.map((j) => (j.id === jobId ? updated : j))
    toast.add({ title: `Re-queued AI job #${jobId}`, color: 'success' })
  }
  catch (err) {
    toast.add({
      title: 'Retry failed',
      description: extractErrorMessage(err, 'Could not retry job.'),
      color: 'error',
    })
  }
}

async function cancelJob(jobId: number) {
  try {
    const updated = await request<AiGenerationJob>(`/api/v1/ai/jobs/${jobId}/cancel`, {
      method: 'POST',
    })
    jobs.value = jobs.value.map((j) => (j.id === jobId ? updated : j))
    toast.add({ title: `Cancelled AI job #${jobId}`, color: 'neutral' })
  }
  catch (err) {
    toast.add({
      title: 'Cancel failed',
      description: extractErrorMessage(err, 'Could not cancel job.'),
      color: 'error',
    })
  }
}

async function exportHistoryCsv() {
  exportingCsv.value = true
  try {
    const wid = uiStore.selectedWebsiteId ? `website_id=${uiStore.selectedWebsiteId}&` : ''
    const st = historyStatusFilter.value !== 'all' ? `status=${historyStatusFilter.value}` : ''
    const res = await fetch(`/api/v1/ai/history/export?${wid}${st}`, {
      credentials: 'include',
    })
    if (!res.ok) {
      throw new Error('Failed to export CSV')
    }
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'contenthub-ai-history.csv'
    link.click()
    URL.revokeObjectURL(url)
  }
  catch {
    toast.add({ title: 'CSV export failed', color: 'error' })
  }
  finally {
    exportingCsv.value = false
  }
}

async function invalidateCache(mode: 'expired' | 'website' | 'selected') {
  invalidatingCache.value = true
  try {
    const body =
      mode === 'expired'
        ? { expired_only: true }
        : mode === 'website'
          ? { website_id: uiStore.selectedWebsiteId }
          : { cache_ids: selectedCacheIds.value }

    const res = await request<{ message: string }>('/api/v1/ai/cache/invalidate', {
      method: 'POST',
      body,
    })
    selectedCacheIds.value = []
    toast.add({ title: res.message, color: 'success' })
    await loadOverviewAndProviders()
  }
  catch (err) {
    toast.add({
      title: 'Invalidation failed',
      description: extractErrorMessage(err, 'Could not clear AI cache.'),
      color: 'error',
    })
  }
  finally {
    invalidatingCache.value = false
  }
}

function toggleCacheSelect(cacheId: number, checked: boolean) {
  const next = new Set(selectedCacheIds.value)
  if (checked) {
    next.add(cacheId)
  }
  else {
    next.delete(cacheId)
  }
  selectedCacheIds.value = Array.from(next)
}

watch([() => uiStore.selectedWebsiteId, historyStatusFilter], () => {
  void loadOverviewAndProviders()
})

watch(previewWebsiteId, () => {
  void loadSampleContents()
})

onMounted(() => {
  void loadOverviewAndProviders()
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">
          AI Management Center
        </h1>
        <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          Free-First Gemini & LocalAI provider configuration, Jinja2 prompt templates, token optimization, usage quotas, and SHA-256 response cache.
        </p>
      </div>
      <div class="flex items-center gap-2">
        <UButton
          color="neutral"
          variant="outline"
          size="xs"
          :loading="loading"
          @click="loadOverviewAndProviders"
        >
          <RefreshCw class="mr-1 h-3.5 w-3.5" />
          Refresh
        </UButton>
        <UButton
          color="primary"
          size="xs"
          @click="openCreateProvider"
        >
          <Plus class="mr-1 h-3.5 w-3.5" />
          Add AI Config
        </UButton>
      </div>
    </div>

    <!-- 6 Workspace Tabs -->
    <div class="flex flex-wrap gap-1 border-b border-slate-200 dark:border-slate-800">
      <button
        v-for="tab in [
          { id: 'overview', label: 'Overview' },
          { id: 'providers', label: `AI Configuration (${providers.length})` },
          { id: 'prompts', label: `Prompt Templates (${prompts.length})` },
          { id: 'history', label: `Jobs & History (${jobs.length})` },
          { id: 'usage', label: 'Usage & Quotas' },
          { id: 'cache', label: `Cache (${cacheStats?.active_entries ?? 0})` },
        ]"
        :key="tab.id"
        type="button"
        :class="[
          'border-b-2 px-4 py-2 text-xs font-medium transition-colors',
          activeTab === tab.id
            ? 'border-teal-600 text-teal-700 dark:text-teal-300'
            : 'border-transparent text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100',
        ]"
        @click="activeTab = tab.id as AiTab"
      >
        {{ tab.label }}
      </button>
    </div>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="AI Management unavailable"
      :message="errorMessage"
      retryable
      @retry="loadOverviewAndProviders()"
    />

    <USkeleton
      v-else-if="loading && !usage"
      class="h-64 w-full"
    />

    <!-- TAB 1: OVERVIEW -->
    <div
      v-else-if="activeTab === 'overview' && usage"
      class="space-y-6 text-xs"
    >
      <div class="flex items-start gap-2 rounded-lg border border-teal-200 bg-teal-50/70 px-4 py-3 text-teal-900 dark:border-teal-900/50 dark:bg-teal-950/30 dark:text-teal-200">
        <ShieldCheck class="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <p class="font-semibold">Free-First Safeguards Active</p>
          <p class="mt-0.5 text-[11px]">
            Application quotas cap daily requests/tokens locally, silent paid fallback is permanently disabled, and actual billing status depends on your Google Cloud / Gemini API project tier.
          </p>
        </div>
      </div>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          title="Active Default Provider"
          :value="usage.active_provider_name || 'Unconfigured'"
          :subtitle="usage.active_model || 'Configure Gemini or LocalAI'"
          icon="Sparkles"
          :status="quotaMeta.color"
          :status-label="quotaMeta.label"
        />
        <MetricCard
          title="API Requests Today"
          :value="usage.requests_today"
          :subtitle="`Limit: ${usage.daily_request_limit ?? '—'} · Remaining: ${usage.daily_requests_remaining ?? '—'}`"
          icon="Activity"
        />
        <MetricCard
          title="Cache Savings Today"
          :value="`${usage.cache_hits_today} (${usage.cache_hit_rate_percent}%)`"
          :subtitle="`Active cache entries: ${cacheStats?.active_entries ?? 0}`"
          icon="Workflow"
        />
        <MetricCard
          title="Measured Tokens Today"
          :value="usage.total_measured_tokens_today ?? 'Unavailable'"
          :subtitle="`Month: ${usage.total_measured_tokens_month ?? '—'} · Jobs queued/deferred: ${usage.queued_jobs_count}/${usage.deferred_jobs_count}`"
          icon="BarChart3"
        />
      </div>
    </div>

    <!-- TAB 2: GEMINI CONFIGURATION -->
    <div
      v-else-if="activeTab === 'providers'"
      class="space-y-4 text-xs"
    >
      <div class="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
        <label class="flex cursor-pointer items-center gap-2">
          <input v-model="verifyGenOnTest" type="checkbox">
          <span>Also run tiny live JSON generation probe when clicking Test Connection (uses minimal tokens)</span>
        </label>
        <UButton
          color="primary"
          size="xs"
          @click="openCreateProvider"
        >
          <Plus class="mr-1 h-3.5 w-3.5" />
          New Configuration
        </UButton>
      </div>

      <AppEmptyState
        v-if="providers.length === 0"
        title="No AI configuration created yet"
        description="Add your Gemini API key or a LocalAI endpoint (keys stored Fernet-encrypted), verify connectivity, and choose a model."
      >
        <template #actions>
          <UButton color="primary" size="xs" @click="openCreateProvider">
            Configure AI Provider
          </UButton>
        </template>
      </AppEmptyState>

      <div
        v-for="prov in providers"
        :key="prov.id"
        class="space-y-3 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
      >
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div class="flex flex-wrap items-center gap-2">
              <Sparkles class="h-4 w-4 text-teal-600" />
              <span class="text-sm font-semibold">{{ prov.name }}</span>
              <UBadge
                :color="prov.provider_type === 'localai' ? 'info' : 'neutral'"
                variant="subtle"
                size="xs"
              >
                {{ prov.provider_type === 'localai' ? 'LocalAI' : 'Gemini' }}
              </UBadge>
              <UBadge v-if="prov.is_default" color="primary" variant="subtle" size="xs">
                Default
              </UBadge>
              <HealthStatusBadge :status="prov.last_test_status === 'connected' ? 'ok' : prov.last_test_status" />
            </div>
            <p class="mt-1 flex flex-wrap items-center gap-1.5 font-mono text-[11px] text-slate-500">
              <KeyRound class="h-3 w-3" />
              {{ prov.has_api_key ? `API Key Saved (${prov.masked_api_key})` : (prov.provider_type === 'localai' ? 'No API Key (Local)' : 'API Key Not Stored') }}
              <template v-if="prov.provider_type === 'localai' && prov.base_url">
                · Endpoint: <span>{{ prov.base_url }}</span>
              </template>
              · Model: <strong>{{ prov.selected_model }}</strong>
            </p>
            <p
              v-if="prov.last_test_error"
              class="mt-1 text-rose-600"
            >
              Last Test Error: {{ prov.last_test_error }}
            </p>
          </div>

          <div class="flex flex-wrap gap-1.5">
            <UButton
              color="neutral"
              variant="outline"
              size="xs"
              :loading="refreshingModelsId === prov.id"
              @click="refreshProviderModels(prov)"
            >
              <RefreshCw class="mr-1 h-3 w-3" />
              Refresh Models
            </UButton>
            <UButton
              color="primary"
              variant="subtle"
              size="xs"
              :loading="testingProviderId === prov.id"
              @click="runConnectionTest(prov)"
            >
              <Zap class="mr-1 h-3 w-3" />
              Test Connection
            </UButton>
            <UButton
              color="neutral"
              variant="outline"
              size="xs"
              @click="openEditProvider(prov)"
            >
              Edit
            </UButton>
          </div>
        </div>

        <div class="grid grid-cols-2 gap-3 rounded-md bg-slate-50 p-3 text-[11px] dark:bg-slate-950/60 md:grid-cols-4">
          <div>Daily Requests Cap: <strong>{{ prov.daily_request_limit }}</strong></div>
          <div>Daily Token Cap: <strong>{{ prov.daily_token_limit.toLocaleString() }}</strong></div>
          <div>RPM Cap: <strong>{{ prov.per_minute_request_limit }}/min</strong></div>
          <div>Paid Fallback: <strong class="text-emerald-600">Blocked (Free-First)</strong></div>
        </div>

        <div
          v-if="prov.available_models.length > 0"
          class="flex flex-wrap items-center gap-2 pt-1"
        >
          <span class="font-medium text-slate-500">Active Model:</span>
          <select
            :value="prov.selected_model"
            class="h-8 rounded-md border border-slate-200 bg-white px-2 text-xs dark:border-slate-700 dark:bg-slate-900"
            @change="switchProviderModel(prov, ($event.target as HTMLSelectElement).value)"
          >
            <option
              v-for="m in prov.available_models"
              :key="m.name"
              :value="m.name"
            >
              {{ m.display_name }} ({{ m.name }}){{ m.is_flash_recommended ? ' ★ Recommended' : '' }}
            </option>
          </select>
        </div>
      </div>
    </div>

    <!-- TAB 3: PROMPT TEMPLATES -->
    <div
      v-else-if="activeTab === 'prompts'"
      class="space-y-4 text-xs"
    >
      <div class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
        <p class="text-slate-600 dark:text-slate-300">
          Resolution precedence: <strong>Social Profile</strong> -> <strong>Website + Platform</strong> -> <strong>Website Default</strong> -> <strong>Global Platform</strong> -> <strong>Global Default</strong>. Rendered via restricted Jinja2 sandbox.
        </p>
        <UButton color="primary" size="xs" @click="openCreatePrompt">
          <Plus class="mr-1 h-3.5 w-3.5" />
          New Prompt Template
        </UButton>
      </div>

      <div class="overflow-x-auto rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <table class="min-w-full divide-y divide-slate-200 text-left dark:divide-slate-800">
          <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
            <tr>
              <th class="px-4 py-2.5 font-medium">Name / Key</th>
              <th class="px-4 py-2.5 font-medium">Task Type</th>
              <th class="px-4 py-2.5 font-medium">Scope</th>
              <th class="px-4 py-2.5 font-medium">Version</th>
              <th class="px-4 py-2.5 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
            <tr
              v-for="tpl in prompts"
              :key="tpl.id"
              class="hover:bg-slate-50/70 dark:hover:bg-slate-800/40"
            >
              <td class="px-4 py-2.5">
                <p class="font-medium">{{ tpl.name }}</p>
                <p class="font-mono text-[10px] text-slate-400">{{ tpl.template_key }}</p>
              </td>
              <td class="px-4 py-2.5 font-mono">{{ tpl.task_type }}</td>
              <td class="px-4 py-2.5">
                <UBadge color="neutral" variant="subtle" size="xs">
                  {{ tpl.website_name ? `Site: ${tpl.website_name}` : tpl.platform_key ? `Platform: ${tpl.platform_key}` : 'Global' }}
                </UBadge>
              </td>
              <td class="px-4 py-2.5 font-mono">v{{ tpl.version }}</td>
              <td class="px-4 py-2.5 text-right">
                <div class="flex justify-end gap-1">
                  <UButton color="neutral" variant="outline" size="xs" @click="openPromptRevisions(tpl)">
                    <History class="h-3 w-3" />
                  </UButton>
                  <UButton color="primary" variant="subtle" size="xs" @click="openEditPrompt(tpl)">
                    Edit & Preview
                  </UButton>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- TAB 4: GENERATION JOBS & HISTORY -->
    <div
      v-else-if="activeTab === 'history'"
      class="space-y-6 text-xs"
    >
      <!-- Active & Recent Background Jobs -->
      <section class="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div class="border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          <h2 class="text-sm font-semibold">MySQL AI Generation Job Queue</h2>
        </div>
        <div class="overflow-x-auto">
          <table class="min-w-full divide-y divide-slate-200 text-left dark:divide-slate-800">
            <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
              <tr>
                <th class="px-4 py-2 font-medium">Job</th>
                <th class="px-4 py-2 font-medium">Website / Source</th>
                <th class="px-4 py-2 font-medium">Trigger & Mode</th>
                <th class="px-4 py-2 font-medium">Status</th>
                <th class="px-4 py-2 font-medium">Attempts</th>
                <th class="px-4 py-2 text-right font-medium">Controls</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
              <tr v-for="job in jobs" :key="job.id">
                <td class="px-4 py-2 font-mono">#{{ job.id }}</td>
                <td class="px-4 py-2">
                  <p class="font-medium">{{ job.website_name || `#${job.website_id}` }}</p>
                  <p class="max-w-xs truncate text-[11px] text-slate-500">{{ job.content_title || 'Website task' }}</p>
                </td>
                <td class="px-4 py-2 font-mono text-[11px]">{{ job.trigger_type }} · {{ job.context_mode }}</td>
                <td class="px-4 py-2">
                  <UBadge :color="getJobStatusMeta(job.status).color" variant="subtle" size="xs">
                    {{ getJobStatusMeta(job.status).label }}
                  </UBadge>
                  <p v-if="job.defer_reason || job.error_message" class="mt-0.5 max-w-xs truncate text-[10px] text-slate-500">
                    {{ job.defer_reason || job.error_message }}
                  </p>
                </td>
                <td class="px-4 py-2 font-mono">{{ job.attempt_count }}/{{ job.max_attempts }}</td>
                <td class="px-4 py-2 text-right">
                  <div class="flex justify-end gap-1">
                    <UButton
                      v-if="['failed', 'deferred', 'partially_completed', 'cancelled'].includes(job.status)"
                      color="primary"
                      variant="subtle"
                      size="xs"
                      @click="retryJob(job.id)"
                    >
                      <RotateCcw class="h-3 w-3" />
                    </UButton>
                    <UButton
                      v-if="['queued', 'deferred', 'processing'].includes(job.status)"
                      color="error"
                      variant="ghost"
                      size="xs"
                      @click="cancelJob(job.id)"
                    >
                      <PauseCircle class="h-3 w-3" />
                    </UButton>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Gemini API & Cache Invocation Logs -->
      <section class="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          <h2 class="text-sm font-semibold">Invocation & Token Audit Log</h2>
          <div class="flex items-center gap-2">
            <select
              v-model="historyStatusFilter"
              class="h-8 rounded-md border border-slate-200 bg-white px-2 text-xs dark:border-slate-700 dark:bg-slate-900"
            >
              <option value="all">All Statuses</option>
              <option value="succeeded">Succeeded</option>
              <option value="failed">Failed</option>
              <option value="rate_limited">Rate Limited</option>
              <option value="quota_blocked">Quota Blocked</option>
              <option value="invalid_response">Invalid Output</option>
            </select>
            <UButton
              color="neutral"
              variant="outline"
              size="xs"
              :loading="exportingCsv"
              @click="exportHistoryCsv"
            >
              <Download class="mr-1 h-3.5 w-3.5" />
              Export CSV
            </UButton>
          </div>
        </div>
        <div class="overflow-x-auto">
          <table class="min-w-full divide-y divide-slate-200 text-left dark:divide-slate-800">
            <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
              <tr>
                <th class="px-4 py-2 font-medium">When</th>
                <th class="px-4 py-2 font-medium">Task / Website</th>
                <th class="px-4 py-2 font-medium">Model & Mode</th>
                <th class="px-4 py-2 font-medium">Status</th>
                <th class="px-4 py-2 font-medium">Tokens (Est / Meas)</th>
                <th class="px-4 py-2 font-medium">Latency</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
              <tr v-for="row in historyLogs" :key="row.id">
                <td class="px-4 py-2 whitespace-nowrap text-slate-500">{{ formatDateTime(row.created_at) }}</td>
                <td class="px-4 py-2">
                  <span class="font-medium">{{ row.task_type }}</span>
                  <span v-if="row.website_name" class="block text-[10px] text-slate-500">{{ row.website_name }}</span>
                </td>
                <td class="px-4 py-2 font-mono text-[11px]">
                  {{ row.model_name }} · {{ row.context_mode }}
                  <UBadge v-if="row.cache_hit" color="info" variant="subtle" size="xs" class="ml-1">
                    Cache Hit
                  </UBadge>
                </td>
                <td class="px-4 py-2 font-mono">{{ row.status }}</td>
                <td class="px-4 py-2 font-mono text-[11px]">
                  Est: {{ row.estimated_input_tokens ?? '—' }} ·
                  Meas: {{ row.total_measured_tokens ?? row.token_usage_status }}
                </td>
                <td class="px-4 py-2 font-mono">{{ row.latency_ms !== null ? `${row.latency_ms}ms` : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>

    <!-- TAB 5: USAGE & QUOTAS -->
    <div
      v-else-if="activeTab === 'usage' && usage"
      class="space-y-4 text-xs"
    >
      <div class="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <p class="font-semibold">Cost Transparency Note</p>
        <p class="mt-1 text-slate-500">{{ usage.cost_note }}</p>
      </div>

      <div class="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div
          v-for="(rows, label) in {
            'Usage by Website': usage.usage_by_website,
            'Usage by Model': usage.usage_by_model,
            'Usage by Task': usage.usage_by_task_type,
          }"
          :key="label"
          class="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
        >
          <h3 class="mb-2 text-sm font-semibold">{{ label }}</h3>
          <p v-if="rows.length === 0" class="text-slate-400">No usage recorded yet.</p>
          <div
            v-for="item in rows"
            :key="item.key"
            class="flex items-center justify-between border-t border-slate-100 py-1.5 dark:border-slate-800"
          >
            <span class="truncate font-medium">{{ item.label }}</span>
            <span class="font-mono text-[11px] text-slate-500">
              {{ item.requests }} req · {{ item.cache_hits }} hit · {{ item.measured_tokens }} tok
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 6: CACHE MANAGEMENT -->
    <div
      v-else-if="activeTab === 'cache' && cacheStats"
      class="space-y-4 text-xs"
    >
      <div class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
        <div class="flex items-center gap-3">
          <Database class="h-4 w-4 text-teal-600" />
          <span>
            Active: <strong>{{ cacheStats.active_entries }}</strong> · Expired: <strong>{{ cacheStats.expired_entries }}</strong> · Hits: <strong>{{ cacheStats.total_hits }}</strong>
          </span>
        </div>
        <div class="flex flex-wrap gap-2">
          <UButton
            color="neutral"
            variant="outline"
            size="xs"
            :loading="invalidatingCache"
            @click="invalidateCache('expired')"
          >
            Clear Expired
          </UButton>
          <UButton
            v-if="uiStore.selectedWebsiteId"
            color="warning"
            variant="subtle"
            size="xs"
            :loading="invalidatingCache"
            @click="invalidateCache('website')"
          >
            Invalidate Selected Website
          </UButton>
          <UButton
            v-if="selectedCacheIds.length > 0"
            color="error"
            size="xs"
            :loading="invalidatingCache"
            @click="invalidateCache('selected')"
          >
            <Trash2 class="mr-1 h-3 w-3" />
            Delete Selected ({{ selectedCacheIds.length }})
          </UButton>
        </div>
      </div>

      <div class="overflow-x-auto rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <table class="min-w-full divide-y divide-slate-200 text-left dark:divide-slate-800">
          <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
            <tr>
              <th class="px-3 py-2" />
              <th class="px-4 py-2 font-medium">Website / Task</th>
              <th class="px-4 py-2 font-medium">Model & Mode</th>
              <th class="px-4 py-2 font-medium">Hits</th>
              <th class="px-4 py-2 font-medium">Expires</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
            <tr v-for="entry in cacheStats.entries" :key="entry.id">
              <td class="px-3 py-2">
                <input
                  type="checkbox"
                  :checked="selectedCacheIds.includes(entry.id)"
                  @change="toggleCacheSelect(entry.id, ($event.target as HTMLInputElement).checked)"
                >
              </td>
              <td class="px-4 py-2">
                <p class="font-medium">{{ entry.website_name || `Website #${entry.website_id}` }}</p>
                <p class="font-mono text-[10px] text-slate-400">{{ entry.task_type }} · {{ entry.cache_key_hash.slice(0, 14) }}…</p>
              </td>
              <td class="px-4 py-2 font-mono text-[11px]">{{ entry.model_name }} · {{ entry.context_mode }} ({{ entry.language }})</td>
              <td class="px-4 py-2 font-mono">{{ entry.hit_count }}</td>
              <td class="px-4 py-2 whitespace-nowrap text-slate-500">{{ formatDateTime(entry.expires_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- AI Provider Modal -->
    <UModal
      v-model:open="providerModalOpen"
      :title="editingProvider ? `Edit ${editingProvider.name}` : 'Add AI Configuration'"
    >
      <template #body>
        <form class="max-h-[75vh] space-y-3 overflow-y-auto pr-1 text-xs" @submit.prevent="saveProvider">
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label class="mb-1 block font-medium">AI Service *</label>
              <select
                v-model="providerForm.provider_type"
                class="h-9 w-full rounded-md border border-slate-200 px-2.5 text-xs dark:border-slate-700 dark:bg-slate-900"
                @change="handleProviderTypeChange"
              >
                <option value="gemini">Gemini</option>
                <option value="localai">LocalAI</option>
              </select>
            </div>
            <div v-if="providerForm.provider_type === 'localai'">
              <label class="mb-1 block font-medium">LocalAI API Base URL</label>
              <UInput v-model="providerForm.base_url" size="sm" placeholder="http://127.0.0.1:8080/v1" />
            </div>
            <div>
              <label class="mb-1 block font-medium">Configuration Name *</label>
              <UInput v-model="providerForm.name" size="sm" required />
            </div>
            <div>
              <label class="mb-1 block font-medium">Default Model *</label>
              <UInput v-model="providerForm.selected_model" size="sm" required />
            </div>
          </div>

          <div>
            <div class="mb-1 flex items-center justify-between">
              <label class="font-medium">
                {{ providerForm.provider_type === 'localai' ? 'LocalAI API Key / Token (Optional, Fernet-Encrypted)' : 'Gemini API Key (Fernet-Encrypted)' }}
              </label>
              <span v-if="editingProvider?.masked_api_key" class="font-mono text-[10px] text-teal-600">
                Current: {{ editingProvider.masked_api_key }}
              </span>
            </div>
            <UInput
              v-model="providerForm.api_key"
              type="password"
              size="sm"
              autocomplete="off"
              :placeholder="editingProvider ? 'Leave blank to keep stored key' : (providerForm.provider_type === 'localai' ? 'Optional Bearer token' : 'AIza...')"
            />
            <label v-if="editingProvider?.has_api_key" class="mt-1 inline-flex items-center gap-1 text-[10px] text-rose-600">
              <input v-model="providerForm.clear_api_key" type="checkbox">
              Clear stored API key
            </label>
          </div>

          <div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <div>
              <label class="mb-1 block font-medium">Daily Request Cap</label>
              <UInput v-model.number="providerForm.daily_request_limit" type="number" size="sm" />
            </div>
            <div>
              <label class="mb-1 block font-medium">Daily Token Cap</label>
              <UInput v-model.number="providerForm.daily_token_limit" type="number" size="sm" />
            </div>
            <div>
              <label class="mb-1 block font-medium">Requests / Minute</label>
              <UInput v-model.number="providerForm.per_minute_request_limit" type="number" size="sm" />
            </div>
            <div>
              <label class="mb-1 block font-medium">Max Output Tokens</label>
              <UInput v-model.number="providerForm.max_output_tokens" type="number" size="sm" />
            </div>
            <div>
              <label class="mb-1 block font-medium">Timeout (sec)</label>
              <UInput v-model.number="providerForm.request_timeout_seconds" type="number" size="sm" />
            </div>
            <div>
              <label class="mb-1 block font-medium">Temperature</label>
              <UInput v-model.number="providerForm.default_temperature" type="number" step="0.1" size="sm" />
            </div>
          </div>

          <div class="grid grid-cols-2 gap-2 rounded-md border border-slate-200 p-3 dark:border-slate-700">
            <label class="flex cursor-pointer items-center gap-2">
              <USwitch v-model="providerForm.is_default" size="xs" />
              <span>Set as Default</span>
            </label>
            <label class="flex cursor-pointer items-center gap-2">
              <USwitch v-model="providerForm.generation_enabled" size="xs" />
              <span>Enable Generation</span>
            </label>
            <label class="flex cursor-pointer items-center gap-2">
              <USwitch v-model="providerForm.response_caching_enabled" size="xs" />
              <span>Response Caching</span>
            </label>
            <label class="flex cursor-pointer items-center gap-2">
              <USwitch v-model="providerForm.token_optimization_enabled" size="xs" />
              <span>Python Token Digest</span>
            </label>
          </div>

          <div class="flex justify-end gap-2 pt-2">
            <UButton type="button" color="neutral" variant="outline" size="sm" @click="providerModalOpen = false">
              Cancel
            </UButton>
            <UButton type="submit" color="primary" size="sm" :loading="savingProvider">
              {{ providerForm.provider_type === 'localai' ? 'Save LocalAI Configuration' : 'Save Gemini Configuration' }}
            </UButton>
          </div>
        </form>
      </template>
    </UModal>

    <!-- Prompt Template Editor & Offline Preview Modal -->
    <UModal
      v-model:open="promptModalOpen"
      :title="editingPrompt ? `Edit Template: ${editingPrompt.name}` : 'Create Prompt Template'"
    >
      <template #body>
        <div class="max-h-[80vh] space-y-4 overflow-y-auto pr-1 text-xs">
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label class="mb-1 block font-medium">Template Name *</label>
              <UInput v-model="promptForm.name" size="sm" />
            </div>
            <div v-if="!editingPrompt">
              <label class="mb-1 block font-medium">Template Key *</label>
              <UInput v-model="promptForm.template_key" size="sm" />
            </div>
            <div v-if="!editingPrompt">
              <label class="mb-1 block font-medium">Task Type *</label>
              <select
                v-model="promptForm.task_type"
                class="h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-xs dark:border-slate-700 dark:bg-slate-900"
              >
                <option v-for="t in PROMPT_TASK_TYPE_OPTIONS" :key="t.value" :value="t.value">
                  {{ t.label }}
                </option>
              </select>
            </div>
            <div v-if="!editingPrompt">
              <label class="mb-1 block font-medium">Website Scope (Optional)</label>
              <select
                v-model="promptForm.website_id"
                class="h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-xs dark:border-slate-700 dark:bg-slate-900"
              >
                <option value="">Global Template</option>
                <option v-for="s in uiStore.websitesCatalog" :key="s.id" :value="String(s.id)">
                  {{ s.name }}
                </option>
              </select>
            </div>
          </div>

          <div class="rounded bg-slate-50 p-2 font-mono text-[10px] text-slate-600 dark:bg-slate-950/60 dark:text-slate-300">
            Allowed Variables: website_name, brand_name, website_category, website_url, website_knowledge, content_title, content_url, meta_description, optimized_context, keywords, language, tone, profile_name, platform, character_limit, hashtags, cta, custom_instructions, target_profiles_summary, content_restrictions
          </div>

          <div>
            <label class="mb-1 block font-medium">System Instructions</label>
            <UTextarea v-model="promptForm.system_instructions" :rows="3" size="sm" />
          </div>
          <div>
            <label class="mb-1 block font-medium">User Prompt Template (Jinja2 Sandboxed)</label>
            <UTextarea v-model="promptForm.user_prompt_template" :rows="5" size="sm" />
          </div>
          <div v-if="editingPrompt">
            <label class="mb-1 block font-medium">Revision Change Note</label>
            <UInput v-model="promptForm.change_note" size="sm" placeholder="Optional note for revision history" />
          </div>

          <div class="flex flex-wrap justify-between gap-2">
            <UButton
              v-if="editingPrompt"
              color="neutral"
              variant="outline"
              size="xs"
              :loading="previewLoading"
              @click="runOfflinePromptPreview"
            >
              <Eye class="mr-1 h-3.5 w-3.5" />
              Preview Offline (Zero AI Tokens)
            </UButton>
            <div class="flex gap-2">
              <UButton color="neutral" variant="outline" size="xs" @click="promptModalOpen = false">
                Close
              </UButton>
              <UButton color="primary" size="xs" :loading="savingPrompt" @click="savePrompt">
                <Play class="mr-1 h-3.5 w-3.5" />
                Save Prompt
              </UButton>
            </div>
          </div>

          <!-- Offline Preview Controls & Output -->
          <div
            v-if="editingPrompt"
            class="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700"
          >
            <p class="font-semibold">Offline Preview Inputs</p>
            <div class="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <select
                v-model="previewWebsiteId"
                class="h-8 rounded border border-slate-200 bg-white px-2 text-xs dark:border-slate-700 dark:bg-slate-900"
              >
                <option value="">Sample Website</option>
                <option v-for="s in uiStore.websitesCatalog" :key="s.id" :value="String(s.id)">
                  {{ s.name }}
                </option>
              </select>
              <select
                v-model="previewContentId"
                class="h-8 rounded border border-slate-200 bg-white px-2 text-xs dark:border-slate-700 dark:bg-slate-900"
              >
                <option value="">Sample Article</option>
                <option v-for="c in contentsSample" :key="c.id" :value="String(c.id)">
                  {{ c.title }}
                </option>
              </select>
              <select
                v-model="previewContextMode"
                class="h-8 rounded border border-slate-200 bg-white px-2 text-xs dark:border-slate-700 dark:bg-slate-900"
              >
                <option v-for="opt in CONTEXT_MODE_OPTIONS" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
            </div>
            <div v-if="previewOutput" class="space-y-2 pt-2">
              <p class="font-mono text-[11px] text-teal-600">
                Estimated Input Tokens: ~{{ previewOutput.estimated_input_tokens }} ({{ previewOutput.context_mode }})
              </p>
              <pre class="max-h-40 overflow-y-auto whitespace-pre-wrap rounded bg-slate-50 p-2 font-mono text-[11px] dark:bg-slate-950/60">{{ previewOutput.user_prompt }}</pre>
            </div>
          </div>
        </div>
      </template>
    </UModal>

    <!-- Prompt Revisions Modal -->
    <UModal v-model:open="promptRevisionsOpen" title="Prompt Template Revisions">
      <template #body>
        <div class="max-h-96 space-y-2.5 overflow-y-auto text-xs">
          <div
            v-for="rev in promptRevisions"
            :key="rev.id"
            class="rounded border border-slate-200 p-3 dark:border-slate-700"
          >
            <div class="flex items-center justify-between font-semibold">
              <span>v{{ rev.version }}</span>
              <span class="font-normal text-slate-500">{{ formatDateTime(rev.created_at) }}</span>
            </div>
            <p v-if="rev.change_note" class="mt-0.5 text-[11px] text-teal-600">{{ rev.change_note }}</p>
            <pre class="mt-2 whitespace-pre-wrap rounded bg-slate-50 p-2 font-mono text-[11px] dark:bg-slate-950/60">{{ rev.user_prompt_template }}</pre>
          </div>
        </div>
      </template>
    </UModal>
  </div>
</template>
