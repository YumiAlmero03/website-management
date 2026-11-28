<script setup lang="ts">
import { Ban, CheckCircle2, ExternalLink, RefreshCw, RotateCcw } from 'lucide-vue-next'
import type {
  ContentListItem,
  ContentListResponse,
  ContentStats,
  IndexingStatus,
} from '~/types/api'
import {
  CONTENT_TYPE_OPTIONS,
  extractErrorMessage,
  formatDateTime,
  getContentTypeMeta,
} from '~/utils/format'
import { isContentEligibleForManualGeneration } from '~/utils/ai'

const route = useRoute()
const { request } = useApiClient()
const uiStore = useUiStore()
const toast = useToast()

const activeTab = ref<string>(
  typeof route.query.tab === 'string' ? route.query.tab : 'all',
)
const websiteFilter = ref<string>(
  typeof route.query.website_id === 'string'
    ? route.query.website_id
    : (uiStore.selectedWebsiteId !== null ? String(uiStore.selectedWebsiteId) : 'all'),
)
const categoryFilter = ref<string>('all')
const changeFilter = ref<string>('all')
const search = ref('')
const sortBy = ref<'last_discovered_at' | 'word_count' | 'title'>('last_discovered_at')
const page = ref(1)
const pageSize = ref(20)

const items = ref<ContentListItem[]>([])
const stats = ref<ContentStats>({
  total_discovered: 0,
  total_extracted: 0,
  homepage_count: 0,
  page_count: 0,
  game_page_count: 0,
  blog_post_count: 0,
  blog_index_count: 0,
  other_count: 0,
  pending_count: 0,
  failed_count: 0,
  updated_count: 0,
  excluded_count: 0,
  discovered_today_count: 0,
})
const totalItems = ref(0)
const loading = ref(true)
const errorMessage = ref<string | null>(null)
const busyItemId = ref<number | null>(null)
const googleIndexFilter = ref('all')
const indexingStatus = ref<IndexingStatus>({
  state: 'idle',
  progress: 0,
  total: 0,
  processed: 0,
  indexed: 0,
  skipped: 0,
  ready: 0,
  failed: 0,
})
let indexingPoll: ReturnType<typeof setInterval> | null = null

const totalPages = computed(() => Math.max(1, Math.ceil(totalItems.value / pageSize.value)))

const tabs = computed(() => [
  { key: 'all', label: 'All Content', count: stats.value.total_discovered },
  { key: 'homepage', label: 'Homepage', count: stats.value.homepage_count },
  { key: 'pages', label: 'Pages', count: stats.value.page_count },
  { key: 'game_pages', label: 'Game Pages', count: stats.value.game_page_count ?? 0 },
  { key: 'blog_posts', label: 'Blog Posts', count: stats.value.blog_post_count },
  { key: 'blog_indexes', label: 'Blog Indexes', count: stats.value.blog_index_count },
  { key: 'other', label: 'Other', count: stats.value.other_count },
  { key: 'failed', label: 'Failed Extraction', count: stats.value.failed_count },
])

async function loadContents() {
  loading.value = true
  errorMessage.value = null
  try {
    const query: Record<string, string | number | boolean> = {
      page: page.value,
      page_size: pageSize.value,
      tab: activeTab.value,
      sort_by: sortBy.value,
      sort_dir: sortBy.value === 'title' ? 'asc' : 'desc',
    }
    if (websiteFilter.value !== 'all') {
      query.website_id = Number(websiteFilter.value)
    }
    if (categoryFilter.value !== 'all') {
      query.category_id = Number(categoryFilter.value)
    }
    if (changeFilter.value !== 'all') {
      query.change_filter = changeFilter.value
    }
    if (search.value.trim()) {
      query.search = search.value.trim()
    }
    if (googleIndexFilter.value !== 'all') {
      query.google_index_status = googleIndexFilter.value
    }

    const res = await request<ContentListResponse>('/api/v1/contents', { query })
    items.value = res.items
    stats.value = res.stats
    totalItems.value = res.meta.total_items
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to load Content Library.')
  }
  finally {
    loading.value = false
  }
}

