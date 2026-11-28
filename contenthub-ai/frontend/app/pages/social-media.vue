<script setup lang="ts">
import {
  AlertTriangle,
  Archive,
  CalendarClock,
  CheckCircle2,
  ClipboardCheck,
  Copy,
  Download,
  ExternalLink,
  History,
  ImagePlus,
  RotateCcw,
  Save,
  ScrollText,
  Send,
  ShieldAlert,
  Wrench,
  XCircle,
} from 'lucide-vue-next'
import type {
  MediaAsset,
  MediaAssetListResponse,
  PlatformItem,
  PublicationRecordItem,
  PublishingHistoryListResponse,
  PublishingJobItem,
  PublishingJobListResponse,
  PublishingLogItem,
  PublishingPreflightResponse,
  PublishingStatisticsResponse,
  SocialPostItem,
  SocialPostListResponse,
  SocialPostMediaAttachment,
  SocialPostStats,
  SocialProfileItem,
} from '~/types/api'
import {
  buildAssembledSocialDraft,
  buildManualPublishChecklist,
  buildUrlWithUtm,
  estimateAssembledLength,
  formatUtcForLocalInput,
  getDraftStatusMeta,
  getPublishingStatusMeta,
  localInputToUtcIso,
  PUBLISHING_TZ_OPTIONS,
} from '~/utils/ai'
import { extractErrorMessage, formatDateTime } from '~/utils/format'

const route = useRoute()
const { request } = useApiClient()
const uiStore = useUiStore()
const toast = useToast()

const activeSection = ref<'queue' | 'history'>('queue')
const viewTab = ref<string>('drafts')
const platformFilter = ref<string>('all')
const profileFilter = ref<string>('all')
const searchFilter = ref<string>('')
const dateFrom = ref<string>('')
const dateTo = ref<string>('')
const page = ref(1)
const pageSize = ref(20)
const totalItems = ref(0)

const posts = ref<SocialPostItem[]>([])
const pubStats = ref<PublishingStatisticsResponse | null>(null)
const stats = ref<SocialPostStats>({
  total_drafts: 0,
  drafts: 0,
  pending_review: 0,
  approved: 0,
  rejected: 0,
  generation_failed: 0,
  archived: 0,
  scheduled: 0,
  publishing: 0,
  published: 0,
  manually_published: 0,
  failed_publishing: 0,
  verification_required: 0,
})
const platforms = ref<PlatformItem[]>([])
const allProfiles = ref<SocialProfileItem[]>([])

const loading = ref(true)
const errorMessage = ref<string | null>(null)
const savingActionId = ref<number | null>(null)

// Publication History state
const historyItems = ref<PublicationRecordItem[]>([])
const historyPage = ref(1)
const historyTotal = ref(0)
const historyLoading = ref(false)
const historyOutcomeFilter = ref<string>('all')
const historyMethodFilter = ref<string>('all')

// Enhanced Edit Modal (Caption + Alternative Captions + UTM Builder + Media Picker)
const editModalOpen = ref(false)
const editTarget = ref<SocialPostItem | null>(null)
const savingEdit = ref(false)
const websiteAssets = ref<MediaAsset[]>([])
const selectedMediaIds = ref<number[]>([])
const postAttachments = ref<SocialPostMediaAttachment[]>([])
const editForm = ref({
  title: '',
  caption: '',
  cta_text: '',
  hashtags_text: '',
  alternative_captions_text: '',
  utm_source: '',
  utm_medium: '',
  utm_campaign: '',
  utm_content: '',
})

// Reject Modal
const rejectTarget = ref<SocialPostItem | null>(null)
const rejectReason = ref('')

// Revisions Modal
const revisionsOpen = ref(false)
const revisionsTarget = ref<SocialPostItem | null>(null)

// Preflight + Publish Now Modal
const publishOpen = ref(false)
const publishTarget = ref<SocialPostItem | null>(null)
const preflightLoading = ref(false)
const preflightData = ref<PublishingPreflightResponse | null>(null)
const publishConfirmChecked = ref(false)
const paidApiConfirmChecked = ref(false)
const publishingNow = ref(false)

// Schedule / Reschedule Modal
const scheduleOpen = ref(false)
const scheduleTarget = ref<SocialPostItem | null>(null)
const scheduleLocalAt = ref('')
const scheduleTimezone = ref('Asia/Manila')
const schedulePaidConfirm = ref(false)
const savingSchedule = ref(false)

// Manual Publishing + Mark Published Modal
const manualOpen = ref(false)
const manualTarget = ref<SocialPostItem | null>(null)
const manualForm = ref({
  published_url: '',
  external_post_id: '',
  notes: '',
})
const savingManual = ref(false)

// Reconcile Modal (Verification Required)
const reconcileOpen = ref(false)
const reconcileTargetPost = ref<SocialPostItem | null>(null)
const reconcileTargetJob = ref<PublishingJobItem | null>(null)
const reconcileForm = ref({
  resolution: 'auto' as 'auto' | 'confirm_published' | 'confirm_missing',
  external_post_id: '',
  published_url: '',
  notes: '',
})
const savingReconcile = ref(false)

// Execution Logs Modal
const logsOpen = ref(false)
const logsTarget = ref<SocialPostItem | null>(null)
const logsList = ref<PublishingLogItem[]>([])
const logsLoading = ref(false)

const VIEW_TABS = computed(() => [
  { key: 'drafts', label: `All Drafts (${stats.value.total_drafts})` },
  { key: 'pending_review', label: `Pending Review (${stats.value.pending_review})` },
  { key: 'approved', label: `Approved (${stats.value.approved})` },
  { key: 'scheduled', label: `Scheduled (${stats.value.scheduled})` },
  { key: 'publishing', label: `Publishing (${stats.value.publishing})` },
  { key: 'published', label: `Published (${stats.value.published + stats.value.manually_published})` },
  {
    key: 'failed',
    label: `Failed / Verify (${stats.value.failed_publishing + stats.value.verification_required})`,
  },
  { key: 'manual_publishing', label: 'Manual Workflow' },
  { key: 'archived', label: `Archived (${stats.value.archived})` },
])

const totalPages = computed(() => Math.max(1, Math.ceil(totalItems.value / pageSize.value)))
const historyTotalPages = computed(() => Math.max(1, Math.ceil(historyTotal.value / 25)))

const visibleProfiles = computed(() => {
  if (uiStore.selectedWebsiteId === null) {
    return allProfiles.value
  }
  return allProfiles.value.filter((p) => p.website_id === uiStore.selectedWebsiteId)
})

const editUtmPreview = computed(() => {
  const src = editTarget.value?.source_url
  if (!src) {
    return ''
  }
  return buildUrlWithUtm(src, {
    utm_source: editForm.value.utm_source,
    utm_medium: editForm.value.utm_medium,
    utm_campaign: editForm.value.utm_campaign,
    utm_content: editForm.value.utm_content,
  })
})

const editedPreviewAssembled = computed(() => {
  if (!editTarget.value) {
    return ''
  }
  const tags = editForm.value.hashtags_text
    .split(',')
    .map((h) => h.trim())
    .filter(Boolean)
  return buildAssembledSocialDraft({
    caption: editForm.value.caption,
    ctaText: editForm.value.cta_text || null,
    sourceUrl: editUtmPreview.value || editTarget.value.source_url,
    hashtags: tags,
  })
})

const editedCharCount = computed(() =>
  estimateAssembledLength(editedPreviewAssembled.value, editTarget.value?.platform_key),
)

function profileForPost(post: SocialPostItem): SocialProfileItem | null {
  return allProfiles.value.find((p) => p.id === post.social_profile_id) || null
}

