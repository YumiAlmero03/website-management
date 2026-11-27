<script setup lang="ts">
import { ArrowLeft, Compass, Play, RefreshCw, RotateCw, Wifi } from 'lucide-vue-next'
import type {
  ArticleListResponse,
  ScanLog,
  ScanLogListResponse,
  Website,
  WebsiteConnectivity,
  WebsiteDiscoverResult,
} from '~/types/api'
import { extractErrorMessage, formatDateTime } from '~/utils/format'

const route = useRoute()
const { request } = useApiClient()
const toast = useToast()

const websiteId = computed(() => Number(route.params.id))

const website = ref<Website | null>(null)
const scanLogs = ref<ScanLogListResponse | null>(null)
const articles = ref<ArticleListResponse | null>(null)
const activeScan = ref<ScanLog | null>(null)
const connectivityResult = ref<WebsiteConnectivity | null>(null)
const discoveryResult = ref<WebsiteDiscoverResult | null>(null)

const loading = ref(true)
const testing = ref(false)
const discovering = ref(false)
const startingScan = ref(false)
const retryingScanId = ref<number | null>(null)
const errorMessage = ref<string | null>(null)
const activeTab = ref<'overview' | 'articles' | 'history' | 'discovery'>('overview')

let pollTimer: ReturnType<typeof setInterval> | null = null

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function pollActiveScan(scanId: number) {
  try {
    const latest = await request<ScanLog>(`/api/v1/scans/${scanId}`)
    activeScan.value = latest
    if (!['pending', 'processing'].includes(latest.status)) {
      stopPolling()
      await Promise.all([loadWebsiteData(false)])
      toast.add({
        title: `Scan #${latest.id} ${latest.status}`,
        description: `New: ${latest.new_articles}, Updated: ${latest.updated_articles}, Failed: ${latest.failed_articles}`,
        color: latest.status === 'failed' ? 'error' : 'success',
      })
    }
  }
  catch {
    stopPolling()
  }
}

function startPolling(scanId: number) {
  stopPolling()
  void pollActiveScan(scanId)
  pollTimer = setInterval(() => {
    void pollActiveScan(scanId)
  }, 2500)
}

async function loadWebsiteData(showSpinner = true) {
  if (showSpinner) {
    loading.value = true
  }
  errorMessage.value = null
  try {
    const [siteRes, logsRes, articlesRes] = await Promise.all([
      request<Website>(`/api/v1/websites/${websiteId.value}`),
      request<ScanLogListResponse>(`/api/v1/websites/${websiteId.value}/scan-logs`, {
        query: { page: 1, page_size: 20 },
      }),
      request<ArticleListResponse>('/api/v1/articles', {
        query: { website_id: websiteId.value, page: 1, page_size: 20 },
      }),
    ])
    website.value = siteRes
    scanLogs.value = logsRes
    articles.value = articlesRes

    const running = logsRes.items.find((s) => s.status === 'pending' || s.status === 'processing')
    if (running) {
      activeScan.value = running
      startPolling(running.id)
    }
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to load website details.')
  }
  finally {
    loading.value = false
  }
}

async function runConnectivityTest() {
  testing.value = true
  try {
    connectivityResult.value = await request<WebsiteConnectivity>(
      `/api/v1/websites/${websiteId.value}/test`,
      { method: 'POST' },
    )
    activeTab.value = 'discovery'
    toast.add({
      title: connectivityResult.value.reachable ? 'Website reachable' : 'Connectivity issue',
      description: connectivityResult.value.reachable
        ? `HTTP ${connectivityResult.value.status_code} (${connectivityResult.value.detected_website_type || 'detected'})`
        : (connectivityResult.value.error || 'Could not reach target website.'),
      color: connectivityResult.value.reachable ? 'success' : 'error',
    })
  }
  catch (err) {
    toast.add({ title: 'Test failed', description: extractErrorMessage(err), color: 'error' })
  }
  finally {
    testing.value = false
  }
}