async function reclassifyItem(item: ContentListItem, newType: string) {
  if (item.content_type === newType) {
    return
  }
  busyItemId.value = item.id
  try {
    await request(`/api/v1/contents/${item.id}`, {
      method: 'PATCH',
      body: { content_type: newType, manual_classification_override: true },
    })
    toast.add({
      title: 'Classification updated',
      description: `Pinned as "${getContentTypeMeta(newType).label}" (manual override enabled).`,
      color: 'success',
    })
    await loadContents()
  }
  catch (err) {
    toast.add({
      title: 'Reclassification failed',
      description: extractErrorMessage(err, 'Could not update content type.'),
      color: 'error',
    })
  }
  finally {
    busyItemId.value = null
  }
}

async function toggleExcludeItem(item: ContentListItem) {
  busyItemId.value = item.id
  try {
    await request(`/api/v1/contents/${item.id}`, {
      method: 'PATCH',
      body: { is_excluded: !item.is_excluded },
    })
    toast.add({
      title: item.is_excluded ? 'URL restored' : 'URL excluded',
      color: 'success',
    })
    await loadContents()
  }
  catch (err) {
    toast.add({
      title: 'Update failed',
      description: extractErrorMessage(err, 'Could not change exclusion flag.'),
      color: 'error',
    })
  }
  finally {
    busyItemId.value = null
  }
}

async function retryExtraction(item: ContentListItem) {
  busyItemId.value = item.id
  try {
    const updated = await request<ContentListItem>(`/api/v1/contents/${item.id}/reprocess`, {
      method: 'POST',
    })
    toast.add({
      title: updated.extraction_status === 'extracted' ? 'Extraction succeeded' : 'Extraction failed',
      description: updated.extraction_error || `${updated.word_count} words extracted.`,
      color: updated.extraction_status === 'extracted' ? 'success' : 'warning',
    })
    await loadContents()
  }
  catch (err) {
    toast.add({
      title: 'Re-extraction error',
      description: extractErrorMessage(err, 'Could not reprocess URL.'),
      color: 'error',
    })
  }
  finally {
    busyItemId.value = null
  }
}

const resolvedIndexingWebsiteId = computed<number | null>(() => {
  if (websiteFilter.value !== 'all') {
    const parsed = Number(websiteFilter.value)
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null
  }
  if (uiStore.selectedWebsiteId !== null) {
    return uiStore.selectedWebsiteId
  }
  if (uiStore.websitesCatalog.length === 1) {
    return uiStore.websitesCatalog[0]?.id ?? null
  }
  return null
})

function ensureIndexingPoll() {
  if (indexingPoll) {
    return
  }
  indexingPoll = setInterval(() => {
    void refreshIndexingStatus()
  }, 3000)
}

async function refreshIndexingStatus() {
  const targetWebsiteId = resolvedIndexingWebsiteId.value
  if (targetWebsiteId === null) {
    return
  }
  try {
    indexingStatus.value = await request<IndexingStatus>(
      `/api/v1/indexing/websites/${targetWebsiteId}/status`,
    )
    if (indexingStatus.value.state === 'queued' || indexingStatus.value.state === 'processing') {
      ensureIndexingPoll()
    }
  }
  catch {
    // Leave the last known button state visible while the status endpoint is unavailable.
  }
}

watch(() => indexingStatus.value.state, (state) => {
  if (state === 'completed') {
    if (indexingPoll) {
      clearInterval(indexingPoll)
      indexingPoll = null
    }
    toast.add({
      title: 'Indexing completed',
      description: `${indexingStatus.value.processed} processed · ${indexingStatus.value.indexed} indexed · ${indexingStatus.value.skipped} skipped · ${indexingStatus.value.ready} ready to request · ${indexingStatus.value.failed} failed`,
      color: 'success',
    })
    void loadContents()
  }
  if (state === 'deferred') {
    if (indexingPoll) {
      clearInterval(indexingPoll)
      indexingPoll = null
    }
  }
})

watch(
  () => uiStore.selectedWebsiteId,
  (val) => {
    websiteFilter.value = val !== null ? String(val) : 'all'
    void refreshIndexingStatus()
  },
)

