<script setup lang="ts">
import { ArrowLeft, Ban, CheckCircle2, ExternalLink, RefreshCw, Sparkles } from 'lucide-vue-next'
import type { ContentDetail, ContentRevision } from '~/types/api'
import {
  CONTENT_TYPE_OPTIONS,
  extractErrorMessage,
  formatDateTime,
  getContentTypeMeta,
} from '~/utils/format'

const route = useRoute()
const { request } = useApiClient()
const toast = useToast()

const contentId = computed(() => Number(route.params.id))

const detail = ref<ContentDetail | null>(null)
const revisions = ref<ContentRevision[]>([])
const loading = ref(true)
const errorMessage = ref<string | null>(null)
const reprocessing = ref(false)
const savingClass = ref(false)
const selectedType = ref('page')
const activeTab = ref<'markdown' | 'extracted' | 'optimized' | 'structured' | 'html' | 'revisions'>('markdown')

async function loadContent() {
  loading.value = true
  errorMessage.value = null
  try {
    const [itemData, revData] = await Promise.all([
      request<ContentDetail>(`/api/v1/contents/${contentId.value}`),
      request<ContentRevision[]>(`/api/v1/contents/${contentId.value}/revisions`),
    ])
    detail.value = itemData
    revisions.value = revData
    selectedType.value = itemData.content_type
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to load content details.')
  }
  finally {
    loading.value = false
  }
}

async function applyClassification() {
  if (!detail.value || selectedType.value === detail.value.content_type) {
    return
  }
  savingClass.value = true
  try {
    const updated = await request<ContentDetail>(`/api/v1/contents/${contentId.value}`, {
      method: 'PATCH',
      body: {
        content_type: selectedType.value,
        manual_classification_override: true,
      },
    })
    detail.value = updated
    toast.add({
      title: 'Classification saved',
      description: 'Pinned type will be preserved across future scans.',
      color: 'success',
    })
  }
  catch (err) {
    toast.add({
      title: 'Classification failed',
      description: extractErrorMessage(err, 'Could not update content classification.'),
      color: 'error',
    })
  }
  finally {
    savingClass.value = false
  }
}

async function toggleExclude() {
  if (!detail.value) {
    return
  }
  savingClass.value = true
  try {
    detail.value = await request<ContentDetail>(`/api/v1/contents/${contentId.value}`, {
      method: 'PATCH',
      body: { is_excluded: !detail.value.is_excluded },
    })
    toast.add({
      title: detail.value.is_excluded ? 'URL excluded' : 'URL restored to Content Library',
      color: 'success',
    })
  }
  catch (err) {
    toast.add({
      title: 'Update failed',
      description: extractErrorMessage(err, 'Could not update exclusion status.'),
      color: 'error',
    })
  }
  finally {
    savingClass.value = false
  }
}

async function reprocessNow() {
  reprocessing.value = true
  try {
    const updated = await request<ContentDetail>(`/api/v1/contents/${contentId.value}/reprocess`, {
      method: 'POST',
    })
    detail.value = updated
    revisions.value = await request<ContentRevision[]>(`/api/v1/contents/${contentId.value}/revisions`)
    toast.add({
      title: updated.extraction_status === 'extracted' ? 'Content re-extracted' : 'Re-extraction reported failure',
      description: updated.extraction_error || `${updated.word_count} words extracted.`,
      color: updated.extraction_status === 'extracted' ? 'success' : 'warning',
    })
  }
  catch (err) {
    toast.add({
      title: 'Reprocess failed',
      description: extractErrorMessage(err, 'Could not reprocess URL.'),
      color: 'error',
    })
  }
  finally {
    reprocessing.value = false
  }
}

