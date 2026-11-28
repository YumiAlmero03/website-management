<script setup lang="ts">
import {
  AlertTriangle,
  CheckCircle2,
  CheckSquare,
  ExternalLink,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Sparkles,
  XCircle,
} from 'lucide-vue-next'
import ContentKeywordEditorFields from '~/components/approval/ContentKeywordEditorFields.vue'
import type {
  AiKeywordSuggestionPreview,
  ApproveContentResult,
  ApprovedKeywordMapEntry,
  BulkApproveResult,
  ContentApprovalDetail,
  ContentApprovalItem,
  ContentApprovalListResponse,
  ContentApprovalStats,
  ImageAltSuggestionItem,
  KeywordMapListResponse,
} from '~/types/api'
import { getApprovalStatusMeta } from '~/utils/ai'
import {
  CONTENT_TYPE_OPTIONS,
  extractErrorMessage,
  formatDateTime,
  getContentTypeMeta,
} from '~/utils/format'
import {
  buildGamePageKeywords,
  buildSyncedAnchors,
  resolveInitialKeywordSuggestion,
  shouldAutoSyncAnchorsForMapping,
} from '~/utils/keywordSuggestions'

const { request } = useApiClient()
const uiStore = useUiStore()
const toast = useToast()

// Primary View Mode ('queue' vs 'keyword_map')
const viewMode = ref<'queue' | 'keyword_map'>('queue')

// Approval Queue State
const statusFilter = ref<string>('pending_review')
const websiteFilter = ref<string>(
  uiStore.selectedWebsiteId !== null ? String(uiStore.selectedWebsiteId) : 'all',
)
const contentTypeFilter = ref<string>('all')
const search = ref('')
const page = ref(1)
const pageSize = ref(20)

const items = ref<ContentApprovalItem[]>([])
const totalItems = ref(0)
const stats = ref<ContentApprovalStats>({
  total_eligible: 0,
  awaiting_extraction: 0,
  pending_review: 0,
  needs_rereview: 0,
  approved: 0,
  rejected: 0,
  cannibalization_flagged: 0,
})
const selectedIds = ref<number[]>([])
const loading = ref(true)
const errorMessage = ref<string | null>(null)
const busyId = ref<number | null>(null)
const bulkBusy = ref(false)

interface RowInlineEdit {
  content_type: string
  focus_keyphrase: string
  secondary_keywords_text: string
}
const rowEdits = ref<Record<number, RowInlineEdit>>({})

function parseSecondaryText(raw: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const part of raw.split(/[\n,]/)) {
    const clean = part.trim()
    const low = clean.toLowerCase()
    if (clean && !seen.has(low)) {
      seen.add(low)
      out.push(clean)
    }
  }
  return out
}

function findWebsiteMeta(websiteId: number) {
  return uiStore.websitesCatalog.find((w) => w.id === websiteId) ?? null
}

function buildRowEditDraft(item: ContentApprovalItem): RowInlineEdit {
  const resolved = resolveInitialKeywordSuggestion({
    content: item,
    keywordMapping: item.keyword_mapping,
    approvalStatus: item.status,
    website: findWebsiteMeta(item.website_id),
  })
  return {
    content_type: item.content_type,
    focus_keyphrase: resolved.focusKeyphrase,
    secondary_keywords_text: resolved.secondaryKeywords.join(', '),
  }
}

function isRowModifiedFromDraft(item: ContentApprovalItem): boolean {
  const draft = rowEdits.value[item.content_id]
  if (!draft) {
    return false
  }
  const base = buildRowEditDraft(item)
  const baseSecondaryNorm = parseSecondaryText(base.secondary_keywords_text)
    .map((k) => k.toLowerCase())
    .join('|')
  const draftSecondaryNorm = parseSecondaryText(draft.secondary_keywords_text)
    .map((k) => k.toLowerCase())
    .join('|')
  return (
    draft.content_type !== base.content_type
    || draft.focus_keyphrase.trim() !== base.focus_keyphrase.trim()
    || draftSecondaryNorm !== baseSecondaryNorm
  )
}

function handleRowTypeChange(item: ContentApprovalItem) {
  const draft = rowEdits.value[item.content_id]
  if (!draft) {
    return
  }
  if (
    draft.content_type === 'game_page'
    && !item.keyword_mapping?.is_admin_locked
    && item.keyword_mapping?.suggestion_source !== 'manual'
    && item.status !== 'approved'
  ) {
    const rawFocus = (item.keyword_mapping?.focus_keyphrase || '').trim()
    const rawSecNorm = (item.keyword_mapping?.secondary_keywords || [])
      .map((k) => k.trim().toLowerCase())
      .filter(Boolean)
      .join('|')
    const draftSecNorm = parseSecondaryText(draft.secondary_keywords_text)
      .map((k) => k.toLowerCase())
      .join('|')
    if (draft.focus_keyphrase.trim() === rawFocus && draftSecNorm === rawSecNorm) {
      const gameKeywords = buildGamePageKeywords(item, findWebsiteMeta(item.website_id))
      rowEdits.value = {
        ...rowEdits.value,
        [item.content_id]: {
          ...draft,
          focus_keyphrase: gameKeywords.focusKeyphrase,
          secondary_keywords_text: gameKeywords.secondaryKeywords.join(', '),
        },
      }
    }
  }
}

function isRowDirty(item: ContentApprovalItem): boolean {
  const draft = rowEdits.value[item.content_id]
  if (!draft) {
    return false
  }
  const origFocus = (item.keyword_mapping?.focus_keyphrase || '').trim()
  const origSecondaryNorm = (item.keyword_mapping?.secondary_keywords || [])
    .map((k) => k.trim().toLowerCase())
    .filter(Boolean)
    .join('|')
  const draftSecondaryNorm = parseSecondaryText(draft.secondary_keywords_text)
    .map((k) => k.toLowerCase())
    .join('|')
  return (
    draft.content_type !== item.content_type
    || draft.focus_keyphrase.trim() !== origFocus
    || draftSecondaryNorm !== origSecondaryNorm
  )
}

function resetRowInlineEdit(item: ContentApprovalItem) {
  rowEdits.value = {
    ...rowEdits.value,
    [item.content_id]: buildRowEditDraft(item),
  }
}

// Keyword Map View State
const mapEntries = ref<ApprovedKeywordMapEntry[]>([])
const mapTotal = ref(0)
const mapConflicts = ref(0)
const mapPage = ref(1)
const mapApprovedOnly = ref(true)
const mapLoading = ref(false)

