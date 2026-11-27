<script setup lang="ts">
import { ChevronLeft, ChevronRight, ExternalLink, RefreshCw, Search } from 'lucide-vue-next'
import type { ArticleListResponse } from '~/types/api'
import { extractErrorMessage, formatDateTime } from '~/utils/format'

const { request } = useApiClient()
const uiStore = useUiStore()

const articlesData = ref<ArticleListResponse | null>(null)
const loading = ref(true)
const errorMessage = ref<string | null>(null)

const page = ref(1)
const pageSize = ref(20)
const searchQuery = ref('')
const languageFilter = ref('')
const categoryFilter = ref('')
const statusFilter = ref('all')
const changeFilter = ref('all')
const dateFrom = ref('')
const dateTo = ref('')

const STATUS_OPTIONS = [
  { label: 'All Statuses', value: 'all' },
  { label: 'Optimized', value: 'optimized' },
  { label: 'Extracted', value: 'extracted' },
  { label: 'Updated', value: 'updated' },
  { label: 'Discovered', value: 'discovered' },
  { label: 'Archived', value: 'archived' },
]

const CHANGE_OPTIONS = [
  { label: 'All Articles', value: 'all' },
  { label: 'New / Baseline', value: 'new' },
  { label: 'Updated Revisions', value: 'updated' },
]

