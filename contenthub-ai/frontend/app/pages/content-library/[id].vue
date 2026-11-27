<script setup lang="ts">
import { Archive, ArrowLeft, Copy, ExternalLink, RefreshCw, Sparkles } from 'lucide-vue-next'
import type { ArticleDetail, ArticleRevision } from '~/types/api'
import { extractErrorMessage, formatDateTime } from '~/utils/format'

const route = useRoute()
const { request } = useApiClient()
const toast = useToast()

const articleId = computed(() => Number(route.params.id))

const article = ref<ArticleDetail | null>(null)
const revisions = ref<ArticleRevision[]>([])
const loading = ref(true)
const reprocessing = ref(false)
const archiving = ref(false)
const errorMessage = ref<string | null>(null)
const activeTab = ref<'markdown' | 'optimized' | 'compare' | 'original' | 'revisions'>('markdown')

async function loadArticle() {
  loading.value = true
  errorMessage.value = null
  try {
    const [detail, revList] = await Promise.all([
      request<ArticleDetail>(`/api/v1/articles/${articleId.value}`),
      request<ArticleRevision[]>(`/api/v1/articles/${articleId.value}/revisions`),
    ])
    article.value = detail
    revisions.value = revList
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to load article details.')
  }
  finally {
    loading.value = false
  }
}

async function copyText(label: string, text: string | null | undefined) {
  if (!text) {
    toast.add({ title: `No ${label} available to copy`, color: 'warning' })
    return
  }
  if (import.meta.client && navigator.clipboard) {
    await navigator.clipboard.writeText(text)
    toast.add({ title: `${label} copied to clipboard`, color: 'success' })
  }
}

async function reprocessArticle() {
  if (!article.value) {
    return
  }
  reprocessing.value = true
  try {
    article.value = await request<ArticleDetail>(`/api/v1/articles/${article.value.id}/reprocess`, {
      method: 'POST',
    })
    revisions.value = await request<ArticleRevision[]>(
      `/api/v1/articles/${article.value.id}/revisions`,
    )
    toast.add({ title: 'Article re-extracted', color: 'success' })
  }
  catch (err) {
    toast.add({ title: 'Re-extraction failed', description: extractErrorMessage(err), color: 'error' })
  }
  finally {
    reprocessing.value = false
  }
}

async function toggleArchive() {
  if (!article.value) {
    return
  }
  archiving.value = true
  const nextStatus = article.value.status === 'archived' ? 'optimized' : 'archived'
  try {
    article.value = await request<ArticleDetail>(`/api/v1/articles/${article.value.id}`, {
      method: 'PATCH',
      body: { status: nextStatus },
    })
    toast.add({
      title: nextStatus === 'archived' ? 'Article archived' : 'Article restored',
      color: 'success',
    })
  }
  catch (err) {
    toast.add({ title: 'Status update failed', description: extractErrorMessage(err), color: 'error' })
  }
  finally {
    archiving.value = false
  }
}

