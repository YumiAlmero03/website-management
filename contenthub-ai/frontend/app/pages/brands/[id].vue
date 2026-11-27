<script setup lang="ts">
import { ArrowLeft, Globe, Upload } from 'lucide-vue-next'
import type { BrandDetail } from '~/types/api'
import { extractErrorMessage, formatDateTime } from '~/utils/format'

const route = useRoute()
const { request } = useApiClient()
const uiStore = useUiStore()
const toast = useToast()

const brandId = computed(() => Number(route.params.id))
const brand = ref<BrandDetail | null>(null)
const loading = ref(true)
const uploadingLogo = ref(false)
const errorMessage = ref<string | null>(null)

async function loadBrand() {
  loading.value = true
  errorMessage.value = null
  try {
    brand.value = await request<BrandDetail>(`/api/v1/brands/${brandId.value}`)
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to load brand details.')
  }
  finally {
    loading.value = false
  }
}

async function handleLogoUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || !brand.value) {
    return
  }
  uploadingLogo.value = true
  try {
    const formData = new FormData()
    formData.append('file', file)
    await request(`/api/v1/brands/${brand.value.id}/logo`, {
      method: 'POST',
      body: formData,
    })
    toast.add({ title: 'Brand logo uploaded', color: 'success' })
    await Promise.all([loadBrand(), uiStore.refreshGlobalSelectors()])
  }
  catch (err) {
    toast.add({ title: 'Logo upload failed', description: extractErrorMessage(err), color: 'error' })
  }
  finally {
    uploadingLogo.value = false
    input.value = ''
  }
}