async function fetchArticles() {
  loading.value = true
  errorMessage.value = null
  try {
    const query: Record<string, string | number> = {
      page: page.value,
      page_size: pageSize.value,
    }
    if (uiStore.selectedBrandId !== null) {
      query.brand_id = uiStore.selectedBrandId
    }
    if (uiStore.selectedWebsiteId !== null) {
      query.website_id = uiStore.selectedWebsiteId
    }
    if (searchQuery.value.trim()) {
      query.search = searchQuery.value.trim()
    }
    if (languageFilter.value.trim()) {
      query.language = languageFilter.value.trim()
    }
    if (categoryFilter.value.trim()) {
      query.category = categoryFilter.value.trim()
    }
    if (statusFilter.value !== 'all') {
      query.status = statusFilter.value
    }
    if (changeFilter.value !== 'all') {
      query.change_filter = changeFilter.value
    }
    if (dateFrom.value) {
      query.date_from = `${dateFrom.value}T00:00:00Z`
    }
    if (dateTo.value) {
      query.date_to = `${dateTo.value}T23:59:59Z`
    }

    articlesData.value = await request<ArticleListResponse>('/api/v1/articles', { query })
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to load Content Library articles.')
  }
  finally {
    loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  void fetchArticles()
}

watch(
  () => [uiStore.selectedBrandId, uiStore.selectedWebsiteId],
  () => {
    page.value = 1
    void fetchArticles()
  },
)

onMounted(() => {
  void fetchArticles()
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">
          Content Library
        </h1>
        <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          Discovered articles stored in MySQL with clean Markdown, native YAKE keywords, and Python-prepared token contexts.
        </p>
      </div>
      <UButton
        color="neutral"
        variant="outline"
        size="sm"
        :loading="loading"
        @click="fetchArticles()"
      >
        <RefreshCw class="mr-1.5 h-3.5 w-3.5" />
        Refresh
      </UButton>
    </div>

    <!-- Filter Bar -->
    <form
      class="grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-2 lg:grid-cols-6 dark:border-slate-800 dark:bg-slate-900"
      @submit.prevent="applyFilters"
    >
      <div class="lg:col-span-2">
        <label class="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Keyword Search</label>
        <div class="relative">
          <Search class="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
          <UInput
            v-model="searchQuery"
            placeholder="Title, description, URL..."
            class="w-full pl-8"
          />
        </div>
      </div>

      <div>
        <label class="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Status</label>
        <USelect
          v-model="statusFilter"
          :items="STATUS_OPTIONS"
          value-key="value"
          class="w-full"
          @update:model-value="applyFilters"
        />
      </div>

      <div>
        <label class="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Change Filter</label>
        <USelect
          v-model="changeFilter"
          :items="CHANGE_OPTIONS"
          value-key="value"
          class="w-full"
          @update:model-value="applyFilters"
        />
      </div>

      <div>
        <label class="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Language</label>
        <UInput
          v-model="languageFilter"
          placeholder="en, fil, pt-BR"
          class="w-full"
        />
      </div>

      <div>
        <label class="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Category</label>
        <UInput
          v-model="categoryFilter"
          placeholder="SEO, Guides..."
          class="w-full"
        />
      </div>

      <div>
        <label class="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Discovered From</label>
        <UInput
          v-model="dateFrom"
          type="date"
          class="w-full"
        />
      </div>

      <div>
        <label class="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Discovered To</label>
        <UInput
          v-model="dateTo"
          type="date"
          class="w-full"
        />
      </div>

      <div class="flex items-end">
        <UButton
          type="submit"
          color="primary"
          size="sm"
        >
          Apply Filters
        </UButton>
      </div>
    </form>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="Could not load articles"
      :message="errorMessage"
      retryable
      @retry="fetchArticles()"
    />

    <div class="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <div
        v-if="loading"
        class="space-y-3 p-4"
      >
        <USkeleton
          v-for="idx in 6"
          :key="idx"
          class="h-10 w-full"
        />
      </div>

      <div
        v-else-if="!articlesData || articlesData.items.length === 0"
        class="p-6"
      >
        <AppEmptyState
          title="No discovered articles match your filters"
          description="Run a website scan in the Websites module or clear your current filters."
        />
      </div>

      <template v-else>
        <div class="overflow-x-auto">
          <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
            <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
              <tr>
                <th class="px-4 py-2.5 font-medium">Article</th>
                <th class="px-4 py-2.5 font-medium">Brand / Website</th>
                <th class="px-4 py-2.5 font-medium">Lang</th>
                <th class="px-4 py-2.5 font-medium">Words</th>
                <th class="px-4 py-2.5 font-medium">Status</th>
                <th class="px-4 py-2.5 font-medium">Published</th>
                <th class="px-4 py-2.5 font-medium">Discovered / Checked</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
              <tr
                v-for="article in articlesData.items"
                :key="article.id"
                class="hover:bg-slate-50/70 dark:hover:bg-slate-800/40"
              >
                <td class="px-4 py-3">
                  <div class="flex items-start gap-3">
                    <img
                      v-if="article.featured_image_url"
                      :src="article.featured_image_url"
                      :alt="article.title"
                      class="h-10 w-14 shrink-0 rounded border border-slate-200 object-cover dark:border-slate-700"
                    >
                    <div class="min-w-0">
                      <NuxtLink
                        :to="`/content-library/${article.id}`"
                        class="line-clamp-2 font-semibold text-teal-700 hover:underline dark:text-teal-300"
                      >
                        {{ article.title }}
                      </NuxtLink>
                      <div class="mt-0.5 flex flex-wrap items-center gap-2">
                        <a
                          :href="article.canonical_url"
                          target="_blank"
                          rel="noopener noreferrer"
                          class="inline-flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-600"
                        >
                          Source
                          <ExternalLink class="h-3 w-3" />
                        </a>
                        <UBadge
                          v-if="article.near_duplicate_of_id"
                          color="warning"
                          variant="subtle"
                          size="sm"
                        >
                          Similar #{{ article.near_duplicate_of_id }} ({{ article.near_duplicate_score }}%)
                        </UBadge>
                      </div>
                    </div>
                  </div>
                </td>
                <td class="px-4 py-3 whitespace-nowrap">
                  <p class="font-medium text-slate-800 dark:text-slate-200">{{ article.brand_name || '-' }}</p>
                  <p class="text-[11px] text-slate-500">{{ article.website_name || `#${article.website_id}` }}</p>
                </td>
                <td class="px-4 py-3 font-mono text-[11px]">{{ article.language || '-' }}</td>
                <td class="px-4 py-3">{{ article.word_count }}</td>
                <td class="px-4 py-3">
                  <HealthStatusBadge
                    :status="article.status === 'optimized' || article.status === 'extracted' ? 'ok' : article.status"
                    :label="article.status"
                  />
                </td>
                <td class="px-4 py-3 whitespace-nowrap text-slate-500">
                  {{ formatDateTime(article.published_at) }}
                </td>
                <td class="px-4 py-3 whitespace-nowrap text-[11px] text-slate-500">
                  <div>Disc: {{ formatDateTime(article.discovered_at) }}</div>
                  <div>Chk: {{ formatDateTime(article.last_checked_at) }}</div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-4 py-3 text-xs text-slate-500 dark:border-slate-800">
          <span>
            Page {{ articlesData.meta.page }} of {{ Math.max(1, articlesData.meta.total_pages) }}
            ({{ articlesData.meta.total_items }} total articles)
          </span>
          <div class="flex items-center gap-2">
            <UButton
              color="neutral"
              variant="outline"
              size="xs"
              :disabled="page <= 1"
              @click="page -= 1; fetchArticles()"
            >
              <ChevronLeft class="mr-1 h-3.5 w-3.5" />
              Previous
            </UButton>
            <UButton
              color="neutral"
              variant="outline"
              size="xs"
              :disabled="page >= articlesData.meta.total_pages"
              @click="page += 1; fetchArticles()"
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