onMounted(() => {
  void loadContent()
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-3">
        <UButton
          to="/content-library"
          color="neutral"
          variant="outline"
          size="xs"
        >
          <ArrowLeft class="mr-1 h-3.5 w-3.5" />
          Back
        </UButton>
        <div>
          <h1 class="text-lg font-semibold text-slate-900 dark:text-slate-100">
            {{ detail?.title || `Content #${contentId}` }}
          </h1>
          <a
            v-if="detail"
            :href="detail.canonical_url"
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex items-center gap-1 font-mono text-xs text-teal-600 hover:underline dark:text-teal-400"
          >
            {{ detail.canonical_url }}
            <ExternalLink class="h-3 w-3" />
          </a>
        </div>
      </div>

      <div
        v-if="detail"
        class="flex flex-wrap items-center gap-2"
      >
        <div class="flex items-center gap-1.5">
          <select
            v-model="selectedType"
            aria-label="Manual content classification"
            class="h-8 rounded-md border border-slate-200 bg-white px-2 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
          >
            <option
              v-for="opt in CONTENT_TYPE_OPTIONS"
              :key="opt.value"
              :value="opt.value"
            >
              {{ opt.label }}
            </option>
          </select>
          <UButton
            size="xs"
            color="neutral"
            variant="outline"
            :disabled="selectedType === detail.content_type || savingClass"
            @click="applyClassification"
          >
            Pin Type
          </UButton>
        </div>

        <UButton
          color="primary"
          size="xs"
          :loading="reprocessing"
          @click="reprocessNow"
        >
          <RefreshCw class="mr-1.5 h-3.5 w-3.5" />
          Re-extract Now
        </UButton>

        <UButton
          :color="detail.is_excluded ? 'success' : 'error'"
          variant="outline"
          size="xs"
          :disabled="savingClass"
          @click="toggleExclude"
        >
          <CheckCircle2
            v-if="detail.is_excluded"
            class="mr-1 h-3.5 w-3.5"
          />
          <Ban
            v-else
            class="mr-1 h-3.5 w-3.5"
          />
          {{ detail.is_excluded ? 'Restore URL' : 'Exclude URL' }}
        </UButton>
      </div>
    </div>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="Could not inspect content"
      :message="errorMessage"
      retryable
      @retry="loadContent()"
    />

    <USkeleton
      v-else-if="loading"
      class="h-64 w-full"
    />

    <template v-else-if="detail">
      <!-- Extraction failure alert if present -->
      <div
        v-if="detail.extraction_status === 'failed'"
        class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-200"
      >
        <div>
          <p class="font-semibold">
            Extraction Failed {{ detail.http_status ? `(HTTP ${detail.http_status})` : '' }}
          </p>
          <p class="mt-0.5">{{ detail.extraction_error || 'The URL failed during fetch or parsing.' }}</p>
        </div>
        <UButton
          size="xs"
          color="error"
          :loading="reprocessing"
          @click="reprocessNow"
        >
          Retry Extraction
        </UButton>
      </div>

      <!-- Summary cards -->
      <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div class="rounded-lg border border-slate-200 bg-white p-4 text-xs dark:border-slate-800 dark:bg-slate-900">
          <p class="font-semibold text-slate-900 dark:text-slate-100">Classification & Provenance</p>
          <div class="mt-3 space-y-2">
            <div class="flex justify-between">
              <span class="text-slate-500">Type:</span>
              <UBadge
                :color="getContentTypeMeta(detail.content_type).color"
                variant="subtle"
                size="xs"
              >
                {{ getContentTypeMeta(detail.content_type).label }}
              </UBadge>
            </div>
            <div class="flex justify-between">
              <span class="text-slate-500">Classifier:</span>
              <span>{{ detail.classification_method }}{{ detail.manual_classification_override ? ' (pinned)' : '' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-slate-500">Sources:</span>
              <span class="font-mono">{{ detail.discovery_sources.join(', ') || '—' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-slate-500">Website:</span>
              <NuxtLink
                :to="`/websites/${detail.website_id}`"
                class="font-medium text-teal-600 hover:underline dark:text-teal-400"
              >
                {{ detail.website_name }}
              </NuxtLink>
            </div>
          </div>
        </div>

        <div class="rounded-lg border border-slate-200 bg-white p-4 text-xs dark:border-slate-800 dark:bg-slate-900">
          <p class="font-semibold text-slate-900 dark:text-slate-100">Extraction & Integrity</p>
          <div class="mt-3 space-y-2">
            <div class="flex justify-between">
              <span class="text-slate-500">Extraction:</span>
              <HealthStatusBadge
                :status="detail.extraction_status === 'extracted' ? 'ok' : detail.extraction_status === 'pending' ? 'warning' : 'error'"
                :label="detail.extraction_status"
              />
            </div>
            <div class="flex justify-between">
              <span class="text-slate-500">HTTP Status / Words:</span>
              <span class="font-mono">{{ detail.http_status ?? '—' }} · {{ detail.word_count }} words</span>
            </div>
            <div class="flex justify-between">
              <span class="text-slate-500">Language:</span>
              <span>{{ detail.language || '—' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-slate-500">Last Checked:</span>
              <span>{{ formatDateTime(detail.last_checked_at) }}</span>
            </div>
          </div>
        </div>

        <div class="rounded-lg border border-slate-200 bg-white p-4 text-xs dark:border-slate-800 dark:bg-slate-900">
          <p class="font-semibold text-slate-900 dark:text-slate-100">Keywords & Metadata</p>
          <p class="mt-2 line-clamp-2 text-slate-600 dark:text-slate-300">
            {{ detail.meta_description || 'No meta description found.' }}
          </p>
          <div class="mt-3 flex flex-wrap gap-1">
            <UBadge
              v-for="kw in detail.keywords.slice(0, 8)"
              :key="kw"
              color="neutral"
              variant="subtle"
              size="xs"
            >
              {{ kw }}
            </UBadge>
            <span
              v-if="detail.keywords.length === 0"
              class="text-slate-400"
            >
              No keywords extracted yet
            </span>
          </div>
        </div>
      </div>

      <!-- Content Viewer Tabs -->
      <div class="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div class="flex flex-wrap gap-1 border-b border-slate-200 px-4 pt-3 dark:border-slate-800">
          <button
            v-for="t in [
              { id: 'markdown', label: 'Markdown Body' },
              { id: 'optimized', label: 'AI Optimized Context' },
              { id: 'extracted', label: 'Extracted Text' },
              { id: 'structured', label: 'Structured Metadata JSON' },
              { id: 'html', label: 'Sanitized HTML' },
              { id: 'revisions', label: `Revisions (${revisions.length})` },
            ]"
            :key="t.id"
            type="button"
            :class="[
              'border-b-2 px-3 py-2 text-xs font-medium transition-colors',
              activeTab === t.id
                ? 'border-teal-600 text-teal-700 dark:text-teal-300'
                : 'border-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200',
            ]"
            @click="activeTab = t.id as typeof activeTab"
          >
            {{ t.label }}
          </button>
        </div>

        <div class="p-4 text-xs">
          <pre
            v-if="activeTab === 'markdown'"
            class="max-h-[34rem] overflow-auto whitespace-pre-wrap font-mono text-slate-800 dark:text-slate-200"
          >{{ detail.markdown_content || 'No Markdown extracted yet.' }}</pre>

          <div
            v-else-if="activeTab === 'optimized'"
            class="space-y-2"
          >
            <p class="flex items-center gap-1.5 text-[11px] text-teal-600 dark:text-teal-400">
              <Sparkles class="h-3.5 w-3.5" />
              Token-saving compacted context generated locally without AI calls:
            </p>
            <pre class="max-h-[32rem] overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-3 font-mono text-slate-800 dark:bg-slate-950 dark:text-slate-200">{{ detail.optimized_context || 'Not generated yet.' }}</pre>
          </div>

          <pre
            v-else-if="activeTab === 'extracted'"
            class="max-h-[34rem] overflow-auto whitespace-pre-wrap font-mono text-slate-700 dark:text-slate-300"
          >{{ detail.extracted_content || detail.markdown_content || 'No extracted text.' }}</pre>

          <pre
            v-else-if="activeTab === 'structured'"
            class="max-h-[34rem] overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-3 font-mono text-slate-700 dark:bg-slate-950 dark:text-slate-300"
          >{{ JSON.stringify(detail.structured_data_json || {}, null, 2) }}</pre>

          <pre
            v-else-if="activeTab === 'html'"
            class="max-h-[34rem] overflow-auto whitespace-pre-wrap font-mono text-slate-700 dark:text-slate-300"
          >{{ detail.original_content || 'No HTML stored.' }}</pre>

          <div
            v-else
            class="space-y-3"
          >
            <p
              v-if="revisions.length === 0"
              class="text-slate-500"
            >
              No previous content revisions recorded yet.
            </p>
            <div
              v-for="rev in revisions"
              :key="rev.id"
              class="rounded-md border border-slate-200 p-3 dark:border-slate-800"
            >
              <div class="flex items-center justify-between">
                <span class="font-semibold">Revision #{{ rev.revision_number }} · {{ rev.title }}</span>
                <span class="text-slate-400">{{ formatDateTime(rev.created_at) }}</span>
              </div>
              <pre class="mt-2 max-h-48 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-slate-600 dark:text-slate-300">{{ rev.markdown_content }}</pre>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
