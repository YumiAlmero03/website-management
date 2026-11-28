<script setup lang="ts">
import {
  Archive,
  CheckCircle2,
  Copy,
  Download,
  ExternalLink,
  History,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldAlert,
  Sparkles,
  XCircle,
} from 'lucide-vue-next'
import type {
  PlatformItem,
  SocialPostItem,
  SocialPostListResponse,
  SocialPostStats,
  SocialProfileItem,
} from '~/types/api'
import {
  buildAssembledSocialDraft,
  estimateAssembledLength,
  getDraftStatusMeta,
} from '~/utils/ai'
import { extractErrorMessage, formatDateTime } from '~/utils/format'

const route = useRoute()
const { request } = useApiClient()
const uiStore = useUiStore()
const toast = useToast()

const statusTab = ref<string>('all')
const platformFilter = ref<string>('all')
const profileFilter = ref<string>('all')
const page = ref(1)
const pageSize = ref(20)
const totalItems = ref(0)

const posts = ref<SocialPostItem[]>([])
const stats = ref<SocialPostStats>({
  total_drafts: 0,
  pending_review: 0,
  approved: 0,
  rejected: 0,
  generation_failed: 0,
  archived: 0,
})
const platforms = ref<PlatformItem[]>([])
const allProfiles = ref<SocialProfileItem[]>([])

const loading = ref(true)
const errorMessage = ref<string | null>(null)

// Inline Edit Modal State
const editModalOpen = ref(false)
const editTarget = ref<SocialPostItem | null>(null)
const savingEdit = ref(false)
const editForm = ref({
  title: '',
  caption: '',
  cta_text: '',
  hashtags_text: '',
})

// Reject Modal State
const rejectTarget = ref<SocialPostItem | null>(null)
const rejectReason = ref('')
const savingActionId = ref<number | null>(null)

// Revisions Modal
const revisionsOpen = ref(false)
const revisionsTarget = ref<SocialPostItem | null>(null)

const totalPages = computed(() => Math.max(1, Math.ceil(totalItems.value / pageSize.value)))

const visibleProfiles = computed(() => {
  const wid = uiStore.selectedWebsiteId
  return wid ? allProfiles.value.filter((p) => p.website_id === wid) : allProfiles.value
})

const editedPreviewAssembled = computed(() => {
  if (!editTarget.value) {
    return ''
  }
  const tags = editForm.value.hashtags_text
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter(Boolean)
  return buildAssembledSocialDraft({
    caption: editForm.value.caption,
    ctaText: editForm.value.cta_text,
    sourceUrl: editTarget.value.source_url,
    hashtags: tags,
  })
})

const editedCharCount = computed(() =>
  estimateAssembledLength(editedPreviewAssembled.value, editTarget.value?.platform_key),
)

async function loadMetadata() {
  try {
    const [platRes, profRes] = await Promise.all([
      request<PlatformItem[]>('/api/v1/platforms'),
      request<SocialProfileItem[]>('/api/v1/social-profiles'),
    ])
    platforms.value = platRes
    allProfiles.value = profRes
  }
  catch {
    // Non-blocking fallback if dropdown catalogs fail independently
  }
}

async function loadPosts() {
  loading.value = true
  errorMessage.value = null
  try {
    const queryWid = route.query.website_id
      ? Number(route.query.website_id)
      : (uiStore.selectedWebsiteId ?? undefined)
    const queryContentId = route.query.website_content_id
      ? Number(route.query.website_content_id)
      : undefined

    const res = await request<SocialPostListResponse>('/api/v1/social-posts', {
      query: {
        website_id: queryWid,
        website_content_id: queryContentId,
        platform_id: platformFilter.value === 'all' ? undefined : Number(platformFilter.value),
        social_profile_id: profileFilter.value === 'all' ? undefined : Number(profileFilter.value),
        status: statusTab.value === 'all' ? undefined : statusTab.value,
        page: page.value,
        page_size: pageSize.value,
      },
    })
    posts.value = res.items
    stats.value = res.stats
    totalItems.value = res.meta.total_items
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to load generated social drafts.')
  }
  finally {
    loading.value = false
  }
}

function openEditModal(post: SocialPostItem) {
  editTarget.value = post
  editForm.value = {
    title: post.title || '',
    caption: post.caption,
    cta_text: post.cta_text || '',
    hashtags_text: post.hashtags.join(', '),
  }
  editModalOpen.value = true
}