function getEffectiveTimezone(post: SocialPostItem): string {
  return post.display_timezone || profileForPost(post)?.effective_timezone || 'Asia/Manila'
}

async function loadMetadata() {
  try {
    const [plats, profs, pStats] = await Promise.all([
      request<PlatformItem[]>('/api/v1/platforms'),
      request<SocialProfileItem[]>('/api/v1/social-profiles'),
      request<PublishingStatisticsResponse>('/api/v1/publishing/statistics', {
        query: {
          website_id: uiStore.selectedWebsiteId ?? undefined,
          platform_id: platformFilter.value !== 'all' ? Number(platformFilter.value) : undefined,
        },
      }),
    ])
    platforms.value = plats
    allProfiles.value = profs
    pubStats.value = pStats
  }
  catch {
    // Non-blocking
  }
}

async function loadPosts() {
  loading.value = true
  errorMessage.value = null
  try {
    const query: Record<string, string | number | boolean | undefined> = {
      website_id: uiStore.selectedWebsiteId ?? undefined,
      view: viewTab.value,
      platform_id: platformFilter.value !== 'all' ? Number(platformFilter.value) : undefined,
      social_profile_id: profileFilter.value !== 'all' ? Number(profileFilter.value) : undefined,
      search: searchFilter.value.trim() || undefined,
      date_from: dateFrom.value ? `${dateFrom.value}T00:00:00Z` : undefined,
      date_to: dateTo.value ? `${dateTo.value}T23:59:59Z` : undefined,
      page: page.value,
      page_size: pageSize.value,
    }
    const res = await request<SocialPostListResponse>('/api/v1/social-posts', { query })
    posts.value = res.items
    totalItems.value = res.meta.total_items
    stats.value = res.stats
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to load social publishing items.')
  }
  finally {
    loading.value = false
  }
}

async function loadHistory() {
  historyLoading.value = true
  try {
    const selectedPlat = platforms.value.find((p) => String(p.id) === platformFilter.value)
    const res = await request<PublishingHistoryListResponse>('/api/v1/publishing/history', {
      query: {
        website_id: uiStore.selectedWebsiteId ?? undefined,
        social_profile_id: profileFilter.value !== 'all' ? Number(profileFilter.value) : undefined,
        platform_key: selectedPlat ? selectedPlat.platform_key : undefined,
        outcome: historyOutcomeFilter.value !== 'all' ? historyOutcomeFilter.value : undefined,
        publishing_method: historyMethodFilter.value !== 'all' ? historyMethodFilter.value : undefined,
        date_from: dateFrom.value ? `${dateFrom.value}T00:00:00Z` : undefined,
        date_to: dateTo.value ? `${dateTo.value}T23:59:59Z` : undefined,
        page: historyPage.value,
        page_size: 25,
      },
    })
    historyItems.value = res.items
    historyTotal.value = res.meta.total_items
  }
  catch (err) {
    toast.add({
      title: 'History load failed',
      description: extractErrorMessage(err, 'Could not fetch publication history.'),
      color: 'error',
    })
  }
  finally {
    historyLoading.value = false
  }
}