watch(
  () => [websiteFilter.value, uiStore.websitesCatalog.length],
  () => {
    void refreshIndexingStatus()
  },
)

watch([activeTab, websiteFilter, categoryFilter, changeFilter, sortBy, googleIndexFilter], () => {
  page.value = 1
  void loadContents()
})

watch(page, () => {
  void loadContents()
})

const generateModalOpen = ref(false)
const generateTarget = ref<ContentListItem | null>(null)

function openGenerateModal(item: ContentListItem) {
  generateTarget.value = item
  generateModalOpen.value = true
}

onMounted(() => {
  void Promise.all([uiStore.refreshGlobalSelectors(), loadContents(), refreshIndexingStatus()])
})

onUnmounted(() => {
  if (indexingPoll) clearInterval(indexingPoll)
})
</script>

<template>
  <div class="space-y-5">
    <!-- Header -->
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">
          Universal Content Library
        </h1>
        <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          Every discovered homepage, page, blog index, blog post, category archive, revision, and extraction failure stored in MySQL. Start Google indexing from the website's Settings.
        </p>
      </div>
      <UButton
        color="neutral"
        variant="outline"
        size="sm"
        @click="loadContents()"
      >
        <RefreshCw class="mr-1.5 h-3.5 w-3.5" />
        Refresh
      </UButton>
    </div>

    <!-- Real DB Tab Counts -->
    <div class="flex flex-wrap gap-1.5 border-b border-slate-200 pb-3 dark:border-slate-800">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        :class="[
          'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
          activeTab === tab.key
            ? 'bg-teal-600 text-white'
            : 'bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50 dark:bg-slate-900 dark:text-slate-300 dark:ring-slate-800 dark:hover:bg-slate-800',
        ]"
        @click="activeTab = tab.key"
      >
        <span>{{ tab.label }}</span>
        <span
          :class="[
            'rounded-full px-1.5 py-0.5 font-mono text-[10px]',
            activeTab === tab.key ? 'bg-white/20 text-white' : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
          ]"
        >
          {{ tab.count }}
        </span>
      </button>

      <button
        type="button"
        :class="[
          'ml-auto inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
          activeTab === 'excluded'
            ? 'bg-slate-800 text-white dark:bg-slate-200 dark:text-slate-900'
            : 'text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800',
        ]"
        @click="activeTab = activeTab === 'excluded' ? 'all' : 'excluded'"
      >
        <span>Excluded ({{ stats.excluded_count }})</span>
      </button>
    </div>

    <!-- Filters -->
    <div class="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
      <UInput
        v-model="search"
        placeholder="Search title, URL, or content..."
        class="w-full sm:w-64"
        @keyup.enter="page = 1; loadContents()"
      />

      <select
        v-model="websiteFilter"
        aria-label="Filter by website"
        class="h-9 rounded-md border border-slate-200 bg-white px-2.5 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
      >
        <option value="all">All Websites</option>
        <option
          v-for="site in uiStore.websitesCatalog"
          :key="site.id"
          :value="String(site.id)"
        >
          {{ site.name }}
        </option>
      </select>

      <select
        v-model="categoryFilter"
        aria-label="Filter by website category"
        class="h-9 rounded-md border border-slate-200 bg-white px-2.5 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
      >
        <option value="all">All Website Categories</option>
        <option
          v-for="cat in uiStore.categoriesCatalog"
          :key="cat.id"
          :value="String(cat.id)"
        >
          {{ cat.name }}
        </option>
      </select>

      <select
        v-model="changeFilter"
        aria-label="Filter by change status"
        class="h-9 rounded-md border border-slate-200 bg-white px-2.5 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
      >
        <option value="all">All Changes</option>
        <option value="new">New / Extracted</option>
        <option value="updated">Updated (Has Revision)</option>
      </select>

      <select
        v-model="googleIndexFilter"
        aria-label="Filter by Google Index status"
        class="h-9 rounded-md border border-slate-200 bg-white px-2.5 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
      >
        <option value="all">Google Index: All</option>
        <option value="not_indexed">Not Indexed</option>
        <option value="indexed">Indexed</option>
        <option value="ready_to_request">Ready to Request</option>
        <option value="uninspected">Uninspected</option>
        <option value="failed">Failed</option>
        <option value="technical_issue">Technical Issue</option>
      </select>

      <select
        v-model="sortBy"
        aria-label="Sort results"
        class="h-9 rounded-md border border-slate-200 bg-white px-2.5 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
      >
        <option value="last_discovered_at">Sort: Last Discovered</option>
        <option value="word_count">Sort: Word Count</option>
        <option value="title">Sort: Title A-Z</option>
      </select>

      <UButton
        color="neutral"
        variant="outline"
        size="xs"
        @click="page = 1; loadContents()"
      >
        Search
      </UButton>
    </div>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="Failed to load content"
      :message="errorMessage"
      retryable
      @retry="loadContents()"
    />

    <div
      v-else-if="loading"
      class="space-y-3"
    >
      <USkeleton class="h-16 w-full" />
      <USkeleton class="h-16 w-full" />
      <USkeleton class="h-16 w-full" />
    </div>

    <AppEmptyState
      v-else-if="items.length === 0"
      title="No matching content items"
      description="Run a scan from Websites Management or switch tabs to inspect other discovered URLs."
    />

    <div
      v-else
      class="overflow-x-auto rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
    >
      <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
        <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
          <tr>
            <th class="px-4 py-3 font-medium">Title & URL</th>
            <th class="px-4 py-3 font-medium">Website</th>
            <th class="px-4 py-3 font-medium">Classification</th>
            <th class="px-4 py-3 font-medium">Extraction</th>
            <th class="px-4 py-3 font-medium">Google Index</th>
            <th class="px-4 py-3 font-medium">Sources & Words</th>
            <th class="px-4 py-3 font-medium">Discovered</th>
            <th class="px-4 py-3 text-right font-medium">Actions</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
          <tr
            v-for="item in items"
            :key="item.id"
            class="hover:bg-slate-50/70 dark:hover:bg-slate-800/40"
          >
            <td class="max-w-xs px-4 py-3">
              <NuxtLink
                :to="`/content-library/${item.id}`"
                class="line-clamp-1 font-semibold text-slate-900 hover:text-teal-600 dark:text-slate-100 dark:hover:text-teal-300"
              >
                {{ item.title }}
              </NuxtLink>
              <a
                :href="item.canonical_url"
                target="_blank"
                rel="noopener noreferrer"
                class="mt-0.5 inline-flex max-w-xs items-center gap-1 truncate font-mono text-[11px] text-slate-500 hover:text-teal-600 dark:text-slate-400"
              >
                <span class="truncate">{{ item.canonical_url }}</span>
                <ExternalLink class="h-3 w-3 shrink-0" />
              </a>
              <p
                v-if="item.extraction_error"
                class="mt-1 line-clamp-1 text-[11px] text-rose-600 dark:text-rose-400"
              >
                {{ item.extraction_error }}
              </p>
            </td>

            <td class="px-4 py-3">
              <NuxtLink
                :to="`/websites/${item.website_id}`"
                class="font-medium text-teal-700 hover:underline dark:text-teal-300"
              >
                {{ item.website_name || `Website #${item.website_id}` }}
              </NuxtLink>
              <p class="text-[11px] text-slate-500">
                {{ item.website_category_name || 'Uncategorized' }}
              </p>
            </td>

            <td class="px-4 py-3">
              <div class="flex flex-col gap-1">
                <div class="flex items-center gap-1">
                  <UBadge
                    :color="getContentTypeMeta(item.content_type).color"
                    variant="subtle"
                    size="xs"
                  >
                    {{ getContentTypeMeta(item.content_type).label }}
                  </UBadge>
                  <span
                    v-if="item.manual_classification_override"
                    class="rounded bg-slate-100 px-1 py-0.5 text-[10px] font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                    title="Manually pinned classification preserved across scans"
                  >
                    pinned
                  </span>
                </div>
                <select
                  :value="item.content_type"
                  aria-label="Quick reclassify content type"
                  :disabled="busyItemId === item.id"
                  class="h-6 rounded border border-slate-200 bg-slate-50 px-1 text-[10px] text-slate-600 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-300"
                  @change="reclassifyItem(item, ($event.target as HTMLSelectElement).value)"
                >
                  <option
                    v-for="opt in CONTENT_TYPE_OPTIONS"
                    :key="opt.value"
                    :value="opt.value"
                  >
                    Reclassify: {{ opt.label }}
                  </option>
                </select>
              </div>
            </td>

            <td class="px-4 py-3">
              <HealthStatusBadge
                :status="item.extraction_status === 'extracted' ? 'ok' : item.extraction_status === 'pending' ? 'warning' : 'error'"
                :label="item.extraction_status"
              />
              <span
                v-if="item.http_status"
                class="mt-1 block font-mono text-[10px] text-slate-400"
              >
                HTTP {{ item.http_status }}
              </span>
            </td>

            <td class="px-4 py-3 whitespace-nowrap">
              <UBadge
                :color="item.google_index_status === 'indexed'
                  ? 'success'
                  : item.google_index_status === 'ready_to_request'
                    ? 'warning'
                    : item.google_index_status === 'failed' || item.google_index_status === 'technical_issue'
                      ? 'error'
                      : 'neutral'"
                variant="subtle"
                size="xs"
              >
                {{ item.google_index_status.replaceAll('_', ' ') }}
              </UBadge>
              <p
                v-if="item.google_index_coverage_state"
                class="mt-1 max-w-40 truncate text-[10px] text-slate-500"
                :title="item.google_index_coverage_state"
              >
                {{ item.google_index_coverage_state }}
              </p>
            </td>

            <td class="px-4 py-3">
              <p class="font-mono text-slate-700 dark:text-slate-300">{{ item.word_count }} words</p>
              <p class="text-[11px] text-slate-500">
                {{ item.discovery_sources.join(', ') || 'discovered' }}
              </p>
            </td>

            <td class="px-4 py-3 whitespace-nowrap text-slate-500 dark:text-slate-400">
              {{ formatDateTime(item.last_discovered_at) }}
            </td>

            <td class="px-4 py-3">
              <div class="flex items-center justify-end gap-1">
                <UButton
                  :to="`/content-library/${item.id}`"
                  color="neutral"
                  variant="outline"
                  size="xs"
                >
                  Open
                </UButton>
                <UButton
                  color="neutral"
                  variant="ghost"
                  size="xs"
                  :loading="busyItemId === item.id"
                  title="Re-extract content now"
                  @click="retryExtraction(item)"
                >
                  <RotateCcw class="h-3.5 w-3.5" />
                </UButton>
                <UButton
                  :color="item.is_excluded ? 'success' : 'error'"
                  variant="ghost"
                  size="xs"
                  :disabled="busyItemId === item.id"
                  :title="item.is_excluded ? 'Restore URL' : 'Exclude URL from Content Library'"
                  @click="toggleExcludeItem(item)"
                >
                  <CheckCircle2
                    v-if="item.is_excluded"
                    class="h-3.5 w-3.5"
                  />
                  <Ban
                    v-else
                    class="h-3.5 w-3.5"
                  />
                </UButton>
                <UButton
                  v-if="isContentEligibleForManualGeneration(item)"
                  color="primary"
                  variant="subtle"
                  size="xs"
                  title="Generate Social Drafts"
                  @click="openGenerateModal(item)"
                >
                  Generate
                </UButton>
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <div
        v-if="totalPages > 1"
        class="flex items-center justify-between border-t border-slate-200 px-4 py-3 text-xs dark:border-slate-800"
      >
        <span class="text-slate-500">Page {{ page }} of {{ totalPages }} ({{ totalItems }} items)</span>
        <div class="flex gap-2">
          <UButton
            size="xs"
            color="neutral"
            variant="outline"
            :disabled="page <= 1"
            @click="page--"
          >
            Previous
          </UButton>
          <UButton
            size="xs"
            color="neutral"
            variant="outline"
            :disabled="page >= totalPages"
            @click="page++"
          >
            Next
          </UButton>
        </div>
      </div>
    </div>

    <GenerateSocialModal
      :open="generateModalOpen"
      :content="generateTarget"
      @update:open="generateModalOpen = $event"
      @generated="loadContents()"
    />
  </div>
</template>