async function runDiscovery(applyDetected: boolean) {
  discovering.value = true
  try {
    discoveryResult.value = await request<WebsiteDiscoverResult>(
      `/api/v1/websites/${websiteId.value}/discover`,
      { method: 'POST', query: { apply: applyDetected } },
    )
    activeTab.value = 'discovery'
    if (applyDetected) {
      await loadWebsiteData(false)
    }
    toast.add({
      title: applyDetected ? 'Sources discovered & applied' : 'Sources discovered',
      description: `Recommended method: ${discoveryResult.value.recommended_method}`,
      color: 'success',
    })
  }
  catch (err) {
    toast.add({ title: 'Discovery failed', description: extractErrorMessage(err), color: 'error' })
  }
  finally {
    discovering.value = false
  }
}

async function triggerManualScan() {
  startingScan.value = true
  try {
    const scan = await request<ScanLog>(`/api/v1/websites/${websiteId.value}/scan`, {
      method: 'POST',
    })
    activeScan.value = scan
    startPolling(scan.id)
    toast.add({
      title: `Scan #${scan.id} started`,
      description: 'Running in background without blocking dashboard requests.',
      color: 'success',
    })
  }
  catch (err) {
    toast.add({ title: 'Could not start scan', description: extractErrorMessage(err), color: 'error' })
  }
  finally {
    startingScan.value = false
  }
}

async function retryFailedScan(scanId: number) {
  retryingScanId.value = scanId
  try {
    const scan = await request<ScanLog>(`/api/v1/scans/${scanId}/retry`, { method: 'POST' })
    activeScan.value = scan
    startPolling(scan.id)
    toast.add({ title: `Retry scan #${scan.id} queued`, color: 'success' })
  }
  catch (err) {
    toast.add({ title: 'Retry failed', description: extractErrorMessage(err), color: 'error' })
  }
  finally {
    retryingScanId.value = null
  }
}