async function saveEditedDraft() {
  if (!editTarget.value) {
    return
  }
  savingEdit.value = true
  try {
    const updated = await request<SocialPostItem>(`/api/v1/social-posts/${editTarget.value.id}`, {
      method: 'PATCH',
      body: {
        title: editForm.value.title.trim() || null,
        caption: editForm.value.caption.trim(),
        cta_text: editForm.value.cta_text.trim() || null,
        hashtags: editForm.value.hashtags_text
          .split(/[\n,]/)
          .map((s) => s.trim())
          .filter(Boolean),
      },
    })
    posts.value = posts.value.map((p) => (p.id === updated.id ? updated : p))
    editModalOpen.value = false
    toast.add({
      title: `Saved manual edit (v${updated.current_version})`,
      color: 'success',
    })
  }
  catch (err) {
    toast.add({
      title: 'Save failed',
      description: extractErrorMessage(err, 'Could not update social draft.'),
      color: 'error',
    })
  }
  finally {
    savingEdit.value = false
  }
}

async function approvePost(post: SocialPostItem) {
  savingActionId.value = post.id
  try {
    const updated = await request<SocialPostItem>(`/api/v1/social-posts/${post.id}/approve`, {
      method: 'POST',
    })
    posts.value = posts.value.map((p) => (p.id === updated.id ? updated : p))
    toast.add({ title: 'Draft approved for manual publishing', color: 'success' })
    void loadPosts()
  }
  catch (err) {
    toast.add({
      title: 'Approve failed',
      description: extractErrorMessage(err, 'Could not approve draft.'),
      color: 'error',
    })
  }
  finally {
    savingActionId.value = null
  }
}

async function confirmReject() {
  if (!rejectTarget.value) {
    return
  }
  savingActionId.value = rejectTarget.value.id
  try {
    const updated = await request<SocialPostItem>(
      `/api/v1/social-posts/${rejectTarget.value.id}/reject`,
      {
        method: 'POST',
        body: { reason: rejectReason.value.trim() || null },
      },
    )
    posts.value = posts.value.map((p) => (p.id === updated.id ? updated : p))
    rejectTarget.value = null
    rejectReason.value = ''
    toast.add({ title: 'Draft rejected', color: 'warning' })
    void loadPosts()
  }
  catch (err) {
    toast.add({
      title: 'Reject failed',
      description: extractErrorMessage(err, 'Could not reject draft.'),
      color: 'error',
    })
  }
  finally {
    savingActionId.value = null
  }
}

async function archivePost(post: SocialPostItem) {
  savingActionId.value = post.id
  try {
    await request<SocialPostItem>(`/api/v1/social-posts/${post.id}/archive`, { method: 'POST' })
    toast.add({ title: 'Draft archived', color: 'neutral' })
    await loadPosts()
  }
  catch (err) {
    toast.add({
      title: 'Archive failed',
      description: extractErrorMessage(err, 'Could not archive draft.'),
      color: 'error',
    })
  }
  finally {
    savingActionId.value = null
  }
}

async function regeneratePost(post: SocialPostItem) {
  savingActionId.value = post.id
  try {
    const job = await request<{ id: number }>(`/api/v1/social-posts/${post.id}/regenerate`, {
      method: 'POST',
      body: { context_mode: 'optimized', force: true },
    })
    toast.add({
      title: `Regeneration job #${job.id} queued`,
      description: 'Prior revisions remain preserved in history.',
      color: 'success',
    })
    setTimeout(() => {
      void loadPosts()
    }, 2500)
  }
  catch (err) {
    toast.add({
      title: 'Regeneration failed',
      description: extractErrorMessage(err, 'Could not queue draft regeneration.'),
      color: 'error',
    })
  }
  finally {
    savingActionId.value = null
  }
}

async function copyPostText(post: SocialPostItem) {
  try {
    await navigator.clipboard.writeText(post.assembled_content)
    toast.add({ title: 'Copied formatted post to clipboard', color: 'success' })
  }
  catch {
    toast.add({ title: 'Clipboard permission denied', color: 'warning' })
  }
}

function openRevisions(post: SocialPostItem) {
  revisionsTarget.value = post
  revisionsOpen.value = true
}

watch([statusTab, platformFilter, profileFilter, () => uiStore.selectedWebsiteId], () => {
  page.value = 1
  void loadPosts()
})

watch(page, () => {
  void loadPosts()
})

