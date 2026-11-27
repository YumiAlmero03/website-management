<script setup lang="ts">
import { Eye, Play, Plus, Search, Trash2 } from 'lucide-vue-next'
import type { ScanLog, Website, WebsiteListResponse } from '~/types/api'
import { extractErrorMessage, formatDateTime } from '~/utils/format'

const { request } = useApiClient()
const uiStore = useUiStore()
const toast = useToast()

const WEBSITE_TYPES = [
  { label: 'WordPress', value: 'wordpress' },
  { label: 'Nuxt', value: 'nuxt' },
  { label: 'Next.js', value: 'nextjs' },
  { label: 'Custom PHP', value: 'custom_php' },
  { label: 'Static HTML', value: 'static_html' },
  { label: 'Other CMS', value: 'other_cms' },
  { label: 'Custom REST API', value: 'custom_rest_api' },
]

const DISCOVERY_METHODS = [
  { label: 'Auto (Recommended Order)', value: 'auto' },
  { label: 'Custom REST API', value: 'rest_api' },
  { label: 'WordPress REST API', value: 'wordpress' },
  { label: 'RSS / Atom Feed', value: 'rss' },
  { label: 'XML Sitemap', value: 'sitemap' },
  { label: 'llms.txt', value: 'llms_txt' },
  { label: 'Standard HTML', value: 'html' },
  { label: 'Playwright Fallback (Optional)', value: 'playwright' },
]

const BASELINE_MODES = [
  { label: 'Import Existing (Baseline, No Auto-Post)', value: 'import_existing' },
  { label: 'Import Latest N Articles', value: 'latest_n' },
  { label: 'Import Articles After Date', value: 'after_date' },
  { label: 'Discover New Only After Baseline', value: 'new_only' },
]

const websitesData = ref<WebsiteListResponse | null>(null)
const loading = ref(true)
const errorMessage = ref<string | null>(null)
const searchQuery = ref('')
const statusFilter = ref('all')

const modalOpen = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const scanningId = ref<number | null>(null)

const deleteTarget = ref<Website | null>(null)
const deleteOpen = ref(false)
const deleting = ref(false)

const form = ref({
  brand_id: '',
  name: '',
  domain: '',
  website_type: 'wordpress',
  discovery_method: 'auto',
  rss_url: '',
  sitemap_url: '',
  llms_url: '',
  api_endpoint: '',
  article_url_patterns_text: '',
  excluded_url_patterns_text: '/category/*, /tag/*, /author/*, /wp-admin/*, /search/*',
  scan_interval_minutes: 360,
  auto_scan: true,
  auto_generate: false,
  baseline_mode: 'import_existing',
  baseline_limit: 50,
  status: 'active',
})

const brandItems = computed(() =>
  uiStore.brandsCatalog.map((b) => ({ label: b.name, value: String(b.id) })),
)