onMounted(() => {
  void loadArticle()
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <UButton
        to="/content-library"
        color="neutral"
        variant="outline"
        size="xs"
      >
        <ArrowLeft class="mr-1 h-3.5 w-3.5" />
        Back to Content Library
      </UButton>

      <div
        v-if="article"
        class="flex flex-wrap items-center gap-2"
      >
        <UButton
          :to="article.canonical_url"
          target="_blank"
          rel="noopener noreferrer"
          color="neutral"
          variant="outline"
          size="xs"
        >
          <ExternalLink class="mr-1 h-3.5 w-3.5" />
          Open Original
        </UButton>
        <UButton
          color="neutral"
          variant="outline"
          size="xs"
          @click="copyText('Markdown', article.markdown_content)"
        >
          <Copy class="mr-1 h-3.5 w-3.5" />
          Copy Markdown
        </UButton>
        <UButton
          color="neutral"
          variant="outline"
          size="xs"
          @click="copyText('Optimized Context', article.optimized_context)"
        >
          <Copy class="mr-1 h-3.5 w-3.5" />
          Copy Optimized Context
        </UButton>
        <UButton
          color="neutral"
          variant="outline"
          size="xs"
          :loading="reprocessing"
          @click="reprocessArticle"
        >
          <RefreshCw class="mr-1 h-3.5 w-3.5" />
          Re-extract
        </UButton>
        <UButton
          color="neutral"
          variant="outline"
          size="xs"
          :loading="archiving"
          @click="toggleArchive"
        >
          <Archive class="mr-1 h-3.5 w-3.5" />
          {{ article.status === 'archived' ? 'Restore' : 'Archive' }}
        </UButton>
        <UTooltip text="Gemini social post generation will be implemented in Phase 3">
          <UButton
            color="primary"
            variant="soft"
            size="xs"
            disabled
          >
            <Sparkles class="mr-1 h-3.5 w-3.5" />
            Generate Social Post (Phase 3)
          </UButton>
        </UTooltip>
      </div>
    </div>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="Article unavailable"
      :message="errorMessage"
      retryable
      @retry="loadArticle()"
    />

    <USkeleton
      v-if="loading"
      class="h-72 w-full"
    />

    <template v-else-if="article">
      <!-- Metadata Overview -->
      <div class="rounded-lg border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-slate-900">
        <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div class="space-y-2">
            <div class="flex flex-wrap items-center gap-2">
              <HealthStatusBadge
                :status="article.status === 'optimized' || article.status === 'extracted' ? 'ok' : article.status"
                :label="article.status"
              />
              <UBadge
                v-if="article.is_historical_baseline"
                color="neutral"
                variant="subtle"
                size="sm"
              >
                Baseline Import
              </UBadge>
              <UBadge
                v-if="article.near_duplicate_of_id"
                color="warning"
                variant="subtle"
                size="sm"
              >
                Near-duplicate of #{{ article.near_duplicate_of_id }} ({{ article.near_duplicate_score }}%)
              </UBadge>
            </div>
            <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">
              {{ article.title }}
            </h1>
            <p
              v-if="article.meta_description"
              class="text-sm text-slate-600 dark:text-slate-300"
            >
              {{ article.meta_description }}
            </p>
            <p class="break-all font-mono text-xs text-slate-500">
              {{ article.canonical_url }}
            </p>
          </div>

          <img
            v-if="article.featured_image_url"
            :src="article.featured_image_url"
            :alt="article.featured_media?.alt_text || article.title"
            class="h-28 w-44 shrink-0 rounded-md border border-slate-200 object-cover dark:border-slate-700"
          >
        </div>

        <dl class="mt-5 grid grid-cols-2 gap-4 border-t border-slate-100 pt-4 text-xs sm:grid-cols-4 dark:border-slate-800">
          <div>
            <dt class="text-slate-400">Brand / Website</dt>
            <dd class="mt-0.5 font-medium">{{ article.brand_name || '-' }} · {{ article.website_name || '-' }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">Author / Language</dt>
            <dd class="mt-0.5 font-medium">{{ article.author || 'Unknown' }} · {{ article.language || '-' }}</dd>
          </div>
          <div>
            <dt class="text-slate-400">Word Count / Revisions</dt>
            <dd class="mt-0.5 font-medium">{{ article.word_count }} words · {{ article.revision_count }} revision(s)</dd>
          </div>
          <div>
            <dt class="text-slate-400">Published / Discovered</dt>
            <dd class="mt-0.5 font-medium">
              {{ formatDateTime(article.published_at) }}<br>{{ formatDateTime(article.discovered_at) }}
            </dd>
          </div>
        </dl>

        <div class="mt-4 flex flex-wrap gap-1.5">
          <UBadge
            v-for="kw in article.keywords"
            :key="kw"
            color="primary"
            variant="subtle"
            size="sm"
          >
            {{ kw }}
          </UBadge>
          <UBadge
            v-for="cat in article.categories"
            :key="`cat-${cat}`"
            color="neutral"
            variant="outline"
            size="sm"
          >
            {{ cat }}
          </UBadge>
        </div>

        <p class="mt-3 font-mono text-[11px] text-slate-400">
          URL SHA-256: {{ article.url_hash.slice(0, 16) }}… · Content SHA-256: {{ article.content_hash.slice(0, 16) }}…
        </p>
      </div>

      <!-- Content Tabs -->
      <div class="flex flex-wrap gap-2 border-b border-slate-200 pb-2 dark:border-slate-800">
        <UButton
          v-for="tab in [
            { id: 'markdown', label: 'Clean Markdown' },
            { id: 'optimized', label: 'Optimized Context (Token Prep)' },
            { id: 'compare', label: 'Side-by-Side Comparison' },
            { id: 'original', label: 'Sanitized Original Content' },
            { id: 'revisions', label: `Revision History (${revisions.length})` },
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

      <!-- Clean Markdown -->
      <div
        v-if="activeTab === 'markdown'"
        class="rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900"
      >
        <pre class="max-h-[36rem] overflow-auto whitespace-pre-wrap font-mono text-xs leading-relaxed text-slate-800 dark:text-slate-200">{{ article.markdown_content || 'No Markdown content extracted.' }}</pre>
      </div>

      <!-- Optimized Context -->
      <div
        v-else-if="activeTab === 'optimized'"
        class="space-y-3 rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900"
      >
        <p class="text-xs text-slate-500 dark:text-slate-400">
          Prepared natively in Python (YAKE keywords + extractive sentence selection, zero AI calls). Length:
          <strong>{{ (article.optimized_context || '').length }}</strong> chars vs Markdown
          <strong>{{ (article.markdown_content || '').length }}</strong> chars.
        </p>
        <pre class="max-h-[36rem] overflow-auto whitespace-pre-wrap rounded-md bg-slate-50 p-4 font-mono text-xs leading-relaxed text-slate-800 dark:bg-slate-950 dark:text-slate-200">{{ article.optimized_context || 'No optimized context available.' }}</pre>
      </div>

      <!-- Side-by-Side Comparison -->
      <div
        v-else-if="activeTab === 'compare'"
        class="grid grid-cols-1 gap-4 lg:grid-cols-2"
      >
        <div class="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <h2 class="mb-2 text-xs font-semibold text-slate-700 uppercase dark:text-slate-300">
            Clean Markdown ({{ (article.markdown_content || '').length }} chars)
          </h2>
          <pre class="max-h-[32rem] overflow-auto whitespace-pre-wrap font-mono text-xs leading-relaxed text-slate-700 dark:text-slate-300">{{ article.markdown_content || '-' }}</pre>
        </div>
        <div class="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <h2 class="mb-2 text-xs font-semibold text-teal-700 uppercase dark:text-teal-300">
            Optimized Context ({{ (article.optimized_context || '').length }} chars)
          </h2>
          <pre class="max-h-[32rem] overflow-auto whitespace-pre-wrap font-mono text-xs leading-relaxed text-slate-700 dark:text-slate-300">{{ article.optimized_context || '-' }}</pre>
        </div>
      </div>

      <!-- Sanitized Original (escaped text display — prevents XSS) -->
      <div
        v-else-if="activeTab === 'original'"
        class="rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900"
      >
        <p class="mb-2 text-xs text-slate-500">
          Displayed as escaped sanitized HTML source for reference and validation (never executed).
        </p>
        <pre class="max-h-[36rem] overflow-auto whitespace-pre-wrap font-mono text-xs leading-relaxed text-slate-700 dark:text-slate-300">{{ article.original_content || 'No original content stored.' }}</pre>
      </div>

      <!-- Revisions -->
      <div
        v-else-if="activeTab === 'revisions'"
        class="space-y-3 rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900"
      >
        <AppEmptyState
          v-if="revisions.length === 0"
          title="No prior revisions yet"
          description="Previous snapshots are automatically preserved here whenever an article's SHA-256 content hash changes on rescan."
        />
        <div
          v-for="rev in revisions"
          :key="rev.id"
          class="rounded-md border border-slate-200 p-4 dark:border-slate-800"
        >
          <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span class="font-semibold">Revision #{{ rev.revision_number }} — {{ rev.title }}</span>
            <span class="font-mono text-slate-500">{{ formatDateTime(rev.created_at) }} · {{ rev.content_hash.slice(0, 12) }}</span>
          </div>
          <pre class="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-3 font-mono text-[11px] text-slate-700 dark:bg-slate-950 dark:text-slate-300">{{ rev.markdown_content || '-' }}</pre>
        </div>
      </div>
    </template>
  </div>
</template>