onMounted(() => {
  void loadBrand()
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <UButton
        to="/brands"
        color="neutral"
        variant="outline"
        size="xs"
      >
        <ArrowLeft class="mr-1 h-3.5 w-3.5" />
        Back to Brands
      </UButton>
    </div>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="Brand unavailable"
      :message="errorMessage"
      retryable
      @retry="loadBrand()"
    />

    <USkeleton
      v-if="loading"
      class="h-64 w-full"
    />

    <template v-else-if="brand">
      <div class="rounded-lg border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-slate-900">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div class="flex items-center gap-4">
            <img
              v-if="brand.logo_url"
              :src="brand.logo_url"
              :alt="`${brand.name} logo`"
              class="h-14 w-14 rounded-lg border border-slate-200 object-cover dark:border-slate-700"
            >
            <div
              v-else
              class="flex h-14 w-14 items-center justify-center rounded-lg bg-teal-50 text-lg font-bold text-teal-700 dark:bg-teal-950 dark:text-teal-300"
            >
              {{ brand.name.slice(0, 2).toUpperCase() }}
            </div>
            <div>
              <div class="flex items-center gap-2">
                <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">
                  {{ brand.name }}
                </h1>
                <HealthStatusBadge
                  :status="brand.is_active ? 'active' : 'neutral'"
                  :label="brand.is_active ? 'Active' : 'Archived'"
                />
              </div>
              <p class="font-mono text-xs text-slate-500">
                {{ brand.slug }} · Primary language: {{ brand.primary_language }}
              </p>
            </div>
          </div>

          <label class="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800">
            <Upload class="h-3.5 w-3.5" />
            <span>{{ uploadingLogo ? 'Uploading...' : 'Upload Logo' }}</span>
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif"
              class="hidden"
              :disabled="uploadingLogo"
              @change="handleLogoUpload"
            >
          </label>
        </div>

        <p
          v-if="brand.description"
          class="mt-4 text-sm text-slate-600 dark:text-slate-300"
        >
          {{ brand.description }}
        </p>

        <dl class="mt-6 grid grid-cols-1 gap-4 border-t border-slate-100 pt-4 text-xs sm:grid-cols-2 lg:grid-cols-3 dark:border-slate-800">
          <div>
            <dt class="text-slate-400">Target Audience</dt>
            <dd class="mt-0.5 font-medium text-slate-800 dark:text-slate-200">
              {{ brand.target_audience || '-' }}
            </dd>
          </div>
          <div>
            <dt class="text-slate-400">Target Country</dt>
            <dd class="mt-0.5 font-medium text-slate-800 dark:text-slate-200">
              {{ brand.target_country || '-' }}
            </dd>
          </div>
          <div>
            <dt class="text-slate-400">Secondary Languages</dt>
            <dd class="mt-0.5 font-medium text-slate-800 dark:text-slate-200">
              {{ brand.secondary_languages.length ? brand.secondary_languages.join(', ') : '-' }}
            </dd>
          </div>
          <div>
            <dt class="text-slate-400">Brand Tone</dt>
            <dd class="mt-0.5 font-medium text-slate-800 dark:text-slate-200">
              {{ brand.tone || '-' }}
            </dd>
          </div>
          <div>
            <dt class="text-slate-400">Default CTA</dt>
            <dd class="mt-0.5 font-medium text-slate-800 dark:text-slate-200">
              {{ brand.default_cta || '-' }}
            </dd>
          </div>
          <div>
            <dt class="text-slate-400">Default Hashtags</dt>
            <dd class="mt-0.5 font-medium text-slate-800 dark:text-slate-200">
              {{ brand.default_hashtags.length ? brand.default_hashtags.join(' ') : '-' }}
            </dd>
          </div>
          <div>
            <dt class="text-slate-400">Target Keywords</dt>
            <dd class="mt-0.5 font-medium text-slate-800 dark:text-slate-200">
              {{ brand.target_keywords.length ? brand.target_keywords.join(', ') : '-' }}
            </dd>
          </div>
          <div>
            <dt class="text-slate-400">Restricted Keywords</dt>
            <dd class="mt-0.5 font-medium text-slate-800 dark:text-slate-200">
              {{ brand.restricted_keywords.length ? brand.restricted_keywords.join(', ') : '-' }}
            </dd>
          </div>
        </dl>

        <div
          v-if="brand.writing_guidelines || brand.ai_instructions"
          class="mt-6 grid grid-cols-1 gap-4 border-t border-slate-100 pt-4 text-xs md:grid-cols-2 dark:border-slate-800"
        >
          <div>
            <p class="font-semibold text-slate-700 dark:text-slate-300">Writing Guidelines</p>
            <p class="mt-1 whitespace-pre-wrap text-slate-600 dark:text-slate-400">
              {{ brand.writing_guidelines || 'None configured.' }}
            </p>
          </div>
          <div>
            <p class="font-semibold text-slate-700 dark:text-slate-300">Custom AI Instructions (Phase 3)</p>
            <p class="mt-1 whitespace-pre-wrap text-slate-600 dark:text-slate-400">
              {{ brand.ai_instructions || 'None configured.' }}
            </p>
          </div>
        </div>
      </div>

      <!-- Associated Websites -->
      <section class="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div class="flex items-center justify-between border-b border-slate-200 px-5 py-3.5 dark:border-slate-800">
          <div class="flex items-center gap-2">
            <Globe class="h-4 w-4 text-teal-600" />
            <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Associated Websites ({{ brand.websites.length }})
            </h2>
          </div>
          <UButton
            to="/websites"
            color="primary"
            size="xs"
          >
            Manage Websites
          </UButton>
        </div>

        <div
          v-if="brand.websites.length === 0"
          class="p-5"
        >
          <AppEmptyState
            title="No websites linked to this brand"
            description="Register a website under this brand in the Websites module."
          />
        </div>

        <div
          v-else
          class="overflow-x-auto"
        >
          <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
            <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
              <tr>
                <th class="px-5 py-2.5 font-medium">Website</th>
                <th class="px-5 py-2.5 font-medium">Domain</th>
                <th class="px-5 py-2.5 font-medium">Type</th>
                <th class="px-5 py-2.5 font-medium">Status</th>
                <th class="px-5 py-2.5 font-medium">Last Successful Scan</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
              <tr
                v-for="site in brand.websites"
                :key="site.id"
              >
                <td class="px-5 py-2.5 font-medium text-teal-700 dark:text-teal-300">
                  <NuxtLink
                    :to="`/websites/${site.id}`"
                    class="hover:underline"
                  >
                    {{ site.name }}
                  </NuxtLink>
                </td>
                <td class="px-5 py-2.5 font-mono text-[11px]">{{ site.domain }}</td>
                <td class="px-5 py-2.5">{{ site.website_type }}</td>
                <td class="px-5 py-2.5">
                  <HealthStatusBadge :status="site.status" />
                </td>
                <td class="px-5 py-2.5 text-slate-500">
                  {{ formatDateTime(site.last_successful_scan_at) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>