// Review & Inline Keyword Editing Drawer/Modal State
const reviewModalOpen = ref(false)
const reviewLoading = ref(false)
const reviewDetail = ref<ContentApprovalDetail | null>(null)
const reviewSaving = ref(false)
const reviewAiRefining = ref(false)
const reviewForm = ref({
  content_type: 'blog_post',
  focus_keyphrase: '',
  secondary_keywords: [] as string[],
  anchor_text_variations: [] as string[],
  image_alt_suggestions: [] as ImageAltSuggestionItem[],
  review_note: '',
  trigger_auto_generation: true,
})
const rejectReasonInput = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(totalItems.value / pageSize.value)))
const mapTotalPages = computed(() => Math.max(1, Math.ceil(mapTotal.value / 25)))

const queueTabs = computed(() => [
  { key: 'pending_review', label: 'Pending Review', count: stats.value.pending_review },
  { key: 'needs_rereview', label: 'Needs Re-review', count: stats.value.needs_rereview },
  { key: 'awaiting_extraction', label: 'Awaiting Extraction', count: stats.value.awaiting_extraction },
  { key: 'approved', label: 'Approved', count: stats.value.approved },
  { key: 'rejected', label: 'Rejected', count: stats.value.rejected },
  { key: 'all', label: 'All Eligible', count: stats.value.total_eligible },
])

const selectablePageIds = computed(() =>
  items.value
    .filter((i) => i.extraction_status === 'extracted' && !i.is_excluded)
    .map((i) => i.content_id),
)

const allSelectedOnPage = computed(
  () =>
    selectablePageIds.value.length > 0
    && selectablePageIds.value.every((id) => selectedIds.value.includes(id)),
)

async function loadQueue() {
  loading.value = true
  errorMessage.value = null
  try {
    const query: Record<string, string | number> = {
      page: page.value,
      page_size: pageSize.value,
    }
    if (statusFilter.value !== 'all') {
      query.status = statusFilter.value
    }
    if (websiteFilter.value !== 'all') {
      query.website_id = Number(websiteFilter.value)
    }
    if (contentTypeFilter.value !== 'all') {
      query.content_type = contentTypeFilter.value
    }
    if (search.value.trim()) {
      query.search = search.value.trim()
    }
    const res = await request<ContentApprovalListResponse>('/api/v1/content-approvals', { query })
    items.value = res.items
    stats.value = res.stats
    totalItems.value = res.meta.total_items
    uiStore.setPendingApprovalsCount(
      (res.stats.pending_review || 0) + (res.stats.needs_rereview || 0),
    )
    selectedIds.value = selectedIds.value.filter((id) =>
      res.items.some((item) => item.content_id === id),
    )
    const initialEdits: Record<number, RowInlineEdit> = {}
    for (const item of res.items) {
      initialEdits[item.content_id] = buildRowEditDraft(item)
    }
    rowEdits.value = initialEdits
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to load Content Approval queue.')
  }
  finally {
    loading.value = false
  }
}

async function loadKeywordMap() {
  mapLoading.value = true
  try {
    const query: Record<string, string | number | boolean> = {
      page: mapPage.value,
      page_size: 25,
      approved_only: mapApprovedOnly.value,
    }
    if (websiteFilter.value !== 'all') {
      query.website_id = Number(websiteFilter.value)
    }
    if (contentTypeFilter.value !== 'all') {
      query.content_type = contentTypeFilter.value
    }
    if (search.value.trim()) {
      query.search = search.value.trim()
    }
    const res = await request<KeywordMapListResponse>('/api/v1/content-approvals/keyword-map', {
      query,
    })
    mapEntries.value = res.items
    mapTotal.value = res.meta.total_items
    mapConflicts.value = res.total_cannibalization_conflicts
  }
  catch (err) {
    toast.add({
      title: 'Failed to load Keyword Map',
      description: extractErrorMessage(err, 'Could not fetch keyword mappings.'),
      color: 'error',
    })
  }
  finally {
    mapLoading.value = false
  }
}

async function refreshActiveView() {
  if (viewMode.value === 'queue') {
    await loadQueue()
  }
  else {
    await Promise.all([loadQueue(), loadKeywordMap()])
  }
}

function toggleSelectAll() {
  if (allSelectedOnPage.value) {
    selectedIds.value = []
  }
  else {
    selectedIds.value = [...selectablePageIds.value]
  }
}

function toggleRowSelection(contentId: number) {
  if (selectedIds.value.includes(contentId)) {
    selectedIds.value = selectedIds.value.filter((id) => id !== contentId)
  }
  else {
    selectedIds.value = [...selectedIds.value, contentId]
  }
}

async function openReviewModal(contentId: number) {
  reviewModalOpen.value = true
  reviewLoading.value = true
  rejectReasonInput.value = ''
  try {
    const detail = await request<ContentApprovalDetail>(`/api/v1/content-approvals/${contentId}`)
    reviewDetail.value = detail
    const siteMeta = findWebsiteMeta(detail.website_id)
    const queueItem = items.value.find((i) => i.content_id === contentId)
    const rowDraft = rowEdits.value[contentId]
    const syncAnchors = shouldAutoSyncAnchorsForMapping(detail.keyword_mapping)

    if (queueItem && rowDraft && isRowModifiedFromDraft(queueItem)) {
      const cleanFocus = rowDraft.focus_keyphrase.trim()
      const cleanSec = parseSecondaryText(rowDraft.secondary_keywords_text)
      reviewForm.value = {
        content_type: rowDraft.content_type,
        focus_keyphrase: cleanFocus,
        secondary_keywords: cleanSec,
        anchor_text_variations: syncAnchors
          ? buildSyncedAnchors(cleanFocus, cleanSec)
          : [...(detail.keyword_mapping?.anchor_text_variations || [])],
        image_alt_suggestions: (detail.keyword_mapping?.image_alt_suggestions || []).map((a) => ({
          ...a,
        })),
        review_note: detail.review_note || '',
        trigger_auto_generation: true,
      }
    }
    else {
      const resolved = resolveInitialKeywordSuggestion({
        content: detail,
        keywordMapping: detail.keyword_mapping,
        approvalStatus: detail.status,
        website: siteMeta,
        overrideContentType: rowDraft?.content_type,
      })
      reviewForm.value = {
        content_type: rowDraft?.content_type || detail.content_type,
        focus_keyphrase: resolved.focusKeyphrase,
        secondary_keywords: resolved.secondaryKeywords,
        anchor_text_variations: resolved.anchorTextVariations,
        image_alt_suggestions: (detail.keyword_mapping?.image_alt_suggestions || []).map((a) => ({
          ...a,
        })),
        review_note: detail.review_note || '',
        trigger_auto_generation: true,
      }
    }
  }
  catch (err) {
    toast.add({
      title: 'Could not load content detail',
      description: extractErrorMessage(err, 'Failed to load review details.'),
      color: 'error',
    })
    reviewModalOpen.value = false
  }
  finally {
    reviewLoading.value = false
  }
}