onMounted(async () => {
  await Promise.all([loadMetadata(), loadPosts()])
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">
          Social Media Drafts
        </h1>
        <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          Review, edit, approve, copy, or regenerate AI social drafts scoped strictly by website & social profile.
        </p>
      </div>
      <div class="flex items-center gap-2">
        <UButton
          to="/content-library"
          color="neutral"
          variant="outline"
          size="xs"
        >
          <Sparkles class="mr-1 h-3.5 w-3.5 text-teal-600" />
          Generate From Content Library
        </UButton>
        <UButton
          color="neutral"
          variant="outline"
          size="xs"
          :loading="loading"
          @click="loadPosts"
        >
          <RefreshCw class="mr-1 h-3.5 w-3.5" />
          Refresh
        </UButton>
      </div>
    </div>

    <div class="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50/70 px-3.5 py-2.5 text-xs text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200">
      <ShieldAlert class="mt-0.5 h-4 w-4 shrink-0" />
      <span>
        Manual Review &amp; Copy Mode (Phase 3): External live publishing &amp; auto-posting arrive in Phase 4. Use Copy Content + Download Media to post manually after approval.
      </span>
    </div>

    <!-- Status Tabs -->
    <div class="flex flex-wrap gap-1 border-b border-slate-200 dark:border-slate-800">
      <button
        v-for="tab in [
          { id: 'all', label: `All Drafts (${stats.total_drafts})` },
          { id: 'pending_review', label: `Pending Review (${stats.pending_review})` },
          { id: 'approved', label: `Approved (${stats.approved})` },
          { id: 'rejected', label: `Rejected (${stats.rejected})` },
          { id: 'generation_failed', label: `Generation Failed (${stats.generation_failed})` },
          { id: 'archived', label: `Archived (${stats.archived})` },
        ]"
        :key="tab.id"
        type="button"
        :class="[
          'border-b-2 px-3 py-2 text-xs font-medium transition-colors',
          statusTab === tab.id
            ? 'border-teal-600 text-teal-700 dark:text-teal-300'
            : 'border-transparent text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100',
        ]"
        @click="statusTab = tab.id"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Filter Toolbar -->
    <div class="flex flex-wrap items-center gap-3 text-xs">
      <select
        v-model="platformFilter"
        class="h-8 rounded-md border border-slate-200 bg-white px-2.5 dark:border-slate-700 dark:bg-slate-900"
      >
        <option value="all">All Platforms</option>
        <option
          v-for="plat in platforms"
          :key="plat.id"
          :value="String(plat.id)"
        >
          {{ plat.display_name }}
        </option>
      </select>
      <select
        v-model="profileFilter"
        class="h-8 rounded-md border border-slate-200 bg-white px-2.5 dark:border-slate-700 dark:bg-slate-900"
      >
        <option value="all">All Social Profiles</option>
        <option
          v-for="prof in visibleProfiles"
          :key="prof.id"
          :value="String(prof.id)"
        >
          {{ prof.website_name }} · {{ prof.profile_name }}
        </option>
      </select>
    </div>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="Social drafts unavailable"
      :message="errorMessage"
      retryable
      @retry="loadPosts()"
    />

    <div
      v-else-if="loading"
      class="grid grid-cols-1 gap-4 lg:grid-cols-2"
    >
      <USkeleton
        v-for="idx in 4"
        :key="idx"
        class="h-48 w-full"
      />
    </div>

    <AppEmptyState
      v-else-if="posts.length === 0"
      title="No social drafts match the active filter"
      description="Open an extracted article in Content Library and click Generate Content to create multi-profile social drafts."
    >
      <template #actions>
        <UButton to="/content-library" color="primary" size="xs">
          Go to Content Library
        </UButton>
      </template>
    </AppEmptyState>

    <div
      v-else
      class="grid grid-cols-1 gap-4 lg:grid-cols-2"
    >
      <article
        v-for="post in posts"
        :key="post.id"
        class="flex flex-col justify-between rounded-lg border border-slate-200 bg-white p-4 text-xs shadow-xs dark:border-slate-800 dark:bg-slate-900"
      >
        <div class="space-y-3">
          <div class="flex flex-wrap items-start justify-between gap-2">
            <div>
              <div class="flex flex-wrap items-center gap-1.5">
                <UBadge
                  :color="getDraftStatusMeta(post.status).color"
                  variant="subtle"
                  size="xs"
                >
                  {{ getDraftStatusMeta(post.status).label }}
                </UBadge>
                <UBadge color="neutral" variant="outline" size="xs">
                  {{ post.platform_display_name || post.platform_key }}
                </UBadge>
                <span class="font-semibold text-slate-900 dark:text-slate-100">
                  {{ post.social_profile_name }}
                </span>
                <UBadge v-if="post.is_manually_edited" color="info" variant="soft" size="xs">
                  Edited v{{ post.current_version }}
                </UBadge>
                <span v-else class="font-mono text-[10px] text-slate-400">v{{ post.current_version }}</span>
              </div>
              <p class="mt-1 text-[11px] text-slate-500">
                Website: <strong>{{ post.website_name }}</strong>
                <template v-if="post.source_title">
                  · Article:
                  <NuxtLink
                    v-if="post.website_content_id"
                    :to="`/content-library/${post.website_content_id}`"
                    class="text-teal-600 hover:underline dark:text-teal-400"
                  >
                    {{ post.source_title }}
                  </NuxtLink>
                </template>
              </p>
            </div>
            <span
              :class="[
                'font-mono text-[11px]',
                post.character_limit && post.character_count > post.character_limit
                  ? 'font-semibold text-rose-600'
                  : 'text-slate-500',
              ]"
            >
              {{ post.character_count }}/{{ post.character_limit ?? '∞' }} chars
            </span>
          </div>

          <div
            v-if="post.featured_image_url"
            class="flex items-center justify-between gap-2 rounded bg-slate-50 p-2 dark:bg-slate-950/60"
          >
            <div class="flex min-w-0 items-center gap-2">
              <img
                :src="post.featured_image_url"
                alt="Draft media"
                class="h-10 w-10 rounded object-cover"
              >
              <span class="truncate text-[11px] text-slate-500">Featured Media Attached</span>
            </div>
            <a
              :href="post.featured_image_url"
              download
              target="_blank"
              class="inline-flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-[11px] hover:bg-white dark:border-slate-700"
            >
              <Download class="h-3 w-3" />
              Media
            </a>
          </div>

          <div
            v-if="post.status === 'generation_failed'"
            class="rounded border border-rose-200 bg-rose-50 p-3 text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-200"
          >
            Generation failed: {{ post.error_message || 'Structured output validation failed.' }}
          </div>

          <pre
            v-else
            class="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-md bg-slate-50 p-3 font-sans text-xs text-slate-800 dark:bg-slate-950/60 dark:text-slate-200"
          >{{ post.assembled_content }}</pre>

          <div
            v-if="post.validation_warnings.length > 0"
            class="space-y-1 text-[11px] text-amber-700 dark:text-amber-300"
          >
            <p v-for="warn in post.validation_warnings" :key="warn">• {{ warn }}</p>
          </div>
          <p v-if="post.rejection_reason" class="text-[11px] text-rose-600">
            Rejection reason: {{ post.rejection_reason }}
          </p>
        </div>

        <div class="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3 dark:border-slate-800">
          <div class="flex flex-wrap gap-1.5">
            <UButton
              v-if="post.assembled_content"
              color="neutral"
              variant="outline"
              size="xs"
              @click="copyPostText(post)"
            >
              <Copy class="mr-1 h-3 w-3" />
              Copy
            </UButton>
            <UButton
              color="neutral"
              variant="outline"
              size="xs"
              @click="openEditModal(post)"
            >
              Edit
            </UButton>
            <UButton
              color="neutral"
              variant="ghost"
              size="xs"
              @click="openRevisions(post)"
            >
              <History class="h-3.5 w-3.5" />
            </UButton>
            <a
              v-if="post.source_url"
              :href="post.source_url"
              target="_blank"
              rel="noopener noreferrer"
              class="inline-flex items-center px-1.5 text-slate-400 hover:text-teal-600"
              title="Open source article"
            >
              <ExternalLink class="h-3.5 w-3.5" />
            </a>
          </div>

          <div class="flex flex-wrap gap-1">
            <UButton
              v-if="post.status !== 'approved' && post.status !== 'generation_failed'"
              color="success"
              variant="subtle"
              size="xs"
              :loading="savingActionId === post.id"
              @click="approvePost(post)"
            >
              <CheckCircle2 class="mr-1 h-3 w-3" />
              Approve
            </UButton>
            <UButton
              v-if="post.status !== 'rejected'"
              color="warning"
              variant="subtle"
              size="xs"
              :loading="savingActionId === post.id"
              @click="rejectTarget = post"
            >
              <XCircle class="mr-1 h-3 w-3" />
              Reject
            </UButton>
            <UButton
              color="primary"
              variant="subtle"
              size="xs"
              :loading="savingActionId === post.id"
              @click="regeneratePost(post)"
            >
              <RotateCcw class="mr-1 h-3 w-3" />
              Regenerate
            </UButton>
            <UButton
              v-if="post.status !== 'archived'"
              color="neutral"
              variant="ghost"
              size="xs"
              @click="archivePost(post)"
            >
              <Archive class="h-3.5 w-3.5" />
            </UButton>
          </div>
        </div>
      </article>
    </div>

    <div
      v-if="totalPages > 1"
      class="flex items-center justify-between text-xs text-slate-500"
    >
      <span>Page {{ page }} of {{ totalPages }} ({{ totalItems }} drafts)</span>
      <div class="flex gap-2">
        <UButton color="neutral" variant="outline" size="xs" :disabled="page <= 1" @click="page--">
          Previous
        </UButton>
        <UButton color="neutral" variant="outline" size="xs" :disabled="page >= totalPages" @click="page++">
          Next
        </UButton>
      </div>
    </div>

    <!-- Edit Draft Modal -->
    <UModal
      v-model:open="editModalOpen"
      :title="`Edit ${editTarget?.platform_display_name || ''} Draft`"
    >
      <template #body>
        <form class="space-y-3 text-xs" @submit.prevent="saveEditedDraft">
          <div v-if="editTarget?.platform_key === 'pinterest'">
            <label class="mb-1 block font-medium">Pin Title</label>
            <UInput v-model="editForm.title" size="sm" />
          </div>
          <div>
            <div class="mb-1 flex items-center justify-between">
              <label class="font-medium">Caption *</label>
              <span
                :class="[
                  'font-mono text-[11px]',
                  editTarget?.character_limit && editedCharCount > editTarget.character_limit
                    ? 'font-semibold text-rose-600'
                    : 'text-slate-500',
                ]"
              >
                Assembled: {{ editedCharCount }}/{{ editTarget?.character_limit ?? '∞' }}
              </span>
            </div>
            <UTextarea v-model="editForm.caption" :rows="5" size="sm" required />
          </div>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label class="mb-1 block font-medium">Call To Action (CTA)</label>
              <UInput v-model="editForm.cta_text" size="sm" />
            </div>
            <div>
              <label class="mb-1 block font-medium">Hashtags (Comma separated)</label>
              <UInput v-model="editForm.hashtags_text" size="sm" />
            </div>
          </div>
          <div>
            <label class="mb-1 block font-medium">Assembled Output Preview</label>
            <pre class="max-h-36 overflow-y-auto whitespace-pre-wrap rounded bg-slate-50 p-2.5 font-sans text-xs dark:bg-slate-950/60">{{ editedPreviewAssembled }}</pre>
          </div>
          <div class="flex justify-end gap-2 pt-2">
            <UButton type="button" color="neutral" variant="outline" size="xs" @click="editModalOpen = false">
              Cancel
            </UButton>
            <UButton type="submit" color="primary" size="xs" :loading="savingEdit">
              <Save class="mr-1 h-3.5 w-3.5" />
              Save Revision
            </UButton>
          </div>
        </form>
      </template>
    </UModal>

    <!-- Reject Reason Modal -->
    <UModal
      :open="Boolean(rejectTarget)"
      title="Reject Social Draft"
      @update:open="(val) => { if (!val) rejectTarget = null }"
    >
      <template #body>
        <form class="space-y-3 text-xs" @submit.prevent="confirmReject">
          <label class="block font-medium">Optional Rejection Reason</label>
          <UTextarea
            v-model="rejectReason"
            :rows="3"
            size="sm"
            placeholder="Explain why this draft needs edits or regeneration..."
          />
          <div class="flex justify-end gap-2">
            <UButton type="button" color="neutral" variant="outline" size="xs" @click="rejectTarget = null">
              Cancel
            </UButton>
            <UButton type="submit" color="warning" size="xs">
              Confirm Reject
            </UButton>
          </div>
        </form>
      </template>
    </UModal>

    <!-- Revisions Comparison Modal -->
    <SocialPostRevisionsModal
      :open="revisionsOpen"
      :post="revisionsTarget"
      @update:open="revisionsOpen = $event"
    />
  </div>
</template>
