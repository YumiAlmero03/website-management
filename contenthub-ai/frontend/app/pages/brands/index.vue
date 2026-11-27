<script setup lang="ts">
import { Edit, Eye, Plus, Search, Trash2 } from 'lucide-vue-next'
import type { Brand, BrandListResponse } from '~/types/api'
import { extractErrorMessage } from '~/utils/format'

const { request } = useApiClient()
const uiStore = useUiStore()
const toast = useToast()

const LANGUAGE_OPTIONS = [
  { label: 'English (en)', value: 'en' },
  { label: 'Filipino (fil)', value: 'fil' },
  { label: 'Taglish (taglish)', value: 'taglish' },
  { label: 'Brazilian Portuguese (pt-BR)', value: 'pt-BR' },
  { label: 'Spanish (es)', value: 'es' },
  { label: 'Indonesian (id)', value: 'id' },
]

const STATUS_FILTERS = [
  { label: 'All Statuses', value: 'all' },
  { label: 'Active', value: 'active' },
  { label: 'Inactive / Archived', value: 'inactive' },
]

const brandsData = ref<BrandListResponse | null>(null)
const loading = ref(true)
const errorMessage = ref<string | null>(null)

const page = ref(1)
const searchQuery = ref('')
const statusFilter = ref('all')

const modalOpen = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)

const form = ref({
  name: '',
  slug: '',
  logo_url: '',
  description: '',
  target_audience: '',
  target_country: '',
  primary_language: 'en',
  secondary_languages_text: '',
  tone: '',
  target_keywords_text: '',
  restricted_keywords_text: '',
  default_hashtags_text: '',
  default_cta: '',
  writing_guidelines: '',
  ai_instructions: '',
  is_active: true,
})

const deleteTarget = ref<Brand | null>(null)
const deleteOpen = ref(false)
const deleting = ref(false)