async function requestAiKeywordRefinement() {
  if (!reviewDetail.value) {
    return
  }
  reviewAiRefining.value = true
  try {
    const preview = await request<AiKeywordSuggestionPreview>(
      `/api/v1/content-approvals/${reviewDetail.value.content_id}/keywords/suggest-ai`,
      {
        method: 'POST',
        body: { apply_immediately: false },
      },
    )
    reviewForm.value.focus_keyphrase = preview.focus_keyphrase
    reviewForm.value.secondary_keywords = [...preview.secondary_keywords]
    reviewForm.value.anchor_text_variations = buildSyncedAnchors(
      preview.focus_keyphrase,
      preview.secondary_keywords,
    )
    if (preview.image_alt_suggestions.length > 0) {
      reviewForm.value.image_alt_suggestions = preview.image_alt_suggestions.map((i) => ({ ...i }))
    }
    toast.add({
      title: preview.provider_name
        ? `${preview.provider_name} keyword suggestions ready`
        : 'LocalAI keyword refinement ready',
      description: 'Review inline edits below, then click Save or Approve & Save.',
      color: 'success',
    })
  }
  catch (err) {
    toast.add({
      title: 'LocalAI refinement unavailable',
      description: extractErrorMessage(err, 'Continue editing keywords manually below.'),
      color: 'warning',
    })
  }
  finally {
    reviewAiRefining.value = false
  }
}

async function saveInlineKeywordsOnly() {
  if (!reviewDetail.value) {
    return
  }
  if (reviewForm.value.focus_keyphrase.trim().length < 2) {
    toast.add({
      title: 'Focus keyphrase required',
      description: 'Enter at least 2 characters before saving.',
      color: 'warning',
    })
    return
  }
  reviewSaving.value = true
  try {
    const updated = await request<ContentApprovalDetail>(
      `/api/v1/content-approvals/${reviewDetail.value.content_id}/keywords`,
      {
        method: 'PATCH',
        body: {
          focus_keyphrase: reviewForm.value.focus_keyphrase.trim(),
          secondary_keywords: reviewForm.value.secondary_keywords,
          anchor_text_variations: reviewForm.value.anchor_text_variations,
          image_alt_suggestions: reviewForm.value.image_alt_suggestions,
          content_type: reviewForm.value.content_type,
          change_note: reviewForm.value.review_note.trim() || null,
        },
      },
    )
    reviewDetail.value = updated
    toast.add({
      title: 'Keyword edits saved',
      description: `Focus keyphrase set to "${updated.keyword_mapping?.focus_keyphrase}".`,
      color: 'success',
    })
    await refreshActiveView()
  }
  catch (err) {
    toast.add({
      title: 'Failed to save keywords',
      description: extractErrorMessage(err, 'Could not save keyword changes.'),
      color: 'error',
    })
  }
  finally {
    reviewSaving.value = false
  }
}

async function approveFromModal() {
  if (!reviewDetail.value) {
    return
  }
  if (reviewForm.value.focus_keyphrase.trim().length < 2) {
    toast.add({
      title: 'Focus keyphrase required before approval',
      description: 'Enter or refine the focus keyphrase before approving.',
      color: 'warning',
    })
    return
  }
  reviewSaving.value = true
  try {
    const res = await request<ApproveContentResult>(
      `/api/v1/content-approvals/${reviewDetail.value.content_id}/approve`,
      {
        method: 'POST',
        body: {
          focus_keyphrase: reviewForm.value.focus_keyphrase.trim(),
          secondary_keywords: reviewForm.value.secondary_keywords,
          anchor_text_variations: reviewForm.value.anchor_text_variations,
          image_alt_suggestions: reviewForm.value.image_alt_suggestions,
          content_type: reviewForm.value.content_type,
          review_note: reviewForm.value.review_note.trim() || null,
          trigger_auto_generation: reviewForm.value.trigger_auto_generation,
        },
      },
    )
    toast.add({
      title: 'Content & keywords approved',
      description: res.auto_generation_note || `Approved "${res.item.keyword_mapping?.focus_keyphrase}".`,
      color: 'success',
    })
    reviewModalOpen.value = false
    await refreshActiveView()
  }
  catch (err) {
    toast.add({
      title: 'Approval failed',
      description: extractErrorMessage(err, 'Could not approve content.'),
      color: 'error',
    })
  }
  finally {
    reviewSaving.value = false
  }
}

async function saveInlineRowOnly(item: ContentApprovalItem) {
  const draft = rowEdits.value[item.content_id]
  if (!draft) {
    return
  }
  if (draft.focus_keyphrase.trim().length < 2) {
    if (draft.content_type !== item.content_type && item.extraction_status !== 'extracted') {
      busyId.value = item.content_id
      try {
        await request(`/api/v1/contents/${item.content_id}`, {
          method: 'PATCH',
          body: {
            content_type: draft.content_type,
            manual_classification_override: true,
          },
        })
        toast.add({
          title: 'Content type updated',
          description: `Classified as "${getContentTypeMeta(draft.content_type).label}".`,
          color: 'success',
        })
        await refreshActiveView()
      }
      catch (err) {
        toast.add({
          title: 'Save failed',
          description: extractErrorMessage(err, 'Could not update content classification.'),
          color: 'error',
        })
      }
      finally {
        busyId.value = null
      }
      return
    }
    toast.add({
      title: 'Focus keyphrase required',
      description: 'Enter at least 2 characters before saving.',
      color: 'warning',
    })
    return
  }
  busyId.value = item.content_id
  try {
    const cleanFocus = draft.focus_keyphrase.trim()
    const cleanSecondary = parseSecondaryText(draft.secondary_keywords_text)
    const syncAnchors = shouldAutoSyncAnchorsForMapping(item.keyword_mapping)
    const nextAnchors = syncAnchors
      ? buildSyncedAnchors(cleanFocus, cleanSecondary)
      : (item.keyword_mapping?.anchor_text_variations || [cleanFocus])
    await request<ContentApprovalDetail>(`/api/v1/content-approvals/${item.content_id}/keywords`, {
      method: 'PATCH',
      body: {
        focus_keyphrase: cleanFocus,
        secondary_keywords: cleanSecondary,
        anchor_text_variations: nextAnchors,
        content_type: draft.content_type,
      },
    })
    toast.add({
      title: 'Inline keyword edits saved',
      description: `Updated "${cleanFocus}".`,
      color: 'success',
    })
    await refreshActiveView()
  }
  catch (err) {
    toast.add({
      title: 'Save failed',
      description: extractErrorMessage(err, 'Could not save inline row edits.'),
      color: 'error',
    })
  }
  finally {
    busyId.value = null
  }
}