onMounted(async () => {
  await loadWebsiteData(true)
  const queryScanId = Number(route.query.scan)
  if (Number.isFinite(queryScanId) && queryScanId > 0) {
    startPolling(queryScanId)
  }
})

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <UButton
        to="/websites"
        color="neutral"
        variant="outline"
        size="xs"
      >
        <ArrowLeft class="mr-1 h-3.5 w-3.5" />
        Back to Websites
      </UButton>

      <div
        v-if="website"
        class="flex flex-wrap items-center gap-2"
      >
        <UButton
          color="neutral"
          variant="outline"
          size="xs"
          :loading="testing"
          @click="runConnectivityTest"
        >
          <Wifi class="mr-1 h-3.5 w-3.5" />
          Test Connectivity
        </UButton>
        <UButton
          color="neutral"
          variant="outline"
          size="xs"
          :loading="discovering"
          @click="runDiscovery(false)"
        >
          <Compass class="mr-1 h-3.5 w-3.5" />
          Preview Sources
        </UButton>
        <UButton
          color="primary"
          size="xs"
          :loading="startingScan"
          :disabled="Boolean(activeScan && ['pending', 'processing'].includes(activeScan.status))"
          @click="triggerManualScan"
        >
          <Play class="mr-1 h-3.5 w-3.5" />
          Trigger Manual Scan
        </UButton>
      </div>
    </div>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="Website unavailable"
      :message="errorMessage"
      retryable
      @retry="loadWebsiteData(true)"
    />

    <USkeleton
      v-if="loading"
      class="h-64 w-full"
    />

    <template v-else-if="website">
      <!-- Header Card -->
      <div class="rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div class="flex items-center gap-2">
              <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">
                {{ website.name }}
              </h1>
              <HealthStatusBadge :status="website.status" />
            </div>
            <p class="mt-0.5 font-mono text-xs text-slate-500">
              https://{{ website.domain }} · Brand: {{ website.brand_name || `#${website.brand_id}` }} · {{ website.website_type }}
            </p>
          </div>
          <div class="text-right text-xs text-slate-500">
            <p>Articles Stored: <strong class="text-slate-900 dark:text-slate-100">{{ website.article_count }}</strong></p>
            <p>Baseline: <strong class="text-slate-900 dark:text-slate-100">{{ website.initial_scan_completed ? 'Established' : `Pending (${website.baseline_mode})` }}</strong></p>
          </div>
        </div>
      </div>

      <!-- Live Scan Progress Banner (Real Polled Counters — Zero Fabricated Percentages) -->
      <div
        v-if="activeScan"
        class="rounded-lg border border-teal-200 bg-teal-50/70 p-4 dark:border-teal-900 dark:bg-teal-950/40"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="flex items-center gap-2">
            <RefreshCw
              v-if="['pending', 'processing'].includes(activeScan.status)"
              class="h-4 w-4 animate-spin text-teal-700 dark:text-teal-300"
            />
            <span class="text-sm font-semibold text-teal-950 dark:text-teal-100">
              Scan #{{ activeScan.id }} ({{ activeScan.trigger_type }} · {{ activeScan.scan_method }})
            </span>
            <HealthStatusBadge
              :status="activeScan.status === 'completed' ? 'ok' : activeScan.status === 'partially_completed' ? 'warning' : activeScan.status"
              :label="activeScan.status"
            />
          </div>
          <span class="font-mono text-xs text-teal-800 dark:text-teal-200">
            {{ activeScan.duration_ms !== null ? `Duration: ${(activeScan.duration_ms / 1000).toFixed(1)}s` : 'Polling live status...' }}
          </span>
        </div>

        <div class="mt-3 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4 lg:grid-cols-7">
          <div class="rounded bg-white/80 p-2 dark:bg-slate-900/70">
            <p class="text-slate-500">URLs Found</p>
            <p class="font-semibold">{{ activeScan.urls_found }}</p>
          </div>
          <div class="rounded bg-white/80 p-2 dark:bg-slate-900/70">
            <p class="text-slate-500">Processed</p>
            <p class="font-semibold">{{ activeScan.articles_processed }}</p>
          </div>
          <div class="rounded bg-white/80 p-2 dark:bg-slate-900/70">
            <p class="text-slate-500">New</p>
            <p class="font-semibold text-emerald-700 dark:text-emerald-400">{{ activeScan.new_articles }}</p>
          </div>
          <div class="rounded bg-white/80 p-2 dark:bg-slate-900/70">
            <p class="text-slate-500">Updated</p>
            <p class="font-semibold text-blue-700 dark:text-blue-400">{{ activeScan.updated_articles }}</p>
          </div>
          <div class="rounded bg-white/80 p-2 dark:bg-slate-900/70">
            <p class="text-slate-500">Unchanged</p>
            <p class="font-semibold">{{ activeScan.unchanged_articles }}</p>
          </div>
          <div class="rounded bg-white/80 p-2 dark:bg-slate-900/70">
            <p class="text-slate-500">Skipped</p>
            <p class="font-semibold">{{ activeScan.skipped_articles }}</p>
          </div>
          <div class="rounded bg-white/80 p-2 dark:bg-slate-900/70">
            <p class="text-slate-500">Failed</p>
            <p class="font-semibold text-red-600 dark:text-red-400">{{ activeScan.failed_articles }}</p>
          </div>
        </div>

        <p
          v-if="activeScan.error_message"
          class="mt-2 text-xs text-red-700 dark:text-red-300"
        >
          Error: {{ activeScan.error_message }}
        </p>
      </div>

      <!-- Tabs -->
      <div class="flex flex-wrap gap-2 border-b border-slate-200 pb-2 dark:border-slate-800">
        <UButton
          v-for="tab in [
            { id: 'overview', label: 'Overview & Config' },
            { id: 'articles', label: `Discovered Articles (${articles?.meta.total_items || 0})` },
            { id: 'history', label: `Scan History (${scanLogs?.meta.total_items || 0})` },
            { id: 'discovery', label: 'Discovery Source Preview' },
          ] as const"
          :key="tab.id"
          :color="activeTab === tab.id ? 'primary' : 'neutral'"
          :variant="activeTab === tab.id ? 'solid' : 'ghost'"
          size="xs"
          @click="activeTab = tab.id"
        >
          {{ tab.label }}
        </UButton>
      </div>

      <!-- Overview & Configuration -->
      <div
        v-if="activeTab === 'overview'"
        class="rounded-lg border border-slate-200 bg-white p-5 text-xs dark:border-slate-800 dark:bg-slate-900"
      >
        <dl class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div>
            <dt class="text-slate-400">Discovery Method</dt>
            <dd class="mt-0.5 font-mono font-medium">{{ website.discovery_method }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">Scan Frequency</dt>
            <dd class="mt-0.5 font-medium">
              Every {{ website.scan_interval_minutes }} min (Auto-scan: {{ website.auto_scan ? 'Enabled' : 'Disabled' }})
            </dd>
          </div>
          <div>
            <dt class="text-slate-400">Next Scheduled Scan</dt>
            <dd class="mt-0.5 font-medium">{{ formatDateTime(website.next_scan_at) }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">RSS / Atom URL</dt>
            <dd class="mt-0.5 break-all font-mono">{{ website.rss_url || '-' }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">Sitemap URL</dt>
            <dd class="mt-0.5 break-all font-mono">{{ website.sitemap_url || '-' }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">llms.txt / API Endpoint</dt>
            <dd class="mt-0.5 break-all font-mono">
              {{ website.llms_url || '-' }}<br>{{ website.api_endpoint || '-' }}
            </dd>
          </div>
          <div>
            <dt class="text-slate-400">Included URL Patterns</dt>
            <dd class="mt-0.5 font-mono">
              {{ website.article_url_patterns.length ? website.article_url_patterns.join(', ') : 'All non-root same-site URLs' }}
            </dd>
          </div>
          <div>
            <dt class="text-slate-400">Excluded URL Patterns</dt>
            <dd class="mt-0.5 font-mono">
              {{ website.excluded_url_patterns.length ? website.excluded_url_patterns.join(', ') : 'Default exclusions only' }}
            </dd>
          </div>
          <div>
            <dt class="text-slate-400">Last Successful Scan</dt>
            <dd class="mt-0.5 font-medium">{{ formatDateTime(website.last_successful_scan_at) }}</dd>
          </div>
        </dl>
      </div>

      <!-- Discovered Articles -->
      <div
        v-else-if="activeTab === 'articles'"
        class="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
      >
        <div
          v-if="!articles || articles.items.length === 0"
          class="p-6"
        >
          <AppEmptyState
            title="No articles discovered for this website yet"
            description="Trigger a manual scan to discover and extract articles into your Content Library."
          />
        </div>
        <div
          v-else
          class="overflow-x-auto"
        >
          <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
            <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
              <tr>
                <th class="px-4 py-2.5 font-medium">Title</th>
                <th class="px-4 py-2.5 font-medium">Status</th>
                <th class="px-4 py-2.5 font-medium">Words</th>
                <th class="px-4 py-2.5 font-medium">Published</th>
                <th class="px-4 py-2.5 font-medium">Discovered</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
              <tr
                v-for="art in articles.items"
                :key="art.id"
              >
                <td class="px-4 py-2.5">
                  <NuxtLink
                    :to="`/content-library/${art.id}`"
                    class="font-medium text-teal-700 hover:underline dark:text-teal-300"
                  >
                    {{ art.title }}
                  </NuxtLink>
                </td>
                <td class="px-4 py-2.5">
                  <HealthStatusBadge :status="art.status === 'optimized' || art.status === 'extracted' ? 'ok' : art.status" :label="art.status" />
                </td>
                <td class="px-4 py-2.5">{{ art.word_count }}</td>
                <td class="px-4 py-2.5 text-slate-500">{{ formatDateTime(art.published_at) }}</td>
                <td class="px-4 py-2.5 text-slate-500">{{ formatDateTime(art.discovered_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Scan History -->
      <div
        v-else-if="activeTab === 'history'"
        class="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
      >
        <div
          v-if="!scanLogs || scanLogs.items.length === 0"
          class="p-6"
        >
          <AppEmptyState
            title="No scan logs recorded"
            description="Every manual, scheduled, and retried scan will appear here."
          />
        </div>
        <div
          v-else
          class="overflow-x-auto"
        >
          <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
            <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
              <tr>
                <th class="px-4 py-2.5 font-medium">ID</th>
                <th class="px-4 py-2.5 font-medium">Method / Trigger</th>
                <th class="px-4 py-2.5 font-medium">Status</th>
                <th class="px-4 py-2.5 font-medium">Found / New / Updated / Failed</th>
                <th class="px-4 py-2.5 font-medium">Duration</th>
                <th class="px-4 py-2.5 font-medium">Started</th>
                <th class="px-4 py-2.5 font-medium text-right">Action</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
              <tr
                v-for="log in scanLogs.items"
                :key="log.id"
              >
                <td class="px-4 py-2.5 font-mono">#{{ log.id }}</td>
                <td class="px-4 py-2.5 font-mono text-[11px]">{{ log.scan_method }} / {{ log.trigger_type }}</td>
                <td class="px-4 py-2.5">
                  <HealthStatusBadge :status="log.status === 'completed' ? 'ok' : log.status === 'partially_completed' ? 'warning' : log.status" :label="log.status" />
                  <p
                    v-if="log.error_message"
                    class="mt-1 max-w-xs truncate text-[11px] text-red-600 dark:text-red-400"
                    :title="log.error_message"
                  >
                    {{ log.error_message }}
                  </p>
                </td>
                <td class="px-4 py-2.5 font-mono text-[11px]">
                  {{ log.urls_found }} / +{{ log.new_articles }} / ~{{ log.updated_articles }} / !{{ log.failed_articles }}
                </td>
                <td class="px-4 py-2.5 text-slate-500">
                  {{ log.duration_ms !== null ? `${(log.duration_ms / 1000).toFixed(1)}s` : '-' }}
                </td>
                <td class="px-4 py-2.5 text-slate-500">{{ formatDateTime(log.started_at || log.created_at) }}</td>
                <td class="px-4 py-2.5 text-right">
                  <UButton
                    v-if="['failed', 'partially_completed', 'cancelled'].includes(log.status)"
                    color="neutral"
                    variant="outline"
                    size="xs"
                    :loading="retryingScanId === log.id"
                    @click="retryFailedScan(log.id)"
                  >
                    <RotateCw class="mr-1 h-3 w-3" />
                    Retry
                  </UButton>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Discovery Source Preview -->
      <div
        v-else-if="activeTab === 'discovery'"
        class="space-y-4 rounded-lg border border-slate-200 bg-white p-5 text-xs dark:border-slate-800 dark:bg-slate-900"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <p class="font-semibold text-slate-900 dark:text-slate-100">
            SSRF-Validated Source Discovery Preview
          </p>
          <UButton
            color="primary"
            variant="soft"
            size="xs"
            :loading="discovering"
            @click="runDiscovery(true)"
          >
            Auto-Discover & Apply Endpoints
          </UButton>
        </div>

        <div
          v-if="connectivityResult"
          class="rounded-md border border-slate-200 p-3 dark:border-slate-800"
        >
          <p class="font-semibold">Connectivity Test</p>
          <p class="mt-1">
            Reachable: <strong>{{ connectivityResult.reachable ? 'Yes' : 'No' }}</strong>
            · Status: <code>{{ connectivityResult.status_code ?? 'N/A' }}</code>
            · Detected Type: <code>{{ connectivityResult.detected_website_type || 'unknown' }}</code>
          </p>
          <p
            v-if="connectivityResult.title"
            class="mt-1 text-slate-500"
          >
            Title: {{ connectivityResult.title }}
          </p>
          <p
            v-if="connectivityResult.error"
            class="mt-1 text-red-600"
          >
            {{ connectivityResult.error }}
          </p>
        </div>

        <div
          v-if="discoveryResult"
          class="space-y-2 rounded-md border border-slate-200 p-3 dark:border-slate-800"
        >
          <p class="font-semibold">
            Discovered Endpoints (Recommended: <code>{{ discoveryResult.recommended_method }}</code>)
          </p>
          <p>WordPress REST API: <code>{{ discoveryResult.wordpress_api_url || 'Not detected' }}</code></p>
          <p>RSS / Atom Feeds: <code>{{ discoveryResult.rss_urls.length ? discoveryResult.rss_urls.join(', ') : 'None found' }}</code></p>
          <p>XML Sitemaps: <code>{{ discoveryResult.sitemap_urls.length ? discoveryResult.sitemap_urls.join(', ') : 'None found' }}</code></p>
          <p>llms.txt: <code>{{ discoveryResult.llms_urls.length ? discoveryResult.llms_urls.join(', ') : 'Not detected' }}</code></p>
        </div>

        <AppEmptyState
          v-if="!connectivityResult && !discoveryResult"
          title="No probe executed yet"
          description="Click 'Test Connectivity' or 'Preview Sources' above to inspect live RSS, sitemap, WordPress API, and llms.txt availability."
        />
      </div>
    </template>
  </div>
</template>