function splitCsv(raw: string): string[] {
  return raw
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

function resetForm() {
  editingId.value = null
  form.value = {
    name: '',
    slug: '',
    logo_url: '',
    description: '',
    target_audience: '',
    target_country: '',
    primary_language: 'en',
    secondary_languages_text: '',
    tone: '',
    target_keywords_text: '',
    restricted_keywords_text: '',
    default_hashtags_text: '',
    default_cta: '',
    writing_guidelines: '',
    ai_instructions: '',
    is_active: true,
  }
}

function openCreateModal() {
  resetForm()
  modalOpen.value = true
}

function openEditModal(brand: Brand) {
  editingId.value = brand.id
  form.value = {
    name: brand.name,
    slug: brand.slug,
    logo_url: brand.logo_url || '',
    description: brand.description || '',
    target_audience: brand.target_audience || '',
    target_country: brand.target_country || '',
    primary_language: brand.primary_language,
    secondary_languages_text: brand.secondary_languages.join(', '),
    tone: brand.tone || '',
    target_keywords_text: brand.target_keywords.join(', '),
    restricted_keywords_text: brand.restricted_keywords.join(', '),
    default_hashtags_text: brand.default_hashtags.join(', '),
    default_cta: brand.default_cta || '',
    writing_guidelines: brand.writing_guidelines || '',
    ai_instructions: brand.ai_instructions || '',
    is_active: brand.is_active,
  }
  modalOpen.value = true
}

async function fetchBrands() {
  loading.value = true
  errorMessage.value = null
  try {
    const query: Record<string, string | number | boolean> = {
      page: page.value,
      page_size: 20,
    }
    if (searchQuery.value.trim()) {
      query.search = searchQuery.value.trim()
    }
    if (statusFilter.value === 'active') {
      query.is_active = true
    }
    else if (statusFilter.value === 'inactive') {
      query.is_active = false
    }
    brandsData.value = await request<BrandListResponse>('/api/v1/brands', { query })
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to load brands.')
  }
  finally {
    loading.value = false
  }
}

async function submitForm() {
  if (!form.value.name.trim()) {
    toast.add({ title: 'Brand name is required', color: 'error' })
    return
  }

  saving.value = true
  try {
    const body = {
      name: form.value.name.trim(),
      slug: form.value.slug.trim() || null,
      logo_url: form.value.logo_url.trim() || null,
      description: form.value.description.trim() || null,
      target_audience: form.value.target_audience.trim() || null,
      target_country: form.value.target_country.trim() || null,
      primary_language: form.value.primary_language.trim() || 'en',
      secondary_languages: splitCsv(form.value.secondary_languages_text),
      tone: form.value.tone.trim() || null,
      target_keywords: splitCsv(form.value.target_keywords_text),
      restricted_keywords: splitCsv(form.value.restricted_keywords_text),
      default_hashtags: splitCsv(form.value.default_hashtags_text),
      default_cta: form.value.default_cta.trim() || null,
      writing_guidelines: form.value.writing_guidelines.trim() || null,
      ai_instructions: form.value.ai_instructions.trim() || null,
      is_active: form.value.is_active,
    }

    if (editingId.value !== null) {
      await request<Brand>(`/api/v1/brands/${editingId.value}`, {
        method: 'PATCH',
        body,
      })
      toast.add({ title: 'Brand updated', color: 'success' })
    }
    else {
      await request<Brand>('/api/v1/brands', {
        method: 'POST',
        body,
      })
      toast.add({ title: 'Brand created', color: 'success' })
    }
    modalOpen.value = false
    await Promise.all([fetchBrands(), uiStore.refreshGlobalSelectors()])
  }
  catch (err) {
    toast.add({
      title: 'Save failed',
      description: extractErrorMessage(err),
      color: 'error',
    })
  }
  finally {
    saving.value = false
  }
}

async function toggleActive(brand: Brand) {
  try {
    await request<Brand>(`/api/v1/brands/${brand.id}`, {
      method: 'PATCH',
      body: { is_active: !brand.is_active },
    })
    toast.add({
      title: brand.is_active ? 'Brand archived' : 'Brand reactivated',
      color: 'success',
    })
    await Promise.all([fetchBrands(), uiStore.refreshGlobalSelectors()])
  }
  catch (err) {
    toast.add({ title: 'Update failed', description: extractErrorMessage(err), color: 'error' })
  }
}

function promptDelete(brand: Brand) {
  deleteTarget.value = brand
  deleteOpen.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) {
    return
  }
  deleting.value = true
  try {
    await request(`/api/v1/brands/${deleteTarget.value.id}`, { method: 'DELETE' })
    toast.add({ title: 'Brand deleted', color: 'neutral' })
    deleteOpen.value = false
    deleteTarget.value = null
    await Promise.all([fetchBrands(), uiStore.refreshGlobalSelectors()])
  }
  catch (err) {
    toast.add({
      title: 'Delete blocked',
      description: extractErrorMessage(err),
      color: 'error',
    })
  }
  finally {
    deleting.value = false
  }
}