async function quickApproveRow(item: ContentApprovalItem) {
  const draft = rowEdits.value[item.content_id]
  if (draft && draft.focus_keyphrase.trim().length < 2) {
    toast.add({
      title: 'Focus keyphrase required',
      description: 'Enter at least 2 characters before approving.',
      color: 'warning',
    })
    return
  }
  busyId.value = item.content_id
  try {
    const syncAnchors = shouldAutoSyncAnchorsForMapping(item.keyword_mapping)
    const bodyPayload: Record<string, unknown> = { trigger_auto_generation: true }
    if (draft && isRowDirty(item)) {
      const cleanFocus = draft.focus_keyphrase.trim()
      const cleanSecondary = parseSecondaryText(draft.secondary_keywords_text)
      bodyPayload.focus_keyphrase = cleanFocus
      bodyPayload.secondary_keywords = cleanSecondary
      bodyPayload.content_type = draft.content_type
      if (syncAnchors) {
        bodyPayload.anchor_text_variations = buildSyncedAnchors(cleanFocus, cleanSecondary)
      }
    }
    else if (syncAnchors && item.keyword_mapping?.focus_keyphrase) {
      bodyPayload.anchor_text_variations = buildSyncedAnchors(
        item.keyword_mapping.focus_keyphrase,
        item.keyword_mapping.secondary_keywords || [],
      )
    }
    const res = await request<ApproveContentResult>(
      `/api/v1/content-approvals/${item.content_id}/approve`,
      {
        method: 'POST',
        body: bodyPayload,
      },
    )
    toast.add({
      title: 'Approved content & keyword mapping',
      description: res.auto_generation_note || `Focus: ${res.item.keyword_mapping?.focus_keyphrase}`,
      color: 'success',
    })
    await refreshActiveView()
  }
  catch (err) {
    toast.add({
      title: 'Quick approval failed',
      description: extractErrorMessage(err, 'Open Review & Edit Keywords to resolve issues before approving.'),
      color: 'error',
    })
  }
  finally {
    busyId.value = null
  }
}

async function rejectContent(contentId: number, reason?: string) {
  busyId.value = contentId
  reviewSaving.value = true
  try {
    await request<ContentApprovalDetail>(`/api/v1/content-approvals/${contentId}/reject`, {
      method: 'POST',
      body: { reason: reason?.trim() || null },
    })
    toast.add({
      title: 'Content rejected',
      description: 'Excluded from AI generation unless updated cleanly on scan.',
      color: 'warning',
    })
    reviewModalOpen.value = false
    await refreshActiveView()
  }
  catch (err) {
    toast.add({
      title: 'Reject failed',
      description: extractErrorMessage(err, 'Could not reject content.'),
      color: 'error',
    })
  }
  finally {
    busyId.value = null
    reviewSaving.value = false
  }
}

async function reopenContent(contentId: number) {
  busyId.value = contentId
  reviewSaving.value = true
  try {
    await request<ContentApprovalDetail>(`/api/v1/content-approvals/${contentId}/reopen`, {
      method: 'POST',
      body: { note: 'Returned for administrator re-review' },
    })
    toast.add({ title: 'Returned to review queue', color: 'info' })
    reviewModalOpen.value = false
    await refreshActiveView()
  }
  catch (err) {
    toast.add({
      title: 'Return failed',
      description: extractErrorMessage(err, 'Could not return item to review.'),
      color: 'error',
    })
  }
  finally {
    busyId.value = null
    reviewSaving.value = false
  }
}

async function runBulkApprove() {
  if (selectedIds.value.length === 0) {
    return
  }
  bulkBusy.value = true
  try {
    const itemById = new Map(items.value.map((i) => [i.content_id, i]))
    const overrides = selectedIds.value
      .map((id) => {
        const item = itemById.get(id)
        const draft = rowEdits.value[id]
        if (!item) {
          return null
        }
        const syncAnchors = shouldAutoSyncAnchorsForMapping(item.keyword_mapping)
        if (draft && isRowDirty(item)) {
          const cleanFocus = draft.focus_keyphrase.trim()
          const cleanSecondary = parseSecondaryText(draft.secondary_keywords_text)
          return {
            content_id: id,
            content_type: draft.content_type,
            focus_keyphrase: cleanFocus || null,
            secondary_keywords: cleanSecondary,
            ...(syncAnchors
              ? { anchor_text_variations: buildSyncedAnchors(cleanFocus, cleanSecondary) }
              : {}),
          }
        }
        if (syncAnchors && item.keyword_mapping?.focus_keyphrase) {
          return {
            content_id: id,
            anchor_text_variations: buildSyncedAnchors(
              item.keyword_mapping.focus_keyphrase,
              item.keyword_mapping.secondary_keywords || [],
            ),
          }
        }
        return null
      })
      .filter((ov): ov is NonNullable<typeof ov> => ov !== null)
    const res = await request<BulkApproveResult>('/api/v1/content-approvals/bulk-approve', {
      method: 'POST',
      body: {
        content_ids: selectedIds.value,
        overrides,
        trigger_auto_generation: true,
      },
    })
    toast.add({
      title: `Approved ${res.total_approved} item(s)`,
      description:
        res.total_skipped > 0
          ? `${res.total_skipped} skipped (missing extraction or focus keyphrase).`
          : res.auto_generation_job_ids.length > 0
            ? `Queued ${res.auto_generation_job_ids.length} automatic social generation job(s).`
            : 'All selected content and keyword mappings approved.',
      color: res.total_approved > 0 ? 'success' : 'warning',
    })
    selectedIds.value = []
    await refreshActiveView()
  }
  catch (err) {
    toast.add({
      title: 'Bulk approve failed',
      description: extractErrorMessage(err, 'Could not complete bulk approval.'),
      color: 'error',
    })
  }
  finally {
    bulkBusy.value = false
  }
}

watch(
  () => uiStore.selectedWebsiteId,
  (val) => {
    websiteFilter.value = val !== null ? String(val) : 'all'
    page.value = 1
    mapPage.value = 1
    void refreshActiveView()
  },
)

watch([statusFilter, websiteFilter, contentTypeFilter], () => {
  page.value = 1
  mapPage.value = 1
  void refreshActiveView()
})

watch(viewMode, (mode) => {
  if (mode === 'keyword_map') {
    void loadKeywordMap()
  }
})

watch(mapApprovedOnly, () => {
  mapPage.value = 1
  void loadKeywordMap()
})

onMounted(async () => {
  await uiStore.refreshGlobalSelectors().catch(() => {})
  void loadQueue()
})
</script>