async function exportHistoryCsv() {
  try {
    const selectedPlat = platforms.value.find((p) => String(p.id) === platformFilter.value)
    const csvText = await request<string>('/api/v1/publishing/history/export', {
      query: {
        website_id: uiStore.selectedWebsiteId ?? undefined,
        social_profile_id: profileFilter.value !== 'all' ? Number(profileFilter.value) : undefined,
        platform_key: selectedPlat ? selectedPlat.platform_key : undefined,
        outcome: historyOutcomeFilter.value !== 'all' ? historyOutcomeFilter.value : undefined,
        publishing_method: historyMethodFilter.value !== 'all' ? historyMethodFilter.value : undefined,
      },
    })
    if (import.meta.client) {
      const blob = new Blob([csvText], { type: 'text/csv;charset=utf-8;' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'contenthub-publishing-history.csv'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    }
  }
  catch (err) {
    toast.add({
      title: 'CSV export failed',
      description: extractErrorMessage(err, 'Could not download history CSV.'),
      color: 'error',
    })
  }
}

async function openEditModal(post: SocialPostItem) {
  editTarget.value = post
  const utm = post.utm_params || {}
  editForm.value = {
    title: post.title || '',
    caption: post.caption,
    cta_text: post.cta_text || '',
    hashtags_text: post.hashtags.join(', '),
    alternative_captions_text: (post.alternative_captions || []).join('\n'),
    utm_source: utm.utm_source || post.platform_key || '',
    utm_medium: utm.utm_medium || 'social',
    utm_campaign: utm.utm_campaign || '',
    utm_content: utm.utm_content || '',
  }
  selectedMediaIds.value = []
  websiteAssets.value = []
  editModalOpen.value = true
  try {
    const [mediaRes, attRes] = await Promise.all([
      request<MediaAssetListResponse>('/api/v1/media', {
        query: { website_id: post.website_id, page: 1, page_size: 40 },
      }),
      request<SocialPostMediaAttachment[]>(`/api/v1/social-posts/${post.id}/media`),
    ])
    websiteAssets.value = mediaRes.items
    postAttachments.value = attRes
    if (attRes.length > 0) {
      selectedMediaIds.value = attRes.map((a) => a.media_asset_id)
    }
    else if (post.featured_media_id) {
      selectedMediaIds.value = [post.featured_media_id]
    }
  }
  catch {
    // Media picker optional if endpoint empty
  }
}

function toggleMediaAsset(assetId: number) {
  if (selectedMediaIds.value.includes(assetId)) {
    selectedMediaIds.value = selectedMediaIds.value.filter((id) => id !== assetId)
  }
  else {
    selectedMediaIds.value = [...selectedMediaIds.value, assetId]
  }
}

async function saveEditedDraft() {
  if (!editTarget.value || !editForm.value.caption.trim()) {
    return
  }
  savingEdit.value = true
  try {
    const tags = editForm.value.hashtags_text
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)
    const altCaps = editForm.value.alternative_captions_text
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean)
    const utmParams: Record<string, string> = {}
    if (editForm.value.utm_source.trim()) {
      utmParams.utm_source = editForm.value.utm_source.trim()
    }
    if (editForm.value.utm_medium.trim()) {
      utmParams.utm_medium = editForm.value.utm_medium.trim()
    }
    if (editForm.value.utm_campaign.trim()) {
      utmParams.utm_campaign = editForm.value.utm_campaign.trim()
    }
    if (editForm.value.utm_content.trim()) {
      utmParams.utm_content = editForm.value.utm_content.trim()
    }

    const updated = await request<SocialPostItem>(`/api/v1/social-posts/${editTarget.value.id}`, {
      method: 'PATCH',
      body: {
        title: editForm.value.title.trim() || null,
        caption: editForm.value.caption.trim(),
        cta_text: editForm.value.cta_text.trim() || null,
        hashtags: tags,
        alternative_captions: altCaps,
        utm_params: utmParams,
      },
    })

    // Sync attached media list if user modified attachments
    const origMediaIds = postAttachments.value.map((a) => a.media_asset_id)
    const changedMedia =
      selectedMediaIds.value.length !== origMediaIds.length
      || selectedMediaIds.value.some((id, idx) => origMediaIds[idx] !== id)
    if (changedMedia) {
      await request<SocialPostMediaAttachment[]>(
        `/api/v1/social-posts/${editTarget.value.id}/media`,
        {
          method: 'PUT',
          body: {
            attachments: selectedMediaIds.value.map((mid, idx) => ({
              media_asset_id: mid,
              sort_order: idx,
              role: idx === 0 ? 'primary' : 'gallery',
            })),
          },
        },
      )
    }

    toast.add({
      title: updated.status === 'pending_review' && editTarget.value.status === 'approved'
        ? 'Draft updated — re-approval required before publish'
        : `Saved draft revision v${updated.current_version}`,
      color: 'success',
    })
    editModalOpen.value = false
    await Promise.all([loadPosts(), loadMetadata()])
  }
  catch (err) {
    toast.add({
      title: 'Could not save edit',
      description: extractErrorMessage(err, 'Failed to update social draft.'),
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
    await request<SocialPostItem>(`/api/v1/social-posts/${post.id}/approve`, { method: 'POST' })
    toast.add({ title: 'Draft approved for publishing', color: 'success' })
    await Promise.all([loadPosts(), loadMetadata()])
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
    await request<SocialPostItem>(`/api/v1/social-posts/${rejectTarget.value.id}/reject`, {
      method: 'POST',
      body: { reason: rejectReason.value.trim() || null },
    })
    toast.add({ title: 'Draft rejected', color: 'neutral' })
    rejectTarget.value = null
    rejectReason.value = ''
    await Promise.all([loadPosts(), loadMetadata()])
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
    await Promise.all([loadPosts(), loadMetadata()])
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
    await request(`/api/v1/social-posts/${post.id}/regenerate`, {
      method: 'POST',
      body: { context_mode: 'optimized', force: true },
    })
    toast.add({
      title: 'Regeneration job queued',
      description: 'New revision will preserve prior revisions cleanly.',
      color: 'success',
    })
    setTimeout(() => void loadPosts(), 1800)
  }
  catch (err) {
    toast.add({
      title: 'Regeneration failed',
      description: extractErrorMessage(err, 'Verify AI configuration and quotas.'),
      color: 'error',
    })
  }
  finally {
    savingActionId.value = null
  }
}

async function openPublishNowModal(post: SocialPostItem) {
  publishTarget.value = post
  publishConfirmChecked.value = false
  paidApiConfirmChecked.value = false
  preflightData.value = null
  publishOpen.value = true
  preflightLoading.value = true
  try {
    preflightData.value = await request<PublishingPreflightResponse>(
      `/api/v1/social-posts/${post.id}/preflight`,
    )
  }
  catch (err) {
    toast.add({
      title: 'Preflight check failed',
      description: extractErrorMessage(err, 'Could not load pre-publish checks.'),
      color: 'error',
    })
  }
  finally {
    preflightLoading.value = false
  }
}

async function refreshPreflightWithPaid() {
  if (!publishTarget.value) {
    return
  }
  preflightLoading.value = true
  try {
    preflightData.value = await request<PublishingPreflightResponse>(
      `/api/v1/social-posts/${publishTarget.value.id}/preflight`,
      { query: { confirm_paid_api: paidApiConfirmChecked.value } },
    )
  }
  finally {
    preflightLoading.value = false
  }
}

async function confirmPublishNow() {
  if (!publishTarget.value || !publishConfirmChecked.value) {
    return
  }
  publishingNow.value = true
  try {
    const job = await request<PublishingJobItem>(
      `/api/v1/social-posts/${publishTarget.value.id}/publish`,
      {
        method: 'POST',
        body: {
          confirm: true,
          confirm_paid_api: paidApiConfirmChecked.value,
        },
      },
    )
    toast.add({
      title: 'Publishing job queued',
      description: `Job #${job.id} queued for external API delivery.`,
      color: 'success',
    })
    publishOpen.value = false
    await Promise.all([loadPosts(), loadMetadata()])
    setTimeout(() => {
      void loadPosts()
      void loadMetadata()
    }, 2500)
  }
  catch (err) {
    toast.add({
      title: 'Publish blocked',
      description: extractErrorMessage(err, 'Resolve preflight checks before publishing.'),
      color: 'error',
    })
  }
  finally {
    publishingNow.value = false
  }
}

function openScheduleModal(post: SocialPostItem) {
  scheduleTarget.value = post
  const tz = getEffectiveTimezone(post)
  scheduleTimezone.value = tz
  scheduleLocalAt.value = formatUtcForLocalInput(post.scheduled_for, tz)
  schedulePaidConfirm.value = false
  scheduleOpen.value = true
}

async function saveSchedule() {
  if (!scheduleTarget.value) {
    return
  }
  const utcIso = localInputToUtcIso(scheduleLocalAt.value, scheduleTimezone.value)
  if (!utcIso) {
    toast.add({ title: 'Enter a valid date and time', color: 'warning' })
    return
  }
  savingSchedule.value = true
  try {
    await request<SocialPostItem>(`/api/v1/social-posts/${scheduleTarget.value.id}/schedule`, {
      method: 'POST',
      body: {
        scheduled_at: utcIso,
        display_timezone: scheduleTimezone.value,
        confirm_paid_api: schedulePaidConfirm.value,
      },
    })
    toast.add({ title: 'Post scheduled successfully', color: 'success' })
    scheduleOpen.value = false
    await Promise.all([loadPosts(), loadMetadata()])
  }
  catch (err) {
    toast.add({
      title: 'Schedule rejected',
      description: extractErrorMessage(err, 'Verify content/keyword/draft approvals and future timestamp.'),
      color: 'error',
    })
  }
  finally {
    savingSchedule.value = false
  }
}

async function cancelSchedule(post: SocialPostItem) {
  savingActionId.value = post.id
  try {
    await request<SocialPostItem>(`/api/v1/social-posts/${post.id}/cancel-schedule`, {
      method: 'POST',
      body: { reason: 'Cancelled by administrator from Publishing Hub' },
    })
    toast.add({ title: 'Schedule cancelled', color: 'neutral' })
    await Promise.all([loadPosts(), loadMetadata()])
  }
  catch (err) {
    toast.add({
      title: 'Cancel schedule failed',
      description: extractErrorMessage(err, 'Could not cancel scheduled publication.'),
      color: 'error',
    })
  }
  finally {
    savingActionId.value = null
  }
}

function openManualModal(post: SocialPostItem) {
  manualTarget.value = post
  manualForm.value = {
    published_url: post.published_url || '',
    external_post_id: post.external_post_id || '',
    notes: '',
  }
  manualOpen.value = true
}

async function submitManualPublished() {
  if (!manualTarget.value || !manualForm.value.published_url.trim()) {
    return
  }
  savingManual.value = true
  try {
    await request<SocialPostItem>(
      `/api/v1/social-posts/${manualTarget.value.id}/mark-published`,
      {
        method: 'POST',
        body: {
          published_url: manualForm.value.published_url.trim(),
          external_post_id: manualForm.value.external_post_id.trim() || null,
          notes: manualForm.value.notes.trim() || null,
        },
      },
    )
    toast.add({ title: 'Manual publication recorded', color: 'success' })
    manualOpen.value = false
    await Promise.all([loadPosts(), loadMetadata()])
  }
  catch (err) {
    toast.add({
      title: 'Record failed',
      description: extractErrorMessage(err, 'Enter a valid http/https live post URL.'),
      color: 'error',
    })
  }
  finally {
    savingManual.value = false
  }
}

async function retryPostJob(post: SocialPostItem) {
  savingActionId.value = post.id
  try {
    const jobs = await request<PublishingJobListResponse>('/api/v1/publishing/jobs', {
      query: { social_post_id: post.id, page: 1, page_size: 5 },
    })
    const targetJob = jobs.items.find((j) => ['failed', 'deferred'].includes(j.status))
    if (!targetJob) {
      toast.add({ title: 'No retryable job found; try Publish Now.', color: 'warning' })
      return
    }
    await request(`/api/v1/publishing/jobs/${targetJob.id}/retry`, { method: 'POST' })
    toast.add({ title: `Queued retry for Job #${targetJob.id}`, color: 'success' })
    await Promise.all([loadPosts(), loadMetadata()])
  }
  catch (err) {
    toast.add({
      title: 'Retry failed',
      description: extractErrorMessage(err, 'Could not retry publishing job.'),
      color: 'error',
    })
  }
  finally {
    savingActionId.value = null
  }
}

async function openReconcileModal(post: SocialPostItem) {
  reconcileTargetPost.value = post
  reconcileTargetJob.value = null
  reconcileForm.value = {
    resolution: 'auto',
    external_post_id: '',
    published_url: '',
    notes: '',
  }
  reconcileOpen.value = true
  try {
    const jobs = await request<PublishingJobListResponse>('/api/v1/publishing/jobs', {
      query: { social_post_id: post.id, page: 1, page_size: 5 },
    })
    reconcileTargetJob.value =
      jobs.items.find((j) => j.status === 'verification_required') || jobs.items[0] || null
  }
  catch {
    // Handled if missing
  }
}

async function submitReconcile() {
  if (!reconcileTargetJob.value) {
    return
  }
  savingReconcile.value = true
  try {
    const res = await request<PublishingJobItem>(
      `/api/v1/publishing/jobs/${reconcileTargetJob.value.id}/reconcile`,
      {
        method: 'POST',
        body: {
          resolution: reconcileForm.value.resolution,
          external_post_id: reconcileForm.value.external_post_id.trim() || null,
          published_url: reconcileForm.value.published_url.trim() || null,
          notes: reconcileForm.value.notes.trim() || null,
        },
      },
    )
    toast.add({
      title: 'Reconciliation complete',
      description: `Job status is now ${res.status}.`,
      color: res.status === 'published' || res.status === 'queued' ? 'success' : 'warning',
    })
    reconcileOpen.value = false
    await Promise.all([loadPosts(), loadMetadata()])
  }
  catch (err) {
    toast.add({
      title: 'Reconciliation failed',
      description: extractErrorMessage(err, 'Verify external platform status manually or select Confirm Published/Missing.'),
      color: 'error',
    })
  }
  finally {
    savingReconcile.value = false
  }
}

async function openLogsModal(post: SocialPostItem) {
  logsTarget.value = post
  logsList.value = []
  logsOpen.value = true
  logsLoading.value = true
  try {
    logsList.value = await request<PublishingLogItem[]>(`/api/v1/social-posts/${post.id}/logs`)
  }
  catch {
    toast.add({ title: 'Could not load execution logs', color: 'error' })
  }
  finally {
    logsLoading.value = false
  }
}

async function copyPostText(post: SocialPostItem) {
  if (!import.meta.client || !post.assembled_content) {
    return
  }
  await navigator.clipboard.writeText(post.assembled_content)
  toast.add({ title: 'Copied final content to clipboard', color: 'success' })
}

function openRevisions(post: SocialPostItem) {
  revisionsTarget.value = post
  revisionsOpen.value = true
}

watch(
  [
    () => uiStore.selectedWebsiteId,
    viewTab,
    platformFilter,
    profileFilter,
    dateFrom,
    dateTo,
    page,
  ],
  () => {
    void loadPosts()
    void loadMetadata()
  },
)

watch([activeSection, historyOutcomeFilter, historyMethodFilter, historyPage], () => {
  if (activeSection.value === 'history') {
    void loadHistory()
  }
})

watch([viewTab, platformFilter, profileFilter, () => uiStore.selectedWebsiteId], () => {
  page.value = 1
})

onMounted(async () => {
  if (typeof route.query.view === 'string') {
    viewTab.value = route.query.view
  }
  const postId = typeof route.query.post_id === 'string' ? Number(route.query.post_id) : 0
  if (Number.isSafeInteger(postId) && postId > 0) {
    try {
      const post = await request<SocialPostItem>(`/api/v1/social-posts/${postId}`)
      if (uiStore.selectedWebsiteId !== null && uiStore.selectedWebsiteId !== post.website_id) {
        uiStore.setWebsiteFilter(post.website_id)
      }
      profileFilter.value = String(post.social_profile_id)
      void openEditModal(post)
    }
    catch (err) {
      toast.add({ title: 'Could not open draft', description: extractErrorMessage(err), color: 'error' })
    }
  }
  await Promise.all([loadMetadata(), loadPosts()])
})
</script>

<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">
          Social Publishing Hub &amp; Drafts
        </h1>
        <p class="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
          Approve drafts, run 11-point preflight verification, schedule or publish immediately via official APIs, record manual posts, and audit permanent history.
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <UButton to="/publishing-calendar" color="neutral" variant="outline" size="xs">
          Publishing Calendar
        </UButton>
        <UButton to="/connected-accounts" color="neutral" variant="outline" size="xs">
          Connected Accounts
        </UButton>
        <UButton color="primary" size="xs" :loading="loading" @click="loadPosts(); loadMetadata()">
          <RotateCcw class="mr-1 h-3.5 w-3.5" />
          Refresh
        </UButton>
      </div>
    </div>

    <!-- Publishing Statistics Strip -->
    <div v-if="pubStats" class="grid grid-cols-2 gap-3 sm:grid-cols-5">
      <div class="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
        <p class="text-[11px] text-slate-500">Approved Ready</p>
        <p class="mt-0.5 text-lg font-semibold text-slate-900 dark:text-slate-100">{{ pubStats.approved_posts }}</p>
      </div>
      <div class="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
        <p class="text-[11px] text-slate-500">Scheduled Queue</p>
        <p class="mt-0.5 text-lg font-semibold text-teal-700 dark:text-teal-300">{{ pubStats.scheduled_posts }}</p>
      </div>
      <div class="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
        <p class="text-[11px] text-slate-500">Published Today / Month</p>
        <p class="mt-0.5 text-lg font-semibold text-emerald-700 dark:text-emerald-300">
          {{ pubStats.published_today }} / {{ pubStats.published_this_month }}
        </p>
      </div>
      <div class="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
        <p class="text-[11px] text-slate-500">Failed / Verify Needed</p>
        <p class="mt-0.5 text-lg font-semibold text-rose-600">
          {{ pubStats.failed_publications }} / {{ pubStats.verification_required }}
        </p>
      </div>
      <div class="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
        <p class="text-[11px] text-slate-500">Accounts Attention</p>
        <p class="mt-0.5 text-lg font-semibold text-amber-600">{{ pubStats.accounts_requiring_attention }}</p>
      </div>
    </div>

    <!-- Primary Section Switcher + Filters -->
    <div class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white p-3 text-xs dark:border-slate-800 dark:bg-slate-900">
      <div class="flex items-center gap-1.5">
        <button
          type="button"
          :class="[
            'rounded-md px-3 py-1.5 font-medium transition-colors',
            activeSection === 'queue'
              ? 'bg-teal-600 text-white'
              : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800',
          ]"
          @click="activeSection = 'queue'"
        >
          Posts &amp; Publishing Queue
        </button>
        <button
          type="button"
          :class="[
            'rounded-md px-3 py-1.5 font-medium transition-colors',
            activeSection === 'history'
              ? 'bg-teal-600 text-white'
              : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800',
          ]"
          @click="activeSection = 'history'"
        >
          Publication History Log
        </button>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <UInput
          v-if="activeSection === 'queue'"
          v-model="searchFilter"
          size="xs"
          placeholder="Search copy or hashtag..."
          class="w-44"
          @keyup.enter="page = 1; loadPosts()"
        />
        <select v-model="platformFilter" class="h-8 rounded-md border border-slate-200 bg-white px-2 dark:border-slate-700 dark:bg-slate-900">
          <option value="all">All Platforms</option>
          <option v-for="plat in platforms" :key="plat.id" :value="String(plat.id)">
            {{ plat.display_name }}
          </option>
        </select>
        <select v-model="profileFilter" class="h-8 rounded-md border border-slate-200 bg-white px-2 dark:border-slate-700 dark:bg-slate-900">
          <option value="all">All Social Profiles</option>
          <option v-for="prof in visibleProfiles" :key="prof.id" :value="String(prof.id)">
            {{ prof.website_name }} · {{ prof.profile_name }}
          </option>
        </select>
        <input v-model="dateFrom" type="date" class="h-8 rounded-md border border-slate-200 bg-white px-2 text-xs dark:border-slate-700 dark:bg-slate-900" title="From date">
        <input v-model="dateTo" type="date" class="h-8 rounded-md border border-slate-200 bg-white px-2 text-xs dark:border-slate-700 dark:bg-slate-900" title="To date">
      </div>
    </div>

    <!-- QUEUE SECTION (9 Views) -->
    <template v-if="activeSection === 'queue'">
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="tab in VIEW_TABS"
          :key="tab.key"
          type="button"
          :class="[
            'rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors',
            viewTab === tab.key
              ? 'border-teal-600 bg-teal-50 text-teal-800 dark:bg-teal-950/60 dark:text-teal-200'
              : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300',
          ]"
          @click="viewTab = tab.key"
        >
          {{ tab.label }}
        </button>
      </div>

      <AppErrorState
        v-if="errorMessage && !loading"
        title="Social posts unavailable"
        :message="errorMessage"
        retryable
        @retry="loadPosts()"
      />

      <div v-else-if="loading" class="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <USkeleton v-for="idx in 4" :key="idx" class="h-52 w-full" />
      </div>

      <AppEmptyState
        v-else-if="posts.length === 0"
        title="No social posts in this view"
        description="Approve discovered content & keywords, generate drafts in Content Library, or switch views."
      >
        <template #actions>
          <UButton to="/content-approval" color="primary" size="xs">Content Approval Queue</UButton>
        </template>
      </AppEmptyState>

      <div v-else class="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <article
          v-for="post in posts"
          :key="post.id"
          class="flex flex-col justify-between rounded-lg border border-slate-200 bg-white p-4 text-xs shadow-xs dark:border-slate-800 dark:bg-slate-900"
        >
          <div class="space-y-3">
            <div class="flex flex-wrap items-start justify-between gap-2">
              <div>
                <div class="flex flex-wrap items-center gap-1.5">
                  <UBadge :color="getDraftStatusMeta(post.status).color" variant="subtle" size="xs">
                    Draft: {{ getDraftStatusMeta(post.status).label }}
                  </UBadge>
                  <UBadge :color="getPublishingStatusMeta(post.publishing_status).color" variant="soft" size="xs">
                    {{ getPublishingStatusMeta(post.publishing_status).label }}
                  </UBadge>
                  <UBadge color="neutral" variant="outline" size="xs">
                    {{ post.platform_display_name || post.platform_key }} · {{ post.publishing_method === 'api' ? 'API' : 'Manual' }}
                  </UBadge>
                  <span class="font-semibold text-slate-900 dark:text-slate-100">
                    {{ post.social_profile_name }}
                  </span>
                  <span class="font-mono text-[10px] text-slate-400">v{{ post.current_version }}</span>
                </div>
                <p class="mt-1 text-[11px] text-slate-500">
                  Website: <strong>{{ post.website_name }}</strong>
                  <template v-if="post.source_title">
                    · Article:
                    <NuxtLink v-if="post.website_content_id" :to="`/content-library/${post.website_content_id}`" class="text-teal-600 hover:underline dark:text-teal-400">
                      {{ post.source_title }}
                    </NuxtLink>
                  </template>
                  <template v-if="post.focus_keyphrase">
                    · Keyword: <span class="font-medium text-slate-700 dark:text-slate-300">{{ post.focus_keyphrase }}</span>
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
                {{ post.character_count }}/{{ post.character_limit ?? '∞' }}
              </span>
            </div>

            <div
              v-if="post.featured_image_url"
              class="flex items-center justify-between gap-2 rounded bg-slate-50 p-2 dark:bg-slate-950/60"
            >
              <div class="flex min-w-0 items-center gap-2">
                <img :src="post.featured_image_url" alt="Attached media" class="h-10 w-10 rounded object-cover">
                <span class="truncate text-[11px] text-slate-500">
                  {{ post.media_count || 1 }} Media Attachment(s)
                </span>
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

            <pre class="max-h-44 overflow-y-auto whitespace-pre-wrap rounded-md bg-slate-50 p-3 font-sans text-xs text-slate-800 dark:bg-slate-950/60 dark:text-slate-200">{{ post.assembled_content }}</pre>

            <!-- Scheduling / Outcome / Error Metadata -->
            <div class="flex flex-wrap items-center gap-3 text-[11px] text-slate-500">
              <span v-if="post.scheduled_for" class="font-medium text-teal-700 dark:text-teal-300">
                Scheduled: {{ formatDateTime(post.scheduled_for, getEffectiveTimezone(post)) }} ({{ getEffectiveTimezone(post) }})
              </span>
              <span v-if="post.published_at" class="font-medium text-emerald-700 dark:text-emerald-300">
                Published: {{ formatDateTime(post.published_at, getEffectiveTimezone(post)) }}
              </span>
              <a
                v-if="post.published_url"
                :href="post.published_url"
                target="_blank"
                rel="noopener noreferrer"
                class="inline-flex items-center gap-1 text-teal-600 hover:underline dark:text-teal-400"
              >
                Live Post URL <ExternalLink class="h-3 w-3" />
              </a>
              <span v-if="post.target_url_with_utm" class="truncate font-mono text-[10px] text-slate-400" :title="post.target_url_with_utm">
                UTM Active
              </span>
            </div>

            <div
              v-if="post.last_publish_error"
              class="flex items-start gap-2 rounded border border-rose-200 bg-rose-50 px-2.5 py-2 text-[11px] text-rose-800 dark:border-rose-900/50 dark:bg-rose-950/30 dark:text-rose-200"
            >
              <AlertTriangle class="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{{ post.last_publish_error }}</span>
            </div>

            <div v-if="post.validation_warnings.length > 0" class="space-y-0.5 text-[11px] text-amber-700 dark:text-amber-300">
              <p v-for="warn in post.validation_warnings" :key="warn">• {{ warn }}</p>
            </div>
          </div>

          <!-- Action Footer -->
          <div class="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3 dark:border-slate-800">
            <div class="flex flex-wrap gap-1.5">
              <UButton v-if="post.assembled_content" color="neutral" variant="outline" size="xs" @click="copyPostText(post)">
                <Copy class="mr-1 h-3 w-3" />
                Copy
              </UButton>
              <UButton color="neutral" variant="outline" size="xs" @click="openEditModal(post)">
                Edit / Media / UTM
              </UButton>
              <UButton color="neutral" variant="ghost" size="xs" title="Revision History" @click="openRevisions(post)">
                <History class="h-3.5 w-3.5" />
              </UButton>
              <UButton color="neutral" variant="ghost" size="xs" title="Publishing Execution Logs" @click="openLogsModal(post)">
                <ScrollText class="h-3.5 w-3.5" />
              </UButton>
            </div>

            <div class="flex flex-wrap gap-1">
              <!-- Approval Workflow -->
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
                v-if="post.status === 'pending_review'"
                color="warning"
                variant="subtle"
                size="xs"
                @click="rejectTarget = post"
              >
                <XCircle class="mr-1 h-3 w-3" />
                Reject
              </UButton>

              <!-- Publishing Actions for Approved Posts -->
              <template v-if="post.status === 'approved' && !['published', 'manually_published'].includes(post.publishing_status)">
                <UButton
                  v-if="post.publishing_method === 'api'"
                  color="primary"
                  size="xs"
                  @click="openPublishNowModal(post)"
                >
                  <Send class="mr-1 h-3 w-3" />
                  Publish Now
                </UButton>
                <UButton color="info" variant="subtle" size="xs" @click="openScheduleModal(post)">
                  <CalendarClock class="mr-1 h-3 w-3" />
                  {{ post.publishing_status === 'scheduled' ? 'Reschedule' : 'Schedule' }}
                </UButton>
                <UButton
                  v-if="post.publishing_status === 'scheduled'"
                  color="warning"
                  variant="ghost"
                  size="xs"
                  @click="cancelSchedule(post)"
                >
                  Cancel Sched
                </UButton>
                <UButton color="neutral" variant="outline" size="xs" @click="openManualModal(post)">
                  <Wrench class="mr-1 h-3 w-3" />
                  Manual Publish
                </UButton>
              </template>

              <!-- Failure / Verification Actions -->
              <UButton
                v-if="post.publishing_status === 'verification_required'"
                color="warning"
                size="xs"
                @click="openReconcileModal(post)"
              >
                <ShieldAlert class="mr-1 h-3 w-3" />
                Verify / Reconcile
              </UButton>
              <UButton
                v-if="post.publishing_status === 'failed'"
                color="error"
                variant="subtle"
                size="xs"
                :loading="savingActionId === post.id"
                @click="retryPostJob(post)"
              >
                <RotateCcw class="mr-1 h-3 w-3" />
                Retry
              </UButton>

              <UButton v-if="post.website_content_id" color="primary" variant="ghost" size="xs" title="Regenerate Draft" @click="regeneratePost(post)">
                <RotateCcw class="h-3.5 w-3.5" />
              </UButton>
              <UButton v-if="post.status !== 'archived'" color="neutral" variant="ghost" size="xs" title="Archive" @click="archivePost(post)">
                <Archive class="h-3.5 w-3.5" />
              </UButton>
            </div>
          </div>
        </article>
      </div>

      <div v-if="totalPages > 1" class="flex items-center justify-between text-xs text-slate-500">
        <span>Page {{ page }} of {{ totalPages }} ({{ totalItems }} posts)</span>
        <div class="flex gap-2">
          <UButton color="neutral" variant="outline" size="xs" :disabled="page <= 1" @click="page--">Previous</UButton>
          <UButton color="neutral" variant="outline" size="xs" :disabled="page >= totalPages" @click="page++">Next</UButton>
        </div>
      </div>
    </template>

    <!-- PUBLICATION HISTORY SECTION -->
    <template v-else>
      <div class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white p-3 text-xs dark:border-slate-800 dark:bg-slate-900">
        <div class="flex flex-wrap gap-2">
          <select v-model="historyOutcomeFilter" class="h-8 rounded border border-slate-200 bg-white px-2 dark:border-slate-700 dark:bg-slate-900">
            <option value="all">All Outcomes</option>
            <option value="published">Published (API)</option>
            <option value="manually_published">Manually Published</option>
            <option value="failed">Failed</option>
          </select>
          <select v-model="historyMethodFilter" class="h-8 rounded border border-slate-200 bg-white px-2 dark:border-slate-700 dark:bg-slate-900">
            <option value="all">API &amp; Manual</option>
            <option value="api">API Only</option>
            <option value="manual">Manual Only</option>
          </select>
        </div>
        <UButton color="primary" variant="outline" size="xs" @click="exportHistoryCsv">
          <Download class="mr-1 h-3.5 w-3.5" />
          Export CSV
        </UButton>
      </div>

      <div class="overflow-x-auto rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
          <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60">
            <tr>
              <th class="px-4 py-2.5 font-medium">Website / Profile</th>
              <th class="px-4 py-2.5 font-medium">Platform &amp; Method</th>
              <th class="px-4 py-2.5 font-medium">Outcome</th>
              <th class="px-4 py-2.5 font-medium">Source Content</th>
              <th class="px-4 py-2.5 font-medium">Published Timestamp</th>
              <th class="px-4 py-2.5 font-medium">Live Post URL</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 dark:divide-slate-800">
            <tr v-if="historyLoading">
              <td colspan="6" class="px-4 py-6 text-center text-slate-400">Loading history...</td>
            </tr>
            <tr v-else-if="historyItems.length === 0">
              <td colspan="6" class="px-4 py-6 text-center text-slate-400">No publication records match the active filter.</td>
            </tr>
            <tr v-for="rec in historyItems" :key="rec.id">
              <td class="px-4 py-2.5">
                <p class="font-medium text-slate-900 dark:text-slate-100">{{ rec.website_name }}</p>
                <p class="text-[11px] text-slate-500">{{ rec.profile_name }}</p>
              </td>
              <td class="px-4 py-2.5">
                <UBadge color="neutral" variant="outline" size="xs">
                  {{ rec.platform_display_name }} · {{ rec.publishing_method }}
                </UBadge>
              </td>
              <td class="px-4 py-2.5">
                <UBadge :color="getPublishingStatusMeta(rec.outcome).color" variant="subtle" size="xs">
                  {{ rec.outcome }} ({{ rec.verification_status }})
                </UBadge>
                <p v-if="rec.error_summary" class="mt-0.5 text-[10px] text-rose-600">{{ rec.error_summary }}</p>
              </td>
              <td class="px-4 py-2.5">
                {{ rec.source_title || '-' }}
                <span v-if="rec.approved_version_number" class="font-mono text-[10px] text-slate-400">v{{ rec.approved_version_number }}</span>
              </td>
              <td class="px-4 py-2.5 whitespace-nowrap font-mono text-[11px] text-slate-500">
                {{ formatDateTime(rec.published_at || rec.created_at) }}
              </td>
              <td class="px-4 py-2.5">
                <a
                  v-if="rec.published_url"
                  :href="rec.published_url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="inline-flex items-center gap-1 text-teal-600 hover:underline dark:text-teal-400"
                >
                  Open Post <ExternalLink class="h-3 w-3" />
                </a>
                <span v-else class="text-slate-400">-</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="historyTotalPages > 1" class="flex items-center justify-between text-xs text-slate-500">
        <span>Page {{ historyPage }} of {{ historyTotalPages }} ({{ historyTotal }} records)</span>
        <div class="flex gap-2">
          <UButton color="neutral" variant="outline" size="xs" :disabled="historyPage <= 1" @click="historyPage--">Previous</UButton>
          <UButton color="neutral" variant="outline" size="xs" :disabled="historyPage >= historyTotalPages" @click="historyPage++">Next</UButton>
        </div>
      </div>
    </template>

    <!-- Edit Modal (Caption, Alt Hooks, UTM Builder, Media Picker) -->
    <UModal v-model:open="editModalOpen" :title="`Edit ${editTarget?.platform_display_name || ''} Post`">
      <template #body>
        <form class="max-h-[78vh] space-y-3 overflow-y-auto pr-1 text-xs" @submit.prevent="saveEditedDraft">
          <div
            v-if="editTarget?.status === 'approved'"
            class="rounded border border-amber-200 bg-amber-50 p-2 text-[11px] text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200"
          >
            Material edits to an approved draft invalidate approval and cancel pending schedules until re-approved.
          </div>
          <div v-if="editTarget?.platform_key === 'pinterest' || editTarget?.platform_key === 'google_business_profile'">
            <label class="mb-1 block font-medium">Post / Pin Title</label>
            <UInput v-model="editForm.title" size="sm" />
          </div>
          <div>
            <div class="mb-1 flex items-center justify-between">
              <label class="font-medium">Caption *</label>
              <span :class="['font-mono text-[11px]', editTarget?.character_limit && editedCharCount > editTarget.character_limit ? 'font-semibold text-rose-600' : 'text-slate-500']">
                Assembled: {{ editedCharCount }}/{{ editTarget?.character_limit ?? '∞' }}
              </span>
            </div>
            <UTextarea v-model="editForm.caption" :rows="4" size="sm" required />
          </div>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label class="mb-1 block font-medium">Call To Action (CTA)</label>
              <UInput v-model="editForm.cta_text" size="sm" />
            </div>
            <div>
              <label class="mb-1 block font-medium">Hashtags (CSV)</label>
              <UInput v-model="editForm.hashtags_text" size="sm" />
            </div>
          </div>
          <div>
            <label class="mb-1 block font-medium">Alternative Captions / Hooks (one per line)</label>
            <UTextarea v-model="editForm.alternative_captions_text" :rows="2" size="sm" placeholder="Optional A/B backup hooks..." />
          </div>

          <!-- UTM Parameter Builder -->
          <div v-if="editTarget?.source_url" class="space-y-2 rounded border border-slate-200 bg-slate-50/70 p-2.5 dark:border-slate-700 dark:bg-slate-950/60">
            <span class="font-semibold">UTM Link Builder</span>
            <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <UInput v-model="editForm.utm_source" size="xs" placeholder="utm_source" />
              <UInput v-model="editForm.utm_medium" size="xs" placeholder="utm_medium" />
              <UInput v-model="editForm.utm_campaign" size="xs" placeholder="utm_campaign" />
              <UInput v-model="editForm.utm_content" size="xs" placeholder="utm_content" />
            </div>
            <p class="truncate font-mono text-[10px] text-teal-700 dark:text-teal-300">
              Tracked URL: {{ editUtmPreview }}
            </p>
          </div>

          <!-- Media Picker -->
          <div v-if="websiteAssets.length > 0" class="space-y-2 rounded border border-slate-200 p-2.5 dark:border-slate-700">
            <div class="flex items-center justify-between">
              <span class="inline-flex items-center gap-1 font-semibold">
                <ImagePlus class="h-3.5 w-3.5 text-teal-600" />
                Attach Media Assets ({{ selectedMediaIds.length }} selected)
              </span>
            </div>
            <div class="grid max-h-36 grid-cols-3 gap-2 overflow-y-auto sm:grid-cols-4">
              <button
                v-for="asset in websiteAssets"
                :key="asset.id"
                type="button"
                :class="[
                  'flex flex-col items-center rounded border p-1 text-left transition-colors',
                  selectedMediaIds.includes(asset.id)
                    ? 'border-teal-600 bg-teal-50 dark:bg-teal-950/60'
                    : 'border-slate-200 hover:border-slate-400 dark:border-slate-700',
                ]"
                @click="toggleMediaAsset(asset.id)"
              >
                <img :src="`/api/v1/media/${asset.id}/file`" :alt="asset.file_name" class="h-12 w-full rounded object-cover">
                <span class="mt-1 w-full truncate text-[10px]">{{ asset.file_name }}</span>
              </button>
            </div>
          </div>

          <div>
            <label class="mb-1 block font-medium">Final Output Preview</label>
            <pre class="max-h-28 overflow-y-auto whitespace-pre-wrap rounded bg-slate-50 p-2 font-sans text-xs dark:bg-slate-950/60">{{ editedPreviewAssembled }}</pre>
          </div>

          <div class="flex justify-end gap-2 pt-2">
            <UButton type="button" color="neutral" variant="outline" size="xs" @click="editModalOpen = false">Cancel</UButton>
            <UButton type="submit" color="primary" size="xs" :loading="savingEdit">
              <Save class="mr-1 h-3.5 w-3.5" />
              Save Changes
            </UButton>
          </div>
        </form>
      </template>
    </UModal>

    <!-- Preflight & Publish Now Confirm Modal -->
    <UModal v-model:open="publishOpen" :title="`Preflight & Publish Now — ${publishTarget?.platform_display_name || ''}`">
      <template #body>
        <div class="space-y-3 text-xs">
          <div v-if="preflightLoading" class="py-4 text-center text-slate-400">Running 11-point preflight checks...</div>
          <template v-else-if="preflightData">
            <div class="rounded bg-slate-50 p-2.5 dark:bg-slate-950/60">
              <p><strong>Destination:</strong> {{ preflightData.destination_name }} <span v-if="preflightData.destination_target">({{ preflightData.destination_target }})</span></p>
              <p class="mt-0.5 text-[11px] text-slate-500">Chars: {{ preflightData.character_count }}/{{ preflightData.character_limit ?? '∞' }}</p>
            </div>

            <div class="max-h-56 space-y-1.5 overflow-y-auto">
              <div
                v-for="chk in preflightData.checks"
                :key="chk.name"
                :class="[
                  'flex items-start justify-between gap-2 rounded border px-2.5 py-1.5',
                  chk.passed
                    ? 'border-emerald-200 bg-emerald-50/40 text-emerald-900 dark:border-emerald-900/50 dark:bg-emerald-950/20 dark:text-emerald-200'
                    : 'border-rose-200 bg-rose-50/60 text-rose-900 dark:border-rose-900/50 dark:bg-rose-950/20 dark:text-rose-200',
                ]"
              >
                <span>{{ chk.detail }}</span>
                <UBadge :color="chk.passed ? 'success' : 'error'" variant="soft" size="xs">
                  {{ chk.passed ? 'Pass' : 'Fail' }}
                </UBadge>
              </div>
            </div>

            <label v-if="preflightData.platform_key === 'twitter'" class="flex cursor-pointer items-center gap-2 rounded border border-amber-200 bg-amber-50 p-2 text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200">
              <input v-model="paidApiConfirmChecked" type="checkbox" @change="refreshPreflightWithPaid">
              <span>Confirm paid pay-per-use X API usage for this request</span>
            </label>

            <label class="flex cursor-pointer items-center gap-2 rounded border border-slate-200 p-2.5 font-medium dark:border-slate-700">
              <input v-model="publishConfirmChecked" type="checkbox" :disabled="!preflightData.ready">
              <span>Confirm immediate external publication to {{ preflightData.destination_name }}</span>
            </label>

            <div class="flex justify-end gap-2 pt-2">
              <UButton color="neutral" variant="outline" size="xs" @click="publishOpen = false">Cancel</UButton>
              <UButton
                color="primary"
                size="xs"
                :disabled="!preflightData.ready || !publishConfirmChecked"
                :loading="publishingNow"
                @click="confirmPublishNow"
              >
                <Send class="mr-1 h-3.5 w-3.5" />
                Publish Externally Now
              </UButton>
            </div>
          </template>
        </div>
      </template>
    </UModal>

    <!-- Schedule / Reschedule Modal -->
    <UModal v-model:open="scheduleOpen" :title="`Schedule Post — ${scheduleTarget?.platform_display_name || ''}`">
      <template #body>
        <form class="space-y-3 text-xs" @submit.prevent="saveSchedule">
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label class="mb-1 block font-medium">Display Timezone</label>
              <select v-model="scheduleTimezone" class="h-9 w-full rounded border border-slate-200 bg-white px-2 text-xs dark:border-slate-700 dark:bg-slate-900">
                <option v-for="tz in PUBLISHING_TZ_OPTIONS" :key="tz.value" :value="tz.value">{{ tz.label }}</option>
              </select>
            </div>
            <div>
              <label class="mb-1 block font-medium">Publish Date &amp; Time ({{ scheduleTimezone }})</label>
              <input
                v-model="scheduleLocalAt"
                type="datetime-local"
                required
                class="h-9 w-full rounded border border-slate-200 bg-white px-2 text-xs dark:border-slate-700 dark:bg-slate-900"
              >
            </div>
          </div>
          <p v-if="scheduleTarget && profileForPost(scheduleTarget)?.preferred_publishing_days.length" class="text-[11px] text-slate-500">
            Preferred schedule hints: {{ profileForPost(scheduleTarget)?.preferred_publishing_days.join(', ') }} at
            {{ profileForPost(scheduleTarget)?.preferred_publishing_times.join(', ') || 'any time' }}
          </p>
          <div class="flex justify-end gap-2 pt-2">
            <UButton type="button" color="neutral" variant="outline" size="xs" @click="scheduleOpen = false">Cancel</UButton>
            <UButton type="submit" color="primary" size="xs" :loading="savingSchedule">Save Schedule</UButton>
          </div>
        </form>
      </template>
    </UModal>

    <!-- Manual Publishing Checklist & Mark Published Modal -->
    <UModal v-model:open="manualOpen" :title="`Manual Publishing — ${manualTarget?.platform_display_name || ''}`">
      <template #body>
        <form v-if="manualTarget" class="space-y-3 text-xs" @submit.prevent="submitManualPublished">
          <div class="space-y-1.5 rounded border border-slate-200 bg-slate-50 p-2.5 dark:border-slate-700 dark:bg-slate-950/60">
            <p class="font-semibold inline-flex items-center gap-1">
              <ClipboardCheck class="h-3.5 w-3.5 text-teal-600" />
              Manual Workflow Checklist
            </p>
            <ol class="list-inside list-decimal space-y-1 text-[11px] text-slate-600 dark:text-slate-300">
              <li v-for="step in buildManualPublishChecklist(manualTarget.platform_key)" :key="step">{{ step }}</li>
            </ol>
            <div class="flex flex-wrap gap-2 pt-1">
              <UButton type="button" color="neutral" variant="outline" size="xs" @click="copyPostText(manualTarget)">
                <Copy class="mr-1 h-3 w-3" />
                Copy Final Content
              </UButton>
              <a
                v-if="manualTarget.featured_image_url"
                :href="manualTarget.featured_image_url"
                download
                target="_blank"
                class="inline-flex items-center gap-1 rounded border border-slate-200 bg-white px-2 py-1 text-[11px] dark:border-slate-700 dark:bg-slate-900"
              >
                <Download class="h-3 w-3" />
                Download Media
              </a>
            </div>
          </div>

          <div>
            <label class="mb-1 block font-medium">Live Published Post URL *</label>
            <UInput v-model="manualForm.published_url" size="sm" required placeholder="https://facebook.com/.../posts/12345" />
          </div>
          <div>
            <label class="mb-1 block font-medium">Optional External Post ID</label>
            <UInput v-model="manualForm.external_post_id" size="sm" placeholder="Optional platform post ID" />
          </div>
          <div>
            <label class="mb-1 block font-medium">Notes</label>
            <UTextarea v-model="manualForm.notes" :rows="2" size="sm" />
          </div>
          <div class="flex justify-end gap-2 pt-2">
            <UButton type="button" color="neutral" variant="outline" size="xs" @click="manualOpen = false">Cancel</UButton>
            <UButton type="submit" color="success" size="xs" :loading="savingManual">Mark as Published</UButton>
          </div>
        </form>
      </template>
    </UModal>

    <!-- Reconcile Ambiguous Timeout Outcome Modal -->
    <UModal v-model:open="reconcileOpen" title="Reconcile Uncertain Publishing Outcome">
      <template #body>
        <form class="space-y-3 text-xs" @submit.prevent="submitReconcile">
          <p class="rounded border border-amber-200 bg-amber-50 p-2 text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200">
            A network interruption or worker timeout occurred after submission. ContentHub AI intentionally paused automatic retries to prevent duplicate social posts.
          </p>
          <div>
            <label class="mb-1 block font-medium">Resolution Action</label>
            <select v-model="reconcileForm.resolution" class="h-9 w-full rounded border border-slate-200 bg-white px-2 text-xs dark:border-slate-700 dark:bg-slate-900">
              <option value="auto">Auto-Verify Recent Feed via Platform API</option>
              <option value="confirm_published">Confirm Already Published Manually</option>
              <option value="confirm_missing">Confirm Missing on Platform &amp; Re-Queue Safe Retry</option>
            </select>
          </div>
          <div v-if="reconcileForm.resolution === 'confirm_published'" class="space-y-2">
            <UInput v-model="reconcileForm.published_url" size="sm" placeholder="Live Published URL (https://...)" />
            <UInput v-model="reconcileForm.external_post_id" size="sm" placeholder="External Post ID (optional)" />
          </div>
          <UTextarea v-model="reconcileForm.notes" :rows="2" size="sm" placeholder="Operator verification notes..." />
          <div class="flex justify-end gap-2 pt-2">
            <UButton type="button" color="neutral" variant="outline" size="xs" @click="reconcileOpen = false">Cancel</UButton>
            <UButton type="submit" color="primary" size="xs" :loading="savingReconcile" :disabled="!reconcileTargetJob">
              Apply Reconciliation
            </UButton>
          </div>
        </form>
      </template>
    </UModal>

    <!-- Execution Logs Modal -->
    <UModal v-model:open="logsOpen" :title="`Publishing Execution Logs — Post #${logsTarget?.id || ''}`">
      <template #body>
        <div class="max-h-96 space-y-2 overflow-y-auto text-xs">
          <div v-if="logsLoading" class="py-4 text-center text-slate-400">Loading logs...</div>
          <div v-else-if="logsList.length === 0" class="py-4 text-center text-slate-400">No execution logs yet.</div>
          <div
            v-for="log in logsList"
            :key="log.id"
            class="rounded border border-slate-200 p-2.5 dark:border-slate-700"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="font-semibold">{{ log.action }} · Attempt #{{ log.attempt_number }}</span>
              <UBadge :color="log.outcome === 'succeeded' || log.outcome === 'manual_recorded' ? 'success' : log.outcome === 'failed' ? 'error' : 'warning'" variant="soft" size="xs">
                {{ log.outcome }}
              </UBadge>
            </div>
            <p class="mt-1 font-mono text-[10px] text-slate-500">
              {{ formatDateTime(log.created_at) }} <span v-if="log.http_status">· HTTP {{ log.http_status }}</span>
            </p>
            <p v-if="log.error_message" class="mt-1 text-rose-600">{{ log.error_message }}</p>
            <a v-if="log.published_url" :href="log.published_url" target="_blank" class="mt-1 inline-block text-teal-600 hover:underline">
              {{ log.published_url }}
            </a>
          </div>
        </div>
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
          <UTextarea v-model="rejectReason" :rows="3" size="sm" placeholder="Explain why this draft needs edits or regeneration..." />
          <div class="flex justify-end gap-2">
            <UButton type="button" color="neutral" variant="outline" size="xs" @click="rejectTarget = null">Cancel</UButton>
            <UButton type="submit" color="warning" size="xs">Confirm Reject</UButton>
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
