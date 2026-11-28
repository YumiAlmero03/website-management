<script setup lang="ts">
import { ChevronDown, ChevronRight, ExternalLink, Globe, Play, Plus, RefreshCw, Trash2 } from 'lucide-vue-next'
import type {
  ScanLog,
  Website,
  WebsiteCategory,
  WebsiteCategoryListResponse,
  WebsiteListResponse,
} from '~/types/api'
import {
  DISCOVERY_METHOD_OPTIONS,
  WEBSITE_TECHNOLOGY_OPTIONS,
  extractErrorMessage,
  formatDateTime,
} from '~/utils/format'

const { request } = useApiClient()
const uiStore = useUiStore()
const toast = useToast()

const websites = ref<Website[]>([])
const categories = ref<WebsiteCategory[]>([])
const loading = ref(true)
const errorMessage = ref<string | null>(null)
const page = ref(1)
const pageSize = ref(20)
const totalItems = ref(0)

// Filters
const categoryFilter = ref<string>('all')
const statusFilter = ref<string>('all')
const technologyFilter = ref<string>('all')
const search = ref('')

// Register Website modal state
const createModalOpen = ref(false)
const showAdvanced = ref(false)
const saving = ref(false)
const inlineCategoryOpen = ref(false)
const creatingCategory = ref(false)
const newCategoryName = ref('')

const createForm = ref({
  name: '',
  brand_name: '',
  domain: '',
  category_id: '' as string,
  primary_language: 'en',
  // Advanced Settings
  website_type: 'wordpress',
  discovery_method: 'auto',
  single_source_only: false,
  target_country: '',
  target_audience: '',
  tone: '',
  brand_description: '',
  target_keywords_text: '',
  restricted_keywords_text: '',
  default_hashtags_text: '',
  default_cta: '',
  writing_guidelines: '',
  ai_instructions: '',
  rss_url: '',
  sitemap_url: '',
  llms_url: '',
  api_endpoint: '',
  excluded_url_patterns_text: '',
  scan_interval_minutes: 1440,
  crawl_batch_size: 100,
  crawl_max_urls_per_run: 1000,
  auto_scan: true,
})

// Delete dialog
const deleteTarget = ref<Website | null>(null)
const deleteOpen = ref(false)
const deleting = ref(false)

const totalPages = computed(() => Math.max(1, Math.ceil(totalItems.value / pageSize.value)))