function splitPatterns(raw: string): string[] {
  return raw
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function openCreateModal() {
  editingId.value = null
  const defaultBrand = uiStore.selectedBrandId ?? uiStore.brandsCatalog[0]?.id
  form.value = {
    brand_id: defaultBrand ? String(defaultBrand) : '',
    name: '',
    domain: '',
    website_type: 'wordpress',
    discovery_method: 'auto',
    rss_url: '',
    sitemap_url: '',
    llms_url: '',
    api_endpoint: '',
    article_url_patterns_text: '',
    excluded_url_patterns_text: '/category/*, /tag/*, /author/*, /wp-admin/*, /search/*',
    scan_interval_minutes: 360,
    auto_scan: true,
    auto_generate: false,
    baseline_mode: 'import_existing',
    baseline_limit: 50,
    status: 'active',
  }
  modalOpen.value = true
}

function openEditModal(site: Website) {
  editingId.value = site.id
  form.value = {
    brand_id: String(site.brand_id),
    name: site.name,
    domain: site.domain,
    website_type: site.website_type,
    discovery_method: site.discovery_method,
    rss_url: site.rss_url || '',
    sitemap_url: site.sitemap_url || '',
    llms_url: site.llms_url || '',
    api_endpoint: site.api_endpoint || '',
    article_url_patterns_text: site.article_url_patterns.join(', '),
    excluded_url_patterns_text: site.excluded_url_patterns.join(', '),
    scan_interval_minutes: site.scan_interval_minutes,
    auto_scan: site.auto_scan,
    auto_generate: site.auto_generate,
    baseline_mode: site.baseline_mode,
    baseline_limit: site.baseline_limit || 50,
    status: site.status,
  }
  modalOpen.value = true
}

async function fetchWebsites() {
  loading.value = true
  errorMessage.value = null
  try {
    const query: Record<string, string | number> = { page: 1, page_size: 50 }
    if (uiStore.selectedBrandId !== null) {
      query.brand_id = uiStore.selectedBrandId
    }
    if (statusFilter.value !== 'all') {
      query.status = statusFilter.value
    }
    if (searchQuery.value.trim()) {
      query.search = searchQuery.value.trim()
    }
    websitesData.value = await request<WebsiteListResponse>('/api/v1/websites', { query })
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to load registered websites.')
  }
  finally {
    loading.value = false
  }
}

async function submitForm() {
  if (!form.value.brand_id || !form.value.name.trim() || !form.value.domain.trim()) {
    toast.add({ title: 'Brand, website name, and domain are required', color: 'error' })
    return
  }
  saving.value = true
  try {
    const body = {
      brand_id: Number(form.value.brand_id),
      name: form.value.name.trim(),
      domain: form.value.domain.trim(),
      website_type: form.value.website_type,
      discovery_method: form.value.discovery_method,
      rss_url: form.value.rss_url.trim() || null,
      sitemap_url: form.value.sitemap_url.trim() || null,
      llms_url: form.value.llms_url.trim() || null,
      api_endpoint: form.value.api_endpoint.trim() || null,
      article_url_patterns: splitPatterns(form.value.article_url_patterns_text),
      excluded_url_patterns: splitPatterns(form.value.excluded_url_patterns_text),
      scan_interval_minutes: Number(form.value.scan_interval_minutes) || 360,
      auto_scan: form.value.auto_scan,
      auto_generate: form.value.auto_generate,
      baseline_mode: form.value.baseline_mode,
      baseline_limit: form.value.baseline_mode === 'latest_n' ? Number(form.value.baseline_limit) || 25 : null,
      status: form.value.status,
    }
    if (editingId.value !== null) {
      await request<Website>(`/api/v1/websites/${editingId.value}`, { method: 'PATCH', body })
      toast.add({ title: 'Website updated', color: 'success' })
    }
    else {
      await request<Website>('/api/v1/websites', { method: 'POST', body })
      toast.add({ title: 'Website registered', color: 'success' })
    }
    modalOpen.value = false
    await Promise.all([fetchWebsites(), uiStore.refreshGlobalSelectors()])
  }
  catch (err) {
    toast.add({ title: 'Save failed', description: extractErrorMessage(err), color: 'error' })
  }
  finally {
    saving.value = false
  }
}

async function triggerScan(site: Website) {
  scanningId.value = site.id
  try {
    const scan = await request<ScanLog>(`/api/v1/websites/${site.id}/scan`, { method: 'POST' })
    toast.add({
      title: `Scan #${scan.id} queued`,
      description: `Scanning '${site.name}' in background. Open Website Details to monitor progress.`,
      color: 'success',
    })
    await navigateTo(`/websites/${site.id}?scan=${scan.id}`)
  }
  catch (err) {
    toast.add({ title: 'Could not start scan', description: extractErrorMessage(err), color: 'error' })
  }
  finally {
    scanningId.value = null
  }
}

async function confirmDelete() {
  if (!deleteTarget.value) {
    return
  }
  deleting.value = true
  try {
    await request(`/api/v1/websites/${deleteTarget.value.id}`, { method: 'DELETE' })
    toast.add({ title: 'Website deleted', color: 'neutral' })
    deleteOpen.value = false
    deleteTarget.value = null
    await Promise.all([fetchWebsites(), uiStore.refreshGlobalSelectors()])
  }
  catch (err) {
    toast.add({ title: 'Delete blocked', description: extractErrorMessage(err), color: 'error' })
  }
  finally {
    deleting.value = false
  }
}

watch(
  () => uiStore.selectedBrandId,
  () => {
    void fetchWebsites()
  },
)

onMounted(async () => {
  if (!uiStore.filtersLoaded) {
    await uiStore.refreshGlobalSelectors()
  }
  await fetchWebsites()
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">
          Website Management
        </h1>
        <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          Register websites, configure SSRF-safe discovery sources, URL patterns, and trigger manual or scheduled scans.
        </p>
      </div>
      <UButton
        color="primary"
        size="sm"
        :disabled="uiStore.brandsCatalog.length === 0"
        @click="openCreateModal"
      >
        <Plus class="mr-1.5 h-4 w-4" />
        Register Website
      </UButton>
    </div>

    <UAlert
      v-if="uiStore.filtersLoaded && uiStore.brandsCatalog.length === 0"
      color="warning"
      variant="soft"
      title="Create a Brand first"
      description="Every monitored website belongs to a brand. Create at least one brand in Brand Management before registering websites."
    />

    <!-- Filter bar -->
    <form
      class="flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
      @submit.prevent="fetchWebsites()"
    >
      <div class="min-w-52 flex-1">
        <label class="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Search</label>
        <div class="relative">
          <Search class="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
          <UInput
            v-model="searchQuery"
            placeholder="Website name or domain..."
            class="w-full pl-8"
          />
        </div>
      </div>

      <div class="w-40">
        <label class="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">Status</label>
        <USelect
          v-model="statusFilter"
          :items="[
            { label: 'All Statuses', value: 'all' },
            { label: 'Active', value: 'active' },
            { label: 'Paused', value: 'paused' },
            { label: 'Error', value: 'error' },
            { label: 'Archived', value: 'archived' },
          ]"
          value-key="value"
          class="w-full"
          @update:model-value="fetchWebsites()"
        />
      </div>

      <UButton
        type="submit"
        color="neutral"
        variant="outline"
        size="sm"
      >
        Apply
      </UButton>
    </form>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="Unable to load websites"
      :message="errorMessage"
      retryable
      @retry="fetchWebsites()"
    />

    <div class="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <div
        v-if="loading"
        class="space-y-3 p-4"
      >
        <USkeleton
          v-for="idx in 4"
          :key="idx"
          class="h-10 w-full"
        />
      </div>

      <div
        v-else-if="!websitesData || websitesData.items.length === 0"
        class="p-6"
      >
        <AppEmptyState
          title="No websites registered"
          description="Register a WordPress, Nuxt, Next.js, PHP, static, or custom REST API website to begin monitoring."
        />
      </div>

      <div
        v-else
        class="overflow-x-auto"
      >
        <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
          <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
            <tr>
              <th class="px-4 py-2.5 font-medium">Website</th>
              <th class="px-4 py-2.5 font-medium">Brand</th>
              <th class="px-4 py-2.5 font-medium">Type / Method</th>
              <th class="px-4 py-2.5 font-medium">Articles</th>
              <th class="px-4 py-2.5 font-medium">Status</th>
              <th class="px-4 py-2.5 font-medium">Last Successful Scan</th>
              <th class="px-4 py-2.5 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
            <tr
              v-for="site in websitesData.items"
              :key="site.id"
              class="hover:bg-slate-50/70 dark:hover:bg-slate-800/40"
            >
              <td class="px-4 py-3">
                <NuxtLink
                  :to="`/websites/${site.id}`"
                  class="font-semibold text-teal-700 hover:underline dark:text-teal-300"
                >
                  {{ site.name }}
                </NuxtLink>
                <p class="font-mono text-[11px] text-slate-500">{{ site.domain }}</p>
              </td>
              <td class="px-4 py-3 text-slate-700 dark:text-slate-300">
                {{ site.brand_name || `#${site.brand_id}` }}
              </td>
              <td class="px-4 py-3 font-mono text-[11px] text-slate-600 dark:text-slate-400">
                {{ site.website_type }} / {{ site.discovery_method }}
              </td>
              <td class="px-4 py-3 font-medium">
                {{ site.article_count }}
              </td>
              <td class="px-4 py-3">
                <HealthStatusBadge :status="site.status" />
              </td>
              <td class="px-4 py-3 text-slate-500">
                {{ formatDateTime(site.last_successful_scan_at) }}
              </td>
              <td class="px-4 py-3 text-right">
                <div class="inline-flex items-center gap-1">
                  <UButton
                    color="primary"
                    variant="soft"
                    size="xs"
                    :loading="scanningId === site.id"
                    @click="triggerScan(site)"
                  >
                    <Play class="mr-1 h-3 w-3" />
                    Scan
                  </UButton>
                  <UButton
                    :to="`/websites/${site.id}`"
                    color="neutral"
                    variant="outline"
                    size="xs"
                  >
                    <Eye class="mr-1 h-3 w-3" />
                    Open
                  </UButton>
                  <UButton
                    color="neutral"
                    variant="ghost"
                    size="xs"
                    @click="openEditModal(site)"
                  >
                    Edit
                  </UButton>
                  <UButton
                    color="error"
                    variant="ghost"
                    size="xs"
                    aria-label="Delete website"
                    @click="deleteTarget = site; deleteOpen = true"
                  >
                    <Trash2 class="h-3.5 w-3.5" />
                  </UButton>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Register / Edit Website Modal -->
    <UModal
      v-model:open="modalOpen"
      :title="editingId ? 'Edit Website' : 'Register Website'"
      description="Configure website discovery sources, URL patterns, and first-scan baseline rules."
    >
      <template #body>
        <form
          class="space-y-3"
          @submit.prevent="submitForm"
        >
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <UFormField
              label="Brand"
              required
            >
              <USelect
                v-model="form.brand_id"
                :items="brandItems"
                value-key="value"
                class="w-full"
              />
            </UFormField>
            <UFormField
              label="Website Name"
              required
            >
              <UInput
                v-model="form.name"
                placeholder="e.g. Company Blog"
                class="w-full"
              />
            </UFormField>
          </div>

          <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <UFormField
              label="Domain"
              required
            >
              <UInput
                v-model="form.domain"
                placeholder="example.com"
                class="w-full"
              />
            </UFormField>
            <UFormField label="Website Type">
              <USelect
                v-model="form.website_type"
                :items="WEBSITE_TYPES"
                value-key="value"
                class="w-full"
              />
            </UFormField>
            <UFormField label="Discovery Method">
              <USelect
                v-model="form.discovery_method"
                :items="DISCOVERY_METHODS"
                value-key="value"
                class="w-full"
              />
            </UFormField>
          </div>

          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <UFormField label="RSS / Atom URL">
              <UInput
                v-model="form.rss_url"
                placeholder="https://example.com/feed/"
                class="w-full"
              />
            </UFormField>
            <UFormField label="Sitemap URL">
              <UInput
                v-model="form.sitemap_url"
                placeholder="https://example.com/sitemap.xml"
                class="w-full"
              />
            </UFormField>
            <UFormField label="llms.txt URL">
              <UInput
                v-model="form.llms_url"
                placeholder="https://example.com/llms.txt"
                class="w-full"
              />
            </UFormField>
            <UFormField label="Custom REST / WP API Endpoint">
              <UInput
                v-model="form.api_endpoint"
                placeholder="https://example.com/wp-json/wp/v2/posts"
                class="w-full"
              />
            </UFormField>
          </div>

          <UFormField label="Included Article URL Patterns (comma or newline separated)">
            <UInput
              v-model="form.article_url_patterns_text"
              placeholder="/blog/*, /articles/*, /news/*"
              class="w-full"
            />
          </UFormField>

          <UFormField label="Excluded URL Patterns">
            <UInput
              v-model="form.excluded_url_patterns_text"
              placeholder="/category/*, /tag/*, /author/*, /wp-admin/*, /search/*"
              class="w-full"
            />
          </UFormField>

          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <UFormField label="Scan Interval (minutes)">
              <UInput
                v-model.number="form.scan_interval_minutes"
                type="number"
                :min="15"
                class="w-full"
              />
            </UFormField>
            <UFormField label="First-Scan Baseline Mode">
              <USelect
                v-model="form.baseline_mode"
                :items="BASELINE_MODES"
                value-key="value"
                class="w-full"
              />
            </UFormField>
          </div>

          <UFormField
            v-if="form.baseline_mode === 'latest_n'"
            label="Latest N Articles Limit"
          >
            <UInput
              v-model.number="form.baseline_limit"
              type="number"
              :min="1"
              :max="500"
              class="w-full"
            />
          </UFormField>

          <div class="flex flex-wrap items-center gap-6 pt-2">
            <label class="flex items-center gap-2 text-xs font-medium">
              <USwitch v-model="form.auto_scan" />
              <span>Enable Scheduled Scanning</span>
            </label>
            <label class="flex items-center gap-2 text-xs font-medium">
              <USwitch v-model="form.auto_generate" />
              <span>Auto-Generate Drafts (Phase 3)</span>
            </label>
          </div>
        </form>
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton
            color="neutral"
            variant="outline"
            :disabled="saving"
            @click="modalOpen = false"
          >
            Cancel
          </UButton>
          <UButton
            color="primary"
            :loading="saving"
            @click="submitForm"
          >
            {{ editingId ? 'Save Changes' : 'Register Website' }}
          </UButton>
        </div>
      </template>
    </UModal>

    <AppConfirmDialog
      v-model:open="deleteOpen"
      title="Delete website?"
      :description="`Delete '${deleteTarget?.name || ''}'? Websites with stored articles cannot be deleted and should be archived instead.`"
      confirm-label="Delete Website"
      confirm-color="error"
      :loading="deleting"
      @confirm="confirmDelete"
    />
  </div>
</template>