<template>
  <div class="space-y-5">
    <!-- Header -->
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">
          Content Approval & SEO Keyword Map
        </h1>
        <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          Review newly discovered pages & blog posts, edit focus & secondary keywords inline while approving, and prevent duplicate keyphrase cannibalization.
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <div class="inline-flex rounded-md border border-slate-200 bg-white p-0.5 dark:border-slate-700 dark:bg-slate-900">
          <button
            type="button"
            :class="[
              'rounded px-3 py-1.5 text-xs font-medium transition-colors',
              viewMode === 'queue'
                ? 'bg-teal-600 text-white'
                : 'text-slate-600 hover:text-slate-900 dark:text-slate-300',
            ]"
            @click="viewMode = 'queue'"
          >
            Approval Queue ({{ stats.pending_review + stats.needs_rereview }})
          </button>
          <button
            type="button"
            :class="[
              'rounded px-3 py-1.5 text-xs font-medium transition-colors',
              viewMode === 'keyword_map'
                ? 'bg-teal-600 text-white'
                : 'text-slate-600 hover:text-slate-900 dark:text-slate-300',
            ]"
            @click="viewMode = 'keyword_map'"
          >
            Keyword Map ({{ stats.approved }})
          </button>
        </div>

        <UButton
          color="neutral"
          variant="outline"
          size="xs"
          @click="refreshActiveView()"
        >
          <RefreshCw class="mr-1.5 h-3.5 w-3.5" />
          Refresh
        </UButton>
      </div>
    </div>

    <!-- Stats Summary Cards -->
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <div class="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
        <p class="text-[11px] text-slate-500">Pending Review</p>
        <p class="mt-1 text-lg font-semibold text-amber-600 dark:text-amber-400">
          {{ stats.pending_review }}
        </p>
      </div>
      <div class="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
        <p class="text-[11px] text-slate-500">Needs Re-review</p>
        <p class="mt-1 text-lg font-semibold text-rose-600 dark:text-rose-400">
          {{ stats.needs_rereview }}
        </p>
      </div>
      <div class="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
        <p class="text-[11px] text-slate-500">Awaiting Extraction</p>
        <p class="mt-1 text-lg font-semibold text-sky-600 dark:text-sky-400">
          {{ stats.awaiting_extraction }}
        </p>
      </div>
      <div class="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
        <p class="text-[11px] text-slate-500">Approved</p>
        <p class="mt-1 text-lg font-semibold text-emerald-600 dark:text-emerald-400">
          {{ stats.approved }}
        </p>
      </div>
      <div class="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
        <p class="text-[11px] text-slate-500">Rejected</p>
        <p class="mt-1 text-lg font-semibold text-slate-600 dark:text-slate-300">
          {{ stats.rejected }}
        </p>
      </div>
      <div class="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
        <p class="text-[11px] text-slate-500">Cannibalization Flags</p>
        <p class="mt-1 text-lg font-semibold text-amber-600 dark:text-amber-400">
          {{ viewMode === 'keyword_map' ? mapConflicts : stats.cannibalization_flagged }}
        </p>
      </div>
    </div>

    <!-- Filters Bar -->
    <div class="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
      <div class="relative flex-1 min-w-[200px]">
        <Search class="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
        <input
          v-model="search"
          type="text"
          placeholder="Search title, URL, or focus keyphrase..."
          class="h-8 w-full rounded-md border border-slate-200 bg-white pl-8 pr-3 text-xs text-slate-800 focus:border-teal-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
          @keydown.enter.prevent="refreshActiveView()"
        >
      </div>

      <select
        v-model="websiteFilter"
        aria-label="Filter by website"
        class="h-8 rounded-md border border-slate-200 bg-white px-2.5 text-xs text-slate-700 focus:border-teal-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
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
        v-model="contentTypeFilter"
        aria-label="Filter by content type"
        class="h-8 rounded-md border border-slate-200 bg-white px-2.5 text-xs text-slate-700 focus:border-teal-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
      >
        <option value="all">All Eligible Types</option>
        <option value="homepage">Homepage</option>
        <option value="page">Page</option>
        <option value="game_page">Game Page</option>
        <option value="blog_post">Blog Post</option>
      </select>

      <UButton
        color="primary"
        size="xs"
        @click="refreshActiveView()"
      >
        Filter
      </UButton>
    </div>

    <!-- QUEUE VIEW -->
    <template v-if="viewMode === 'queue'">
      <!-- Status Tabs -->
      <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-2 dark:border-slate-800">
        <div class="flex flex-wrap gap-1">
          <button
            v-for="tab in queueTabs"
            :key="tab.key"
            type="button"
            :class="[
              'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
              statusFilter === tab.key
                ? 'bg-teal-600 text-white'
                : 'bg-white text-slate-600 hover:bg-slate-100 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800',
            ]"
            @click="statusFilter = tab.key"
          >
            {{ tab.label }} ({{ tab.count }})
          </button>
        </div>

        <div
          v-if="selectedIds.length > 0"
          class="flex items-center gap-2"
        >
          <span class="text-xs font-medium text-teal-700 dark:text-teal-300">
            {{ selectedIds.length }} selected
          </span>
          <UButton
            color="primary"
            size="xs"
            :loading="bulkBusy"
            @click="runBulkApprove"
          >
            <CheckSquare class="mr-1.5 h-3.5 w-3.5" />
            Bulk Approve Selected
          </UButton>
        </div>
      </div>

      <AppErrorState
        v-if="errorMessage && !loading"
        title="Could not load approval queue"
        :message="errorMessage"
        retryable
        @retry="loadQueue()"
      />

      <USkeleton
        v-else-if="loading"
        class="h-64 w-full"
      />

      <AppEmptyState
        v-else-if="items.length === 0"
        title="No content items match this queue filter"
        description="Discovered homepages, pages, game pages, and blog posts automatically appear here after scanning."
      />

      <div
        v-else
        class="overflow-x-auto rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
      >
        <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
          <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
            <tr>
              <th class="w-9 px-3 py-2.5">
                <input
                  type="checkbox"
                  :checked="allSelectedOnPage"
                  aria-label="Select all extracted rows"
                  class="rounded border-slate-300"
                  @change="toggleSelectAll"
                >
              </th>
              <th class="px-3 py-2.5 font-medium">Content & Source URL</th>
              <th class="px-3 py-2.5 font-medium">Type & Extraction</th>
              <th class="px-3 py-2.5 font-medium">Focus & Secondary Keywords</th>
              <th class="px-3 py-2.5 font-medium">Approval</th>
              <th class="px-3 py-2.5 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
            <tr
              v-for="item in items"
              :key="item.content_id"
              class="hover:bg-slate-50/70 dark:hover:bg-slate-800/40"
            >
              <td class="px-3 py-3 align-top">
                <input
                  type="checkbox"
                  :disabled="item.extraction_status !== 'extracted'"
                  :checked="selectedIds.includes(item.content_id)"
                  :aria-label="`Select ${item.title}`"
                  class="rounded border-slate-300 disabled:opacity-40"
                  @change="toggleRowSelection(item.content_id)"
                >
              </td>
              <td class="max-w-xs px-3 py-3 align-top">
                <div class="font-semibold text-slate-900 dark:text-slate-100">
                  {{ item.title }}
                </div>
                <p
                  v-if="item.meta_title && item.meta_title !== item.title"
                  class="mt-0.5 text-[10px] text-slate-500"
                >
                  Meta Title: {{ item.meta_title }}
                </p>
                <div class="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
                  <span>{{ item.website_name || `Website #${item.website_id}` }}</span>
                  <span>·</span>
                  <a
                    :href="item.canonical_url"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="inline-flex items-center gap-0.5 font-mono text-teal-600 hover:underline dark:text-teal-400"
                  >
                    {{ item.canonical_url }}
                    <ExternalLink class="h-3 w-3" />
                  </a>
                </div>
                <div
                  v-if="item.keyword_mapping?.game_name || item.keyword_mapping?.provider_name"
                  class="mt-1 flex flex-wrap gap-1.5 text-[10px]"
                >
                  <span
                    v-if="item.keyword_mapping?.game_name"
                    class="rounded bg-slate-100 px-1.5 py-0.5 font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200"
                  >
                    Game: {{ item.keyword_mapping.game_name }}
                  </span>
                  <span
                    v-if="item.keyword_mapping?.provider_name"
                    class="rounded bg-teal-50 px-1.5 py-0.5 font-medium text-teal-700 dark:bg-teal-950/60 dark:text-teal-200"
                  >
                    Provider: {{ item.keyword_mapping.provider_name }}
                  </span>
                </div>
                <p
                  v-if="item.meta_description"
                  class="mt-1 line-clamp-2 text-[11px] text-slate-600 dark:text-slate-300"
                >
                  {{ item.meta_description }}
                </p>
                <div class="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-slate-400">
                  <span v-if="item.published_at">Published: {{ formatDateTime(item.published_at) }}</span>
                  <span>Discovered: {{ formatDateTime(item.first_discovered_at || item.created_at) }}</span>
                </div>
                <p
                  v-if="item.is_historical_baseline"
                  class="mt-0.5 text-[10px] text-slate-400"
                >
                  Baseline scan item (approval does not trigger auto social drafts)
                </p>
              </td>
              <td class="px-3 py-3 align-top">
                <div class="flex flex-col items-start gap-1.5">
                  <select
                    v-if="rowEdits[item.content_id]"
                    v-model="rowEdits[item.content_id]!.content_type"
                    aria-label="Content classification"
                    :disabled="busyId === item.content_id"
                    class="h-8 rounded border border-slate-200 bg-white px-2 text-xs text-slate-800 focus:border-teal-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                    @change="handleRowTypeChange(item)"
                  >
                    <option
                      v-for="opt in CONTENT_TYPE_OPTIONS"
                      :key="opt.value"
                      :value="opt.value"
                    >
                      {{ opt.label }}
                    </option>
                  </select>
                  <span class="text-[11px] text-slate-500">
                    {{ item.extraction_status }} · {{ item.word_count }} words
                  </span>
                </div>
              </td>
              <td class="min-w-[280px] max-w-md px-3 py-3 align-top">
                <div
                  v-if="rowEdits[item.content_id]"
                  class="space-y-2"
                >
                  <div>
                    <div class="mb-1 flex items-center justify-between gap-1.5">
                      <label
                        :for="`focus-kw-${item.content_id}`"
                        class="text-[10px] font-medium text-slate-500 dark:text-slate-400"
                      >
                        Focus Keyphrase
                      </label>
                      <div class="flex items-center gap-1">
                        <span
                          v-if="isRowDirty(item)"
                          class="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800 dark:bg-amber-900/50 dark:text-amber-300"
                        >
                          Unsaved
                        </span>
                        <span
                          v-if="item.cannibalization_warnings.length > 0"
                          class="inline-flex items-center gap-0.5 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800 dark:bg-amber-900/50 dark:text-amber-300"
                        >
                          <AlertTriangle class="h-3 w-3" />
                          {{ item.cannibalization_warnings.length }} overlap
                        </span>
                      </div>
                    </div>
                    <textarea
                      :id="`focus-kw-${item.content_id}`"
                      v-model="rowEdits[item.content_id]!.focus_keyphrase"
                      rows="2"
                      aria-label="Focus keyphrase"
                      placeholder="Enter primary focus keyphrase..."
                      class="w-full resize-y rounded border border-teal-300 bg-white px-2.5 py-1.5 text-xs font-medium leading-snug text-slate-900 focus:border-teal-600 focus:outline-none dark:border-teal-800 dark:bg-slate-950 dark:text-slate-100"
                    />
                  </div>
                  <div>
                    <label
                      :for="`secondary-kw-${item.content_id}`"
                      class="mb-1 block text-[10px] font-medium text-slate-500 dark:text-slate-400"
                    >
                      Secondary Keywords (comma or newline separated)
                    </label>
                    <textarea
                      :id="`secondary-kw-${item.content_id}`"
                      v-model="rowEdits[item.content_id]!.secondary_keywords_text"
                      rows="3"
                      aria-label="Secondary keywords"
                      placeholder="Secondary keywords (comma or new line separated)..."
                      class="w-full resize-y rounded border border-slate-200 bg-white px-2.5 py-1.5 text-xs leading-snug text-slate-800 focus:border-teal-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                    />
                  </div>
                  <p
                    v-if="!item.keyword_mapping && item.extraction_status !== 'extracted'"
                    class="text-[10px] text-slate-400"
                  >
                    Awaiting extraction suggestions (or pre-fill manually above)
                  </p>
                </div>
              </td>
              <td class="px-3 py-3 align-top">
                <UBadge
                  :color="getApprovalStatusMeta(item.status).color"
                  variant="subtle"
                  size="xs"
                >
                  {{ getApprovalStatusMeta(item.status).label }}
                </UBadge>
                <p
                  v-if="item.keyword_mapping?.keyword_generation_status === 'needs_metadata'"
                  class="mt-1 text-[10px] font-medium text-amber-600 dark:text-amber-400"
                >
                  Needs game metadata
                </p>
                <p
                  v-else-if="item.keyword_mapping?.keyword_generation_method"
                  class="mt-1 text-[10px] text-slate-400"
                >
                  Method: {{ item.keyword_mapping.keyword_generation_method }}
                </p>
                <p
                  v-if="item.keyword_mapping?.last_reviewed_at"
                  class="mt-0.5 text-[10px] text-slate-400"
                >
                  {{ formatDateTime(item.keyword_mapping.last_reviewed_at) }}
                </p>
              </td>
              <td class="px-3 py-3 align-top text-right">
                <div class="inline-flex flex-wrap justify-end gap-1.5">
                  <UButton
                    :color="isRowDirty(item) ? 'primary' : 'neutral'"
                    variant="outline"
                    size="xs"
                    :loading="busyId === item.content_id"
                    @click="saveInlineRowOnly(item)"
                  >
                    <Save class="mr-1 h-3 w-3" />
                    Save
                  </UButton>
                  <UButton
                    v-if="isRowModifiedFromDraft(item)"
                    color="neutral"
                    variant="ghost"
                    size="xs"
                    title="Discard unsaved row edits"
                    @click="resetRowInlineEdit(item)"
                  >
                    Reset
                  </UButton>
                  <UButton
                    color="neutral"
                    variant="outline"
                    size="xs"
                    @click="openReviewModal(item.content_id)"
                  >
                    Review
                  </UButton>
                  <UButton
                    v-if="item.extraction_status === 'extracted' && (item.status !== 'approved' || isRowDirty(item))"
                    color="primary"
                    size="xs"
                    :loading="busyId === item.content_id"
                    @click="quickApproveRow(item)"
                  >
                    <CheckCircle2 class="mr-1 h-3 w-3" />
                    Approve
                  </UButton>
                  <UButton
                    v-if="item.status !== 'rejected'"
                    color="error"
                    variant="ghost"
                    size="xs"
                    :loading="busyId === item.content_id"
                    @click="rejectContent(item.content_id)"
                  >
                    <XCircle class="h-3.5 w-3.5" />
                  </UButton>
                  <UButton
                    v-else
                    color="neutral"
                    variant="ghost"
                    size="xs"
                    :loading="busyId === item.content_id"
                    @click="reopenContent(item.content_id)"
                  >
                    <RotateCcw class="mr-1 h-3 w-3" />
                    Return
                  </UButton>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div
        v-if="totalPages > 1"
        class="flex items-center justify-between text-xs text-slate-500"
      >
        <span>Page {{ page }} of {{ totalPages }} ({{ totalItems }} items)</span>
        <div class="flex gap-2">
          <UButton
            size="xs"
            color="neutral"
            variant="outline"
            :disabled="page <= 1"
            @click="page--; loadQueue()"
          >
            Previous
          </UButton>
          <UButton
            size="xs"
            color="neutral"
            variant="outline"
            :disabled="page >= totalPages"
            @click="page++; loadQueue()"
          >
            Next
          </UButton>
        </div>
      </div>
    </template>

    <!-- KEYWORD MAP VIEW -->
    <template v-else>
      <div class="flex flex-wrap items-center justify-between gap-2">
        <label class="inline-flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
          <input
            v-model="mapApprovedOnly"
            type="checkbox"
            class="rounded border-slate-300"
          >
          Show only Approved Keyword Mappings (used for AI prompts & internal links)
        </label>
        <span class="text-xs text-slate-500">
          Showing {{ mapEntries.length }} of {{ mapTotal }} mapped URLs
        </span>
      </div>

      <USkeleton
        v-if="mapLoading"
        class="h-64 w-full"
      />

      <AppEmptyState
        v-else-if="mapEntries.length === 0"
        title="No keyword mappings found"
        description="Approve discovered content in the Approval Queue to build your reusable Keyword Map."
      />

      <div
        v-else
        class="overflow-x-auto rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
      >
        <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
          <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
            <tr>
              <th class="px-3 py-2.5 font-medium">Website & Target URL</th>
              <th class="px-3 py-2.5 font-medium">Focus Keyphrase</th>
              <th class="px-3 py-2.5 font-medium">Secondary Keywords</th>
              <th class="px-3 py-2.5 font-medium">Approved Anchors</th>
              <th class="px-3 py-2.5 font-medium">Status & Cannibalization</th>
              <th class="px-3 py-2.5 font-medium text-right">Edit</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
            <tr
              v-for="entry in mapEntries"
              :key="entry.content_id"
              class="hover:bg-slate-50/70 dark:hover:bg-slate-800/40"
            >
              <td class="max-w-xs px-3 py-3 align-top">
                <p class="font-semibold text-slate-900 dark:text-slate-100">
                  {{ entry.title }}
                </p>
                <p class="text-[11px] text-slate-500">
                  {{ entry.website_name }} · {{ entry.content_type }}
                </p>
                <a
                  :href="entry.canonical_url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="font-mono text-[11px] text-teal-600 hover:underline dark:text-teal-400"
                >
                  {{ entry.canonical_url }}
                </a>
              </td>
              <td class="px-3 py-3 align-top">
                <span class="rounded bg-teal-50 px-2 py-0.5 text-xs font-semibold text-teal-800 dark:bg-teal-950/60 dark:text-teal-200">
                  {{ entry.focus_keyphrase }}
                </span>
                <p class="mt-1 text-[10px] text-slate-400">
                  v{{ entry.keyword_version }}
                </p>
              </td>
              <td class="max-w-xs px-3 py-3 align-top">
                <div class="flex flex-wrap gap-1">
                  <span
                    v-for="sk in entry.secondary_keywords"
                    :key="sk"
                    class="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-700 dark:bg-slate-800 dark:text-slate-300"
                  >
                    {{ sk }}
                  </span>
                </div>
              </td>
              <td class="max-w-xs px-3 py-3 align-top">
                <div class="flex flex-wrap gap-1">
                  <span
                    v-for="anc in entry.anchor_text_variations"
                    :key="anc"
                    class="rounded border border-teal-200 bg-teal-50/60 px-1.5 py-0.5 text-[10px] text-teal-800 dark:border-teal-900/60 dark:bg-teal-950/30 dark:text-teal-200"
                  >
                    {{ anc }}
                  </span>
                </div>
              </td>
              <td class="px-3 py-3 align-top">
                <UBadge
                  :color="getApprovalStatusMeta(entry.approval_status).color"
                  variant="subtle"
                  size="xs"
                >
                  {{ getApprovalStatusMeta(entry.approval_status).label }}
                </UBadge>
                <div
                  v-if="entry.cannibalization_warnings.length > 0"
                  class="mt-1 flex items-center gap-1 text-[11px] text-amber-600 dark:text-amber-400"
                >
                  <AlertTriangle class="h-3.5 w-3.5 shrink-0" />
                  <span>{{ entry.cannibalization_warnings.length }} conflict(s)</span>
                </div>
              </td>
              <td class="px-3 py-3 align-top text-right">
                <UButton
                  size="xs"
                  color="neutral"
                  variant="outline"
                  @click="openReviewModal(entry.content_id)"
                >
                  Edit
                </UButton>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div
        v-if="mapTotalPages > 1"
        class="flex items-center justify-between text-xs text-slate-500"
      >
        <span>Page {{ mapPage }} of {{ mapTotalPages }}</span>
        <div class="flex gap-2">
          <UButton
            size="xs"
            color="neutral"
            variant="outline"
            :disabled="mapPage <= 1"
            @click="mapPage--; loadKeywordMap()"
          >
            Previous
          </UButton>
          <UButton
            size="xs"
            color="neutral"
            variant="outline"
            :disabled="mapPage >= mapTotalPages"
            @click="mapPage++; loadKeywordMap()"
          >
            Next
          </UButton>
        </div>
      </div>
    </template>

    <!-- Review & Inline Keyword Editing Modal -->
    <UModal
      v-model:open="reviewModalOpen"
      :ui="{ content: 'sm:max-w-4xl' }"
    >
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Review Content & Edit Keywords Inline
            </h2>
            <p
              v-if="reviewDetail"
              class="mt-0.5 text-xs text-slate-500"
            >
              {{ reviewDetail.website_name }} · {{ reviewDetail.canonical_url }}
            </p>
          </div>
          <UBadge
            v-if="reviewDetail"
            :color="getApprovalStatusMeta(reviewDetail.status).color"
            variant="subtle"
            size="xs"
          >
            {{ getApprovalStatusMeta(reviewDetail.status).label }}
          </UBadge>
        </div>
      </template>

      <template #body>
        <USkeleton
          v-if="reviewLoading"
          class="h-64 w-full"
        />

        <div
          v-else-if="reviewDetail"
          class="space-y-5 text-xs"
        >
          <!-- Extracted preview -->
          <div class="rounded-md border border-slate-200 bg-slate-50/60 p-3 dark:border-slate-800 dark:bg-slate-950/40">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <div class="font-semibold text-slate-900 dark:text-slate-100">
                {{ reviewDetail.title }}
              </div>
              <div class="flex items-center gap-2">
                <a
                  :href="reviewDetail.canonical_url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="inline-flex items-center gap-1 text-[11px] font-medium text-teal-600 hover:underline dark:text-teal-400"
                >
                  Open Original URL
                  <ExternalLink class="h-3 w-3" />
                </a>
                <NuxtLink
                  :to="`/content-library/${reviewDetail.content_id}`"
                  class="text-[11px] font-medium text-slate-600 underline dark:text-slate-300"
                >
                  Full Inspector
                </NuxtLink>
              </div>
            </div>
            <p
              v-if="reviewDetail.meta_description"
              class="mt-1 text-slate-600 dark:text-slate-300"
            >
              {{ reviewDetail.meta_description }}
            </p>
            <pre class="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded border border-slate-200 bg-white p-2.5 font-mono text-[11px] text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">{{ reviewDetail.markdown_content || reviewDetail.optimized_context_preview || 'No extracted text available.' }}</pre>
          </div>

          <!-- Inline Keyword & Reclassification Editor -->
          <ContentKeywordEditorFields
            v-model:focus-keyphrase="reviewForm.focus_keyphrase"
            v-model:secondary-keywords="reviewForm.secondary_keywords"
            v-model:anchor-text-variations="reviewForm.anchor_text_variations"
            v-model:image-alt-suggestions="reviewForm.image_alt_suggestions"
            v-model:content-type="reviewForm.content_type"
            :cannibalization-warnings="reviewDetail.cannibalization_warnings"
            :ai-refining="reviewAiRefining"
            :disabled="reviewSaving"
            @request-ai-refine="requestAiKeywordRefinement"
          />

          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label class="block text-[11px] font-medium text-slate-600 dark:text-slate-300">
                Reviewer / Edit Note (optional)
              </label>
              <input
                v-model="reviewForm.review_note"
                type="text"
                placeholder="Note why focus or classification was updated"
                class="mt-1 h-8 w-full rounded-md border border-slate-200 bg-white px-2.5 text-xs text-slate-800 focus:border-teal-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              >
            </div>
            <div class="flex items-end pb-1">
              <label class="inline-flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300">
                <input
                  v-model="reviewForm.trigger_auto_generation"
                  type="checkbox"
                  class="rounded border-slate-300"
                >
                Queue automatic social draft generation (new post-baseline blog posts)
              </label>
            </div>
          </div>

          <!-- Rejection Reason Quick Input -->
          <div class="rounded-md border border-slate-200 p-3 dark:border-slate-800">
            <label class="block text-[11px] font-medium text-slate-600 dark:text-slate-300">
              Rejection Reason (only used if rejecting)
            </label>
            <div class="mt-1 flex gap-2">
              <input
                v-model="rejectReasonInput"
                type="text"
                placeholder="e.g. Thin promotional URL or duplicate utility page"
                class="h-8 flex-1 rounded-md border border-slate-200 bg-white px-2.5 text-xs text-slate-800 focus:border-rose-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              >
              <UButton
                color="error"
                variant="outline"
                size="xs"
                :loading="reviewSaving"
                @click="rejectContent(reviewDetail.content_id, rejectReasonInput)"
              >
                <XCircle class="mr-1 h-3.5 w-3.5" />
                Reject Content
              </UButton>
              <UButton
                v-if="reviewDetail.status !== 'pending_review' && reviewDetail.status !== 'needs_rereview'"
                color="neutral"
                variant="outline"
                size="xs"
                :loading="reviewSaving"
                @click="reopenContent(reviewDetail.content_id)"
              >
                <RotateCcw class="mr-1 h-3.5 w-3.5" />
                Return for Review
              </UButton>
            </div>
          </div>

          <!-- Audit / History Preview -->
          <div
            v-if="reviewDetail.approval_history.length > 0"
            class="space-y-1 border-t border-slate-200 pt-2 text-[11px] text-slate-500 dark:border-slate-800"
          >
            <p class="font-medium text-slate-700 dark:text-slate-300">
              Recent Review History
            </p>
            <div
              v-for="h in reviewDetail.approval_history.slice(0, 4)"
              :key="h.id"
              class="flex flex-wrap items-center justify-between gap-2"
            >
              <span>{{ h.action }} ({{ h.from_status || 'new' }} → {{ h.to_status }}) {{ h.note ? `· ${h.note}` : '' }}</span>
              <span class="font-mono text-[10px]">{{ formatDateTime(h.created_at) }}</span>
            </div>
          </div>
        </div>
      </template>

      <template #footer>
        <div
          v-if="reviewDetail"
          class="flex w-full flex-wrap items-center justify-between gap-2"
        >
          <UButton
            color="neutral"
            variant="ghost"
            size="sm"
            :disabled="reviewSaving"
            @click="reviewModalOpen = false"
          >
            Close
          </UButton>

          <div class="flex flex-wrap gap-2">
            <UButton
              color="neutral"
              variant="outline"
              size="sm"
              :loading="reviewSaving"
              @click="saveInlineKeywordsOnly"
            >
              <Save class="mr-1.5 h-3.5 w-3.5" />
              Save Edits Only
            </UButton>

            <UButton
              color="primary"
              size="sm"
              :disabled="reviewDetail.extraction_status !== 'extracted'"
              :loading="reviewSaving"
              @click="approveFromModal"
            >
              <Sparkles class="mr-1.5 h-3.5 w-3.5" />
              Approve & Save Keywords
            </UButton>
          </div>
        </div>
      </template>
    </UModal>
  </div>
</template>