function parseCommaOrLines(raw: string): string[] {
  return raw
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

async function loadCategories() {
  try {
    const res = await request<WebsiteCategoryListResponse>('/api/v1/website-categories', {
      query: { include_archived: false },
    })
    categories.value = res.items
  }
  catch {
    // Keep category dropdown optional if load fails.
  }
}

async function loadWebsites() {
  loading.value = true
  errorMessage.value = null
  try {
    const query: Record<string, string | number> = {
      page: page.value,
      page_size: pageSize.value,
    }
    if (categoryFilter.value !== 'all') {
      query.category_id = Number(categoryFilter.value)
    }
    if (statusFilter.value !== 'all') {
      query.status = statusFilter.value
    }
    if (technologyFilter.value !== 'all') {
      query.website_type = technologyFilter.value
    }
    if (search.value.trim()) {
      query.search = search.value.trim()
    }
    const res = await request<WebsiteListResponse>('/api/v1/websites', { query })
    websites.value = res.items
    totalItems.value = res.meta.total_items
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to load websites.')
  }
  finally {
    loading.value = false
  }
}

function openCreateModal() {
  createForm.value = {
    name: '',
    brand_name: '',
    domain: '',
    category_id: categories.value[0] ? String(categories.value[0].id) : '',
    primary_language: 'en',
    website_type: 'wordpress',
    discovery_method: 'auto',
    single_source_only: false,
    target_country: '',
    target_audience: '',
    tone: '',
    brand_description: '',
    target_keywords_text: '',
    restricted_keywords_text: '',
    default_hashtags_text: '',
    default_cta: '',
    writing_guidelines: '',
    ai_instructions: '',
    rss_url: '',
    sitemap_url: '',
    llms_url: '',
    api_endpoint: '',
    excluded_url_patterns_text: '',
    scan_interval_minutes: 1440,
    crawl_batch_size: 100,
    crawl_max_urls_per_run: 1000,
    auto_scan: true,
  }
  showAdvanced.value = false
  inlineCategoryOpen.value = false
  newCategoryName.value = ''
  createModalOpen.value = true
}

async function createInlineCategory() {
  const cleanName = newCategoryName.value.trim()
  if (cleanName.length < 2) {
    return
  }
  creatingCategory.value = true
  try {
    const created = await request<WebsiteCategory>('/api/v1/website-categories', {
      method: 'POST',
      body: { name: cleanName },
    })
    categories.value = [...categories.value, created]
    createForm.value.category_id = String(created.id)
    inlineCategoryOpen.value = false
    newCategoryName.value = ''
    toast.add({ title: `Added category "${created.name}"`, color: 'success' })
    void uiStore.refreshGlobalSelectors()
  }
  catch (err) {
    toast.add({
      title: 'Could not add category',
      description: extractErrorMessage(err, 'Invalid category name or duplicate.'),
      color: 'error',
    })
  }
  finally {
    creatingCategory.value = false
  }
}

async function submitCreateWebsite() {
  saving.value = true
  try {
    const f = createForm.value
    const payload = {
      name: f.name.trim(),
      brand_name: f.brand_name.trim() || f.name.trim(),
      domain: f.domain.trim(),
      category_id: f.category_id ? Number(f.category_id) : null,
      primary_language: f.primary_language.trim() || 'en',
      website_type: f.website_type,
      discovery_method: f.discovery_method,
      single_source_only: f.single_source_only,
      target_country: f.target_country.trim() || null,
      target_audience: f.target_audience.trim() || null,
      tone: f.tone.trim() || null,
      brand_description: f.brand_description.trim() || null,
      target_keywords: parseCommaOrLines(f.target_keywords_text),
      restricted_keywords: parseCommaOrLines(f.restricted_keywords_text),
      default_hashtags: parseCommaOrLines(f.default_hashtags_text),
      default_cta: f.default_cta.trim() || null,
      writing_guidelines: f.writing_guidelines.trim() || null,
      ai_instructions: f.ai_instructions.trim() || null,
      rss_url: f.rss_url.trim() || null,
      sitemap_url: f.sitemap_url.trim() || null,
      llms_url: f.llms_url.trim() || null,
      api_endpoint: f.api_endpoint.trim() || null,
      excluded_url_patterns: parseCommaOrLines(f.excluded_url_patterns_text),
      scan_interval_minutes: Number(f.scan_interval_minutes) || 1440,
      crawl_batch_size: Number(f.crawl_batch_size) || 100,
      crawl_max_urls_per_run: Number(f.crawl_max_urls_per_run) || 1000,
      auto_scan: f.auto_scan,
    }
    const created = await request<Website>('/api/v1/websites', {
      method: 'POST',
      body: payload,
    })
    createModalOpen.value = false
    toast.add({
      title: 'Website registered',
      description: `${created.name} (${created.domain}) is ready to scan.`,
      color: 'success',
    })
    await Promise.all([loadWebsites(), uiStore.refreshGlobalSelectors()])
    await navigateTo(`/websites/${created.id}`)
  }
  catch (err) {
    toast.add({
      title: 'Registration failed',
      description: extractErrorMessage(err, 'Could not register website.'),
      color: 'error',
    })
  }
  finally {
    saving.value = false
  }
}

async function triggerQuickScan(site: Website) {
  try {
    const scan = await request<ScanLog>(`/api/v1/websites/${site.id}/scan`, {
      method: 'POST',
      body: { scan_mode: 'full' },
    })
    toast.add({
      title: `Full Scan #${scan.id} queued`,
      description: `Discovering & extracting URLs for ${site.name}.`,
      color: 'success',
    })
  }
  catch (err) {
    toast.add({
      title: 'Could not start scan',
      description: extractErrorMessage(err, 'A scan may already be running.'),
      color: 'error',
    })
  }
}

function promptDelete(site: Website) {
  deleteTarget.value = site
  deleteOpen.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) {
    return
  }
  deleting.value = true
  try {
    await request(`/api/v1/websites/${deleteTarget.value.id}`, { method: 'DELETE' })
    deleteOpen.value = false
    toast.add({ title: 'Website deleted', color: 'success' })
    await Promise.all([loadWebsites(), uiStore.refreshGlobalSelectors()])
  }
  catch (err) {
    deleteOpen.value = false
    toast.add({
      title: 'Delete blocked',
      description: extractErrorMessage(err, 'Remove or archive websites with stored content instead.'),
      color: 'error',
    })
  }
  finally {
    deleting.value = false
  }
}