onMounted(() => {
  void fetchBrands()
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">
          Brand Management
        </h1>
        <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          Configure brand profiles, languages (English, Filipino, Taglish, pt-BR, custom), tone, keywords, and CTAs.
        </p>
      </div>
      <UButton
        color="primary"
        size="sm"
        @click="openCreateModal"
      >
        <Plus class="mr-1.5 h-4 w-4" />
        New Brand
      </UButton>
    </div>

    <!-- Filters -->
    <form
      class="flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
      @submit.prevent="page = 1; fetchBrands()"
    >
      <div class="min-w-52 flex-1">
        <label class="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">
          Search brands
        </label>
        <div class="relative">
          <Search class="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
          <UInput
            v-model="searchQuery"
            placeholder="Name, slug, or target country..."
            class="w-full pl-8"
          />
        </div>
      </div>

      <div class="w-44">
        <label class="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">
          Status
        </label>
        <USelect
          v-model="statusFilter"
          :items="STATUS_FILTERS"
          value-key="value"
          class="w-full"
          @update:model-value="page = 1; fetchBrands()"
        />
      </div>

      <UButton
        type="submit"
        color="neutral"
        variant="outline"
        size="sm"
      >
        Filter
      </UButton>
    </form>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="Unable to load brands"
      :message="errorMessage"
      retryable
      @retry="fetchBrands()"
    />

    <div
      v-if="loading"
      class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3"
    >
      <USkeleton
        v-for="idx in 3"
        :key="idx"
        class="h-44 w-full"
      />
    </div>

    <div v-else-if="!brandsData || brandsData.items.length === 0">
      <AppEmptyState
        title="No brands configured yet"
        description="Create your first brand before registering monitored websites."
      >
        <template #actions>
          <UButton
            color="primary"
            size="sm"
            @click="openCreateModal"
          >
            <Plus class="mr-1.5 h-4 w-4" />
            Create Brand
          </UButton>
        </template>
      </AppEmptyState>
    </div>

    <div
      v-else
      class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3"
    >
      <div
        v-for="brand in brandsData.items"
        :key="brand.id"
        class="flex flex-col justify-between rounded-lg border border-slate-200 bg-white p-5 shadow-xs dark:border-slate-800 dark:bg-slate-900"
      >
        <div>
          <div class="flex items-start justify-between gap-3">
            <div class="flex min-w-0 items-center gap-3">
              <img
                v-if="brand.logo_url"
                :src="brand.logo_url"
                :alt="`${brand.name} logo`"
                class="h-10 w-10 shrink-0 rounded-md border border-slate-200 object-cover dark:border-slate-700"
              >
              <div
                v-else
                class="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-teal-50 text-sm font-semibold text-teal-700 dark:bg-teal-950 dark:text-teal-300"
              >
                {{ brand.name.slice(0, 2).toUpperCase() }}
              </div>
              <div class="min-w-0">
                <NuxtLink
                  :to="`/brands/${brand.id}`"
                  class="block truncate text-sm font-semibold text-slate-900 hover:text-teal-700 dark:text-slate-100 dark:hover:text-teal-300"
                >
                  {{ brand.name }}
                </NuxtLink>
                <p class="truncate font-mono text-[11px] text-slate-500">
                  {{ brand.slug }}
                </p>
              </div>
            </div>
            <HealthStatusBadge
              :status="brand.is_active ? 'active' : 'neutral'"
              :label="brand.is_active ? 'Active' : 'Archived'"
            />
          </div>

          <p
            v-if="brand.description"
            class="mt-3 line-clamp-2 text-xs text-slate-600 dark:text-slate-400"
          >
            {{ brand.description }}
          </p>

          <dl class="mt-4 grid grid-cols-2 gap-2 text-xs">
            <div>
              <dt class="text-slate-400">Primary Language</dt>
              <dd class="font-medium text-slate-800 dark:text-slate-200">
                {{ brand.primary_language }}
              </dd>
            </div>
            <div>
              <dt class="text-slate-400">Websites</dt>
              <dd class="font-medium text-slate-800 dark:text-slate-200">
                {{ brand.website_count }}
              </dd>
            </div>
            <div v-if="brand.target_country">
              <dt class="text-slate-400">Country</dt>
              <dd class="truncate font-medium text-slate-800 dark:text-slate-200">
                {{ brand.target_country }}
              </dd>
            </div>
            <div v-if="brand.tone">
              <dt class="text-slate-400">Tone</dt>
              <dd class="truncate font-medium text-slate-800 dark:text-slate-200">
                {{ brand.tone }}
              </dd>
            </div>
          </dl>
        </div>

        <div class="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3 dark:border-slate-800">
          <div class="flex items-center gap-1.5">
            <UButton
              :to="`/brands/${brand.id}`"
              color="neutral"
              variant="outline"
              size="xs"
            >
              <Eye class="mr-1 h-3.5 w-3.5" />
              Details
            </UButton>
            <UButton
              color="neutral"
              variant="ghost"
              size="xs"
              @click="openEditModal(brand)"
            >
              <Edit class="mr-1 h-3.5 w-3.5" />
              Edit
            </UButton>
          </div>
          <div class="flex items-center gap-1.5">
            <UButton
              color="neutral"
              variant="ghost"
              size="xs"
              @click="toggleActive(brand)"
            >
              {{ brand.is_active ? 'Archive' : 'Activate' }}
            </UButton>
            <UButton
              color="error"
              variant="ghost"
              size="xs"
              aria-label="Delete brand"
              @click="promptDelete(brand)"
            >
              <Trash2 class="h-3.5 w-3.5" />
            </UButton>
          </div>
        </div>
      </div>
    </div>

    <!-- Create / Edit Modal -->
    <UModal
      v-model:open="modalOpen"
      :title="editingId ? 'Edit Brand' : 'Create Brand'"
      description="Configure brand editorial identity, languages, keywords, and Phase 3 AI instructions."
    >
      <template #body>
        <form
          class="space-y-3"
          @submit.prevent="submitForm"
        >
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <UFormField
              label="Brand Name"
              required
            >
              <UInput
                v-model="form.name"
                placeholder="e.g. Manila Tech Journal"
                class="w-full"
              />
            </UFormField>
            <UFormField label="Slug (optional)">
              <UInput
                v-model="form.slug"
                placeholder="auto-generated-from-name"
                class="w-full"
              />
            </UFormField>
          </div>

          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <UFormField label="Primary Language">
              <USelect
                v-model="form.primary_language"
                :items="LANGUAGE_OPTIONS"
                value-key="value"
                class="w-full"
              />
            </UFormField>
            <UFormField label="Secondary Languages (comma-separated)">
              <UInput
                v-model="form.secondary_languages_text"
                placeholder="fil, taglish, pt-BR"
                class="w-full"
              />
            </UFormField>
          </div>

          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <UFormField label="Target Country">
              <UInput
                v-model="form.target_country"
                placeholder="Philippines"
                class="w-full"
              />
            </UFormField>
            <UFormField label="Brand Tone">
              <UInput
                v-model="form.tone"
                placeholder="Authoritative, practical, clear"
                class="w-full"
              />
            </UFormField>
          </div>

          <UFormField label="Target Audience">
            <UInput
              v-model="form.target_audience"
              placeholder="SEO specialists, founders, content managers"
              class="w-full"
            />
          </UFormField>

          <UFormField label="Logo URL (optional)">
            <UInput
              v-model="form.logo_url"
              placeholder="https://example.com/logo.png"
              class="w-full"
            />
          </UFormField>

          <UFormField label="Description">
            <UTextarea
              v-model="form.description"
              :rows="2"
              class="w-full"
            />
          </UFormField>

          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <UFormField label="Target Keywords (comma-separated)">
              <UInput
                v-model="form.target_keywords_text"
                placeholder="technical seo, content automation"
                class="w-full"
              />
            </UFormField>
            <UFormField label="Restricted Keywords (comma-separated)">
              <UInput
                v-model="form.restricted_keywords_text"
                placeholder="guaranteed, clickbait"
                class="w-full"
              />
            </UFormField>
          </div>

          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <UFormField label="Default Hashtags">
              <UInput
                v-model="form.default_hashtags_text"
                placeholder="#SEO, #ContentOps"
                class="w-full"
              />
            </UFormField>
            <UFormField label="Default CTA">
              <UInput
                v-model="form.default_cta"
                placeholder="Read the full guide on our site."
                class="w-full"
              />
            </UFormField>
          </div>

          <UFormField label="Writing Guidelines">
            <UTextarea
              v-model="form.writing_guidelines"
              :rows="2"
              class="w-full"
            />
          </UFormField>

          <UFormField label="Custom AI Instructions (stored for Phase 3)">
            <UTextarea
              v-model="form.ai_instructions"
              :rows="2"
              class="w-full"
            />
          </UFormField>

          <div class="flex items-center justify-between pt-2">
            <span class="text-xs font-medium text-slate-700 dark:text-slate-300">Brand Active</span>
            <USwitch v-model="form.is_active" />
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
            {{ editingId ? 'Save Changes' : 'Create Brand' }}
          </UButton>
        </div>
      </template>
    </UModal>

    <AppConfirmDialog
      v-model:open="deleteOpen"
      title="Delete brand permanently?"
      :description="`Permanently delete '${deleteTarget?.name || ''}'? Brands with associated websites cannot be deleted until websites are removed or reassigned.`"
      confirm-label="Delete Brand"
      confirm-color="error"
      :loading="deleting"
      @confirm="confirmDelete"
    />
  </div>
</template>