watch([categoryFilter, statusFilter, technologyFilter], () => {
  page.value = 1
  void loadWebsites()
})

watch(page, () => {
  void loadWebsites()
})

onMounted(() => {
  void Promise.all([loadCategories(), loadWebsites()])
})
</script>

<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">
          Websites & Brand Hubs
        </h1>
        <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          Website-centric monitoring with built-in brand identity, custom categories, discovery endpoints, and URL rules.
        </p>
      </div>
      <div class="flex items-center gap-2">
        <UButton
          color="neutral"
          variant="outline"
          size="sm"
          @click="loadWebsites()"
        >
          <RefreshCw class="mr-1.5 h-3.5 w-3.5" />
          Refresh
        </UButton>
        <UButton
          color="primary"
          size="sm"
          @click="openCreateModal"
        >
          <Plus class="mr-1.5 h-3.5 w-3.5" />
          Register Website
        </UButton>
      </div>
    </div>

    <!-- Filters -->
    <div class="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
      <UInput
        v-model="search"
        placeholder="Search website, brand, or domain..."
        class="w-full sm:w-64"
        @keyup.enter="page = 1; loadWebsites()"
      />

      <select
        v-model="categoryFilter"
        aria-label="Filter by website category"
        class="h-9 rounded-md border border-slate-200 bg-white px-2.5 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
      >
        <option value="all">All Categories</option>
        <option
          v-for="cat in categories"
          :key="cat.id"
          :value="String(cat.id)"
        >
          {{ cat.name }}
        </option>
      </select>

      <select
        v-model="technologyFilter"
        aria-label="Filter by website technology"
        class="h-9 rounded-md border border-slate-200 bg-white px-2.5 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
      >
        <option value="all">All Technologies</option>
        <option
          v-for="opt in WEBSITE_TECHNOLOGY_OPTIONS"
          :key="opt.value"
          :value="opt.value"
        >
          {{ opt.label }}
        </option>
      </select>

      <select
        v-model="statusFilter"
        aria-label="Filter by status"
        class="h-9 rounded-md border border-slate-200 bg-white px-2.5 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
      >
        <option value="all">All Statuses</option>
        <option value="active">Active</option>
        <option value="paused">Paused</option>
        <option value="error">Error</option>
        <option value="archived">Archived</option>
      </select>

      <UButton
        color="neutral"
        variant="outline"
        size="xs"
        @click="page = 1; loadWebsites()"
      >
        Apply Search
      </UButton>
    </div>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="Could not load websites"
      :message="errorMessage"
      retryable
      @retry="loadWebsites()"
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
      v-else-if="websites.length === 0"
      title="No websites found"
      description="Register your first website in seconds — only website name, brand name, URL, category, and language are required."
    />

    <div
      v-else
      class="overflow-x-auto rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
    >
      <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
        <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
          <tr>
            <th class="px-4 py-3 font-medium">Website / Brand</th>
            <th class="px-4 py-3 font-medium">Category</th>
            <th class="px-4 py-3 font-medium">Technology & Lang</th>
            <th class="px-4 py-3 font-medium">Discovered Content</th>
            <th class="px-4 py-3 font-medium">Last Scan</th>
            <th class="px-4 py-3 font-medium">Status</th>
            <th class="px-4 py-3 text-right font-medium">Actions</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
          <tr
            v-for="site in websites"
            :key="site.id"
            class="hover:bg-slate-50/70 dark:hover:bg-slate-800/40"
          >
            <td class="px-4 py-3">
              <div class="flex items-center gap-2.5">
                <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-teal-50 text-teal-700 dark:bg-teal-950/50 dark:text-teal-300">
                  <Globe class="h-4 w-4" />
                </div>
                <div class="min-w-0">
                  <NuxtLink
                    :to="`/websites/${site.id}`"
                    class="block font-semibold text-slate-900 hover:text-teal-600 dark:text-slate-100 dark:hover:text-teal-300"
                  >
                    {{ site.name }}
                  </NuxtLink>
                  <p class="flex items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400">
                    <span>Brand: {{ site.brand_name }}</span>
                    <span>·</span>
                    <a
                      :href="`https://${site.domain}`"
                      target="_blank"
                      rel="noopener noreferrer"
                      class="inline-flex items-center gap-0.5 font-mono text-teal-600 hover:underline dark:text-teal-400"
                    >
                      {{ site.domain }}
                      <ExternalLink class="h-3 w-3" />
                    </a>
                  </p>
                </div>
              </div>
            </td>

            <td class="px-4 py-3">
              <UBadge
                v-if="site.category_name"
                color="neutral"
                variant="subtle"
                size="xs"
              >
                {{ site.category_name }}
              </UBadge>
              <span
                v-else
                class="text-slate-400"
              >
                Uncategorized
              </span>
            </td>

            <td class="px-4 py-3">
              <p class="font-medium text-slate-800 dark:text-slate-200">{{ site.website_type }}</p>
              <p class="text-[11px] text-slate-500">
                {{ site.primary_language }}{{ site.target_country ? ` · ${site.target_country}` : '' }}
              </p>
            </td>

            <td class="px-4 py-3">
              <p class="font-semibold text-slate-900 dark:text-slate-100">
                {{ site.content_counts.total_discovered }} URLs
              </p>
              <p class="text-[11px] text-slate-500">
                {{ site.content_counts.homepage }}H · {{ site.content_counts.page }}P · {{ site.content_counts.game_page ?? 0 }}G · {{ site.content_counts.blog_post }} Posts
                <span
                  v-if="site.content_counts.failed > 0"
                  class="text-amber-600 dark:text-amber-400"
                >
                  · {{ site.content_counts.failed }} failed
                </span>
              </p>
            </td>

            <td class="px-4 py-3 whitespace-nowrap text-slate-500 dark:text-slate-400">
              {{ formatDateTime(site.last_scanned_at) }}
            </td>

            <td class="px-4 py-3">
              <HealthStatusBadge
                :status="site.status === 'active' ? 'ok' : site.status === 'paused' ? 'warning' : 'error'"
                :label="site.status"
              />
            </td>

            <td class="px-4 py-3">
              <div class="flex items-center justify-end gap-1.5">
                <UButton
                  :to="`/websites/${site.id}`"
                  color="neutral"
                  variant="outline"
                  size="xs"
                >
                  Manage
                </UButton>
                <UButton
                  color="primary"
                  variant="subtle"
                  size="xs"
                  title="Run Full Scan"
                  @click="triggerQuickScan(site)"
                >
                  <Play class="h-3.5 w-3.5" />
                </UButton>
                <UButton
                  color="error"
                  variant="ghost"
                  size="xs"
                  title="Delete Website"
                  @click="promptDelete(site)"
                >
                  <Trash2 class="h-3.5 w-3.5" />
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
        <span class="text-slate-500">Page {{ page }} of {{ totalPages }} ({{ totalItems }} websites)</span>
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

    <!-- Simplified Register Website Modal -->
    <UModal
      v-model:open="createModalOpen"
      title="Register Website"
    >
      <template #body>
        <form
          class="space-y-4"
          @submit.prevent="submitCreateWebsite"
        >
          <p class="text-xs text-slate-500 dark:text-slate-400">
            Quick setup: enter your website details below. Discovery endpoints and classification rules work automatically.
          </p>

          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label class="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300">
                Website Name *
              </label>
              <UInput
                v-model="createForm.name"
                placeholder="e.g., Bygame Casino"
                required
                class="w-full"
              />
            </div>

            <div>
              <label class="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300">
                Brand Name
              </label>
              <UInput
                v-model="createForm.brand_name"
                placeholder="Defaults to Website Name"
                class="w-full"
              />
            </div>
          </div>

          <div>
            <label class="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300">
              Website URL or Domain *
            </label>
            <UInput
              v-model="createForm.domain"
              placeholder="e.g., https://bygame.ph/ or bygame.ph"
              required
              class="w-full"
            />
          </div>

          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <div class="mb-1 flex items-center justify-between">
                <label class="text-xs font-medium text-slate-700 dark:text-slate-300">
                  Website Category
                </label>
                <button
                  type="button"
                  class="text-[11px] font-medium text-teal-600 hover:underline dark:text-teal-400"
                  @click="inlineCategoryOpen = !inlineCategoryOpen"
                >
                  + New Category
                </button>
              </div>
              <select
                v-model="createForm.category_id"
                class="h-9 w-full rounded-md border border-slate-200 bg-white px-2.5 text-xs text-slate-800 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
              >
                <option value="">Uncategorized</option>
                <option
                  v-for="cat in categories"
                  :key="cat.id"
                  :value="String(cat.id)"
                >
                  {{ cat.name }}
                </option>
              </select>

              <div
                v-if="inlineCategoryOpen"
                class="mt-2 flex items-center gap-1.5"
              >
                <UInput
                  v-model="newCategoryName"
                  placeholder="New category name..."
                  size="xs"
                  class="flex-1"
                />
                <UButton
                  size="xs"
                  color="primary"
                  :loading="creatingCategory"
                  @click="createInlineCategory"
                >
                  Add
                </UButton>
              </div>
            </div>

            <div>
              <label class="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300">
                Primary Language *
              </label>
              <UInput
                v-model="createForm.primary_language"
                placeholder="e.g., en, Taglish, fil"
                required
                class="w-full"
              />
            </div>
          </div>

          <!-- Expandable Advanced Settings -->
          <div class="rounded-md border border-slate-200 dark:border-slate-800">
            <button
              type="button"
              class="flex w-full items-center justify-between px-3 py-2 text-left text-xs font-medium text-slate-700 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800/50"
              @click="showAdvanced = !showAdvanced"
            >
              <span>Advanced Settings (Technology, Brand Profile, Endpoints & Crawl Limits)</span>
              <ChevronDown
                v-if="showAdvanced"
                class="h-4 w-4"
              />
              <ChevronRight
                v-else
                class="h-4 w-4"
              />
            </button>

            <div
              v-if="showAdvanced"
              class="space-y-4 border-t border-slate-200 p-3 dark:border-slate-800"
            >
              <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label class="mb-1 block text-[11px] font-medium text-slate-600 dark:text-slate-400">
                    Website Technology
                  </label>
                  <select
                    v-model="createForm.website_type"
                    class="h-8 w-full rounded-md border border-slate-200 bg-white px-2 text-xs dark:border-slate-700 dark:bg-slate-950"
                  >
                    <option
                      v-for="opt in WEBSITE_TECHNOLOGY_OPTIONS"
                      :key="opt.value"
                      :value="opt.value"
                    >
                      {{ opt.label }}
                    </option>
                  </select>
                </div>

                <div>
                  <label class="mb-1 block text-[11px] font-medium text-slate-600 dark:text-slate-400">
                    Discovery Strategy
                  </label>
                  <select
                    v-model="createForm.discovery_method"
                    class="h-8 w-full rounded-md border border-slate-200 bg-white px-2 text-xs dark:border-slate-700 dark:bg-slate-950"
                  >
                    <option
                      v-for="opt in DISCOVERY_METHOD_OPTIONS"
                      :key="opt.value"
                      :value="opt.value"
                    >
                      {{ opt.label }}
                    </option>
                  </select>
                </div>

                <div>
                  <label class="mb-1 block text-[11px] font-medium text-slate-600 dark:text-slate-400">
                    Target Country
                  </label>
                  <UInput
                    v-model="createForm.target_country"
                    placeholder="e.g., Philippines"
                    size="xs"
                  />
                </div>

                <div>
                  <label class="mb-1 block text-[11px] font-medium text-slate-600 dark:text-slate-400">
                    Target Audience
                  </label>
                  <UInput
                    v-model="createForm.target_audience"
                    placeholder="e.g., Sports fans & casual players"
                    size="xs"
                  />
                </div>

                <div>
                  <label class="mb-1 block text-[11px] font-medium text-slate-600 dark:text-slate-400">
                    Brand Tone
                  </label>
                  <UInput
                    v-model="createForm.tone"
                    placeholder="e.g., Clear, confident, trustworthy"
                    size="xs"
                  />
                </div>

                <div>
                  <label class="mb-1 block text-[11px] font-medium text-slate-600 dark:text-slate-400">
                    Default CTA
                  </label>
                  <UInput
                    v-model="createForm.default_cta"
                    placeholder="Optional call to action"
                    size="xs"
                  />
                </div>
              </div>

              <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label class="mb-1 block text-[11px] font-medium text-slate-600 dark:text-slate-400">
                    Target Keywords (comma-separated)
                  </label>
                  <UInput
                    v-model="createForm.target_keywords_text"
                    placeholder="slots, odds, guides"
                    size="xs"
                  />
                </div>
                <div>
                  <label class="mb-1 block text-[11px] font-medium text-slate-600 dark:text-slate-400">
                    Default Hashtags (comma-separated)
                  </label>
                  <UInput
                    v-model="createForm.default_hashtags_text"
                    placeholder="#Bygame, #Guides"
                    size="xs"
                  />
                </div>
              </div>

              <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label class="mb-1 block text-[11px] font-medium text-slate-600 dark:text-slate-400">
                    Custom Sitemap URL (optional)
                  </label>
                  <UInput
                    v-model="createForm.sitemap_url"
                    placeholder="https://example.com/sitemap.xml"
                    size="xs"
                  />
                </div>
                <div>
                  <label class="mb-1 block text-[11px] font-medium text-slate-600 dark:text-slate-400">
                    Custom RSS URL (optional)
                  </label>
                  <UInput
                    v-model="createForm.rss_url"
                    placeholder="https://example.com/feed.xml"
                    size="xs"
                  />
                </div>
                <div>
                  <label class="mb-1 block text-[11px] font-medium text-slate-600 dark:text-slate-400">
                    Batch Size / Run Limit
                  </label>
                  <div class="flex gap-2">
                    <UInput
                      v-model="createForm.crawl_batch_size"
                      type="number"
                      size="xs"
                      placeholder="100"
                    />
                    <UInput
                      v-model="createForm.crawl_max_urls_per_run"
                      type="number"
                      size="xs"
                      placeholder="1000"
                    />
                  </div>
                </div>
                <div>
                  <label class="mb-1 block text-[11px] font-medium text-slate-600 dark:text-slate-400">
                    Excluded URL Patterns (optional)
                  </label>
                  <UInput
                    v-model="createForm.excluded_url_patterns_text"
                    placeholder="/wp-admin/*, /search/*"
                    size="xs"
                  />
                </div>
              </div>

              <label class="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
                <USwitch v-model="createForm.single_source_only" />
                <span>Restrict to selected single discovery source only (disable aggregated crawl)</span>
              </label>
            </div>
          </div>

          <div class="flex justify-end gap-2 pt-2">
            <UButton
              color="neutral"
              variant="outline"
              size="sm"
              @click="createModalOpen = false"
            >
              Cancel
            </UButton>
            <UButton
              type="submit"
              color="primary"
              size="sm"
              :loading="saving"
            >
              Register Website
            </UButton>
          </div>
        </form>
      </template>
    </UModal>

    <AppConfirmDialog
      v-model:open="deleteOpen"
      title="Delete registered website?"
      :description="deleteTarget ? `Delete ${deleteTarget.name} (${deleteTarget.domain})? Websites with stored Content Library items cannot be deleted.` : ''"
      confirm-label="Delete Website"
      confirm-color="error"
      :loading="deleting"
      @confirm="confirmDelete"
    />
  </div>
</template>
