import { isApprovalEligibleContentType } from '~/utils/format'

export const CONTEXT_MODE_OPTIONS = [
  {
    value: 'optimized',
    label: 'Optimized Context (Default)',
    description: 'Compact Python digest (~3-4k chars): recommended for Free-First Gemini quotas.',
  },
  {
    value: 'metadata_only',
    label: 'Metadata Only',
    description: 'Title, URL, meta description, and keywords only (lowest token usage).',
  },
  {
    value: 'full',
    label: 'Full Clean Markdown',
    description: 'Sanitized article text up to safety cap (highest input token usage).',
  },
] as const

export const PROMPT_TASK_TYPE_OPTIONS = [
  { value: 'multi_platform_social', label: 'Multi-Platform Social Batch' },
  { value: 'knowledge_analysis', label: 'Website Knowledge Synthesis' },
  { value: 'facebook_caption', label: 'Facebook Caption' },
  { value: 'instagram_caption', label: 'Instagram Caption' },
  { value: 'twitter_post', label: 'X / Twitter Post' },
  { value: 'threads_post', label: 'Threads Post' },
  { value: 'linkedin_post', label: 'LinkedIn Post' },
  { value: 'google_business_update', label: 'Google Business Update' },
  { value: 'pinterest_description', label: 'Pinterest Description' },
  { value: 'content_summarization', label: 'Content Summarization' },
  { value: 'custom_prompt', label: 'Custom Prompt' },
] as const

export function getDraftStatusMeta(status: string): {
  label: string
  color: 'success' | 'warning' | 'error' | 'neutral' | 'info' | 'primary'
} {
  switch (status) {
    case 'approved':
      return { label: 'Approved', color: 'success' }
    case 'pending_review':
      return { label: 'Pending Review', color: 'info' }
    case 'rejected':
      return { label: 'Rejected', color: 'warning' }
    case 'generation_failed':
      return { label: 'Generation Failed', color: 'error' }
    case 'archived':
      return { label: 'Archived', color: 'neutral' }
    default:
      return { label: status, color: 'neutral' }
  }
}

export function getApprovalStatusMeta(status: string | null | undefined): {
  label: string
  color: 'success' | 'warning' | 'error' | 'neutral' | 'info' | 'primary'
} {
  switch (status) {
    case 'approved':
      return { label: 'Approved', color: 'success' }
    case 'pending_review':
      return { label: 'Pending Review', color: 'warning' }
    case 'needs_rereview':
      return { label: 'Needs Re-review', color: 'error' }
    case 'awaiting_extraction':
      return { label: 'Awaiting Extraction', color: 'info' }
    case 'rejected':
      return { label: 'Rejected', color: 'neutral' }
    default:
      return { label: status || 'Unreviewed', color: 'neutral' }
  }
}

export function getJobStatusMeta(status: string): {
  label: string
  color: 'success' | 'warning' | 'error' | 'neutral' | 'info' | 'primary'
} {
  switch (status) {
    case 'completed':
      return { label: 'Completed', color: 'success' }
    case 'partially_completed':
      return { label: 'Partial', color: 'warning' }
    case 'deferred':
      return { label: 'Deferred', color: 'warning' }
    case 'processing':
      return { label: 'Processing', color: 'primary' }
    case 'queued':
      return { label: 'Queued', color: 'info' }
    case 'failed':
      return { label: 'Failed', color: 'error' }
    case 'cancelled':
      return { label: 'Cancelled', color: 'neutral' }
    default:
      return { label: status, color: 'neutral' }
  }
}

export function getQuotaStatusMeta(status: string): {
  label: string
  color: 'success' | 'warning' | 'error' | 'neutral' | 'info'
} {
  switch (status) {
    case 'ok':
      return { label: 'Within Quota', color: 'success' }
    case 'rpm_throttled':
      return { label: 'RPM Paused', color: 'warning' }
    case 'daily_requests_exhausted':
      return { label: 'Daily Requests Exhausted', color: 'error' }
    case 'daily_tokens_exhausted':
      return { label: 'Daily Tokens Exhausted', color: 'error' }
    case 'disabled':
      return { label: 'Generation Disabled', color: 'neutral' }
    default:
      return { label: 'Not Configured', color: 'neutral' }
  }
}

/**
 * Mirrors backend `measure_platform_character_count`: counts X/Twitter URLs as 23 chars.
 */
export function estimateAssembledLength(
  text: string,
  platformKey: string | null | undefined,
): number {
  if (!text) {
    return 0
  }
  if (platformKey === 'twitter') {
    const normalized = text.replace(/https?:\/\/\S+/g, 'x'.repeat(23))
    return normalized.length
  }
  return text.length
}

export function buildAssembledSocialDraft(params: {
  caption: string
  ctaText: string | null
  sourceUrl: string | null
  hashtags: string[]
}): string {
  const cleanCaption = params.caption.trim()
  const parts: string[] = []
  if (cleanCaption) {
    parts.push(cleanCaption)
  }
  const cta = (params.ctaText || '').trim()
  if (cta && !cleanCaption.toLowerCase().includes(cta.toLowerCase())) {
    parts.push(cta)
  }
  const src = (params.sourceUrl || '').trim()
  if (src && !cleanCaption.includes(src)) {
    parts.push(src)
  }
  const tags = params.hashtags.map((h) => h.trim()).filter(Boolean)
  if (tags.length > 0) {
    const tagLine = tags.map((h) => (h.startsWith('#') ? h : `#${h}`)).join(' ')
    if (!cleanCaption.toLowerCase().includes(tagLine.toLowerCase())) {
      parts.push(tagLine)
    }
  }
  return parts.join('\n\n').trim()
}

export function isContentEligibleForManualGeneration(content: {
  extraction_status: string
  content_type: string
  is_excluded: boolean
}): boolean {
  if (content.extraction_status !== 'extracted' || content.is_excluded) {
    return false
  }
  return isApprovalEligibleContentType(content.content_type)
}

// Phase 4 — Social Publishing, Connections, Schedules & UTM Helpers
import { DateTime } from 'luxon'

export const PUBLISHING_TZ_OPTIONS = [
  { label: 'Asia/Manila (UTC+8)', value: 'Asia/Manila' },
  { label: 'UTC (UTC+0)', value: 'UTC' },
  { label: 'Asia/Singapore (UTC+8)', value: 'Asia/Singapore' },
  { label: 'Asia/Tokyo (UTC+9)', value: 'Asia/Tokyo' },
  { label: 'America/New_York', value: 'America/New_York' },
  { label: 'America/Los_Angeles', value: 'America/Los_Angeles' },
  { label: 'Europe/London', value: 'Europe/London' },
] as const

export const WEEKDAY_OPTIONS = [
  { value: 'mon', label: 'Mon' },
  { value: 'tue', label: 'Tue' },
  { value: 'wed', label: 'Wed' },
  { value: 'thu', label: 'Thu' },
  { value: 'fri', label: 'Fri' },
  { value: 'sat', label: 'Sat' },
  { value: 'sun', label: 'Sun' },
] as const

export function getPublishingStatusMeta(status: string | null | undefined): {
  label: string
  color: 'success' | 'warning' | 'error' | 'neutral' | 'info' | 'primary'
} {
  switch (status) {
    case 'published':
      return { label: 'Published', color: 'success' }
    case 'manually_published':
      return { label: 'Published (Manual)', color: 'info' }
    case 'scheduled':
      return { label: 'Scheduled', color: 'primary' }
    case 'manual_reminder':
      return { label: 'Manual Reminder', color: 'info' }
    case 'queued':
      return { label: 'Queued', color: 'info' }
    case 'publishing':
      return { label: 'Publishing', color: 'primary' }
    case 'deferred':
      return { label: 'Deferred Retry', color: 'warning' }
    case 'verification_required':
      return { label: 'Verify Outcome', color: 'warning' }
    case 'failed':
    case 'failed_publishing':
      return { label: 'Publish Failed', color: 'error' }
    case 'approved':
      return { label: 'Approved Ready', color: 'success' }
    case 'pending_approval':
      return { label: 'Pending Approval', color: 'warning' }
    case 'cancelled':
      return { label: 'Cancelled', color: 'neutral' }
    case 'archived':
      return { label: 'Archived', color: 'neutral' }
    default:
      return { label: 'Unscheduled', color: 'neutral' }
  }
}

export function getConnectionStatusMeta(status: string | null | undefined): {
  label: string
  color: 'success' | 'warning' | 'error' | 'neutral' | 'info'
} {
  switch (status) {
    case 'connected':
      return { label: 'Connected', color: 'success' }
    case 'expiring_soon':
      return { label: 'Expiring Soon', color: 'warning' }
    case 'configured':
      return { label: 'Configured', color: 'info' }
    case 'expired':
      return { label: 'Token Expired', color: 'error' }
    case 'missing_permissions':
      return { label: 'Missing Scopes', color: 'warning' }
    case 'restricted':
      return { label: 'Restricted / Unsupported', color: 'error' }
    case 'error':
      return { label: 'Connection Error', color: 'error' }
    case 'disconnected':
      return { label: 'Disconnected', color: 'neutral' }
    default:
      return { label: 'Not Connected', color: 'neutral' }
  }
}

export function getEligibilityStatusMeta(status: string | null | undefined): {
  label: string
  color: 'success' | 'warning' | 'error' | 'neutral' | 'info'
} {
  switch (status) {
    case 'eligible':
      return { label: 'API Eligible', color: 'success' }
    case 'manual_only':
      return { label: 'Manual Publishing', color: 'info' }
    case 'requires_review':
      return { label: 'App / API Review Needed', color: 'warning' }
    case 'restricted':
      return { label: 'Restricted', color: 'error' }
    case 'unverified':
      return { label: 'Unverified', color: 'warning' }
    default:
      return { label: 'Unknown', color: 'neutral' }
  }
}

export function buildUrlWithUtm(
  baseUrl: string | null | undefined,
  utmParams: Record<string, string | null | undefined>,
): string {
  const clean = (baseUrl || '').trim()
  if (!clean) {
    return ''
  }
  try {
    const parsed = new URL(clean)
    for (const [k, rawVal] of Object.entries(utmParams)) {
      const val = (rawVal || '').trim()
      if (val) {
        parsed.searchParams.set(k.trim(), val)
      }
    }
    return parsed.toString()
  }
  catch {
    return clean
  }
}

export function formatUtcForLocalInput(
  utcIso: string | null | undefined,
  timezone = 'Asia/Manila',
): string {
  if (!utcIso) {
    const now = DateTime.now().setZone(timezone).plus({ hours: 1 }).startOf('minute')
    return now.toFormat("yyyy-LL-dd'T'HH:mm")
  }
  const dt = DateTime.fromISO(utcIso, { zone: 'utc' }).setZone(timezone)
  if (!dt.isValid) {
    return ''
  }
  return dt.toFormat("yyyy-LL-dd'T'HH:mm")
}

export function localInputToUtcIso(
  localValue: string,
  timezone = 'Asia/Manila',
): string | null {
  const trimmed = (localValue || '').trim()
  if (!trimmed) {
    return null
  }
  const dt = DateTime.fromISO(trimmed, { zone: timezone })
  if (!dt.isValid) {
    return null
  }
  return dt.toUTC().toISO()
}

export function buildManualPublishChecklist(platformKey: string | null | undefined): string[] {
  const steps = [
    'Review the final caption, hashtags, and tracked URL.',
    'Click Copy Final Content below to copy the ready-to-paste copy.',
  ]
  if (platformKey === 'instagram' || platformKey === 'pinterest') {
    steps.push('Download the attached image media and upload it to your post/pin.')
  }
  else {
    steps.push('Download any attached media asset if your post includes an image.')
  }
  steps.push(
    'Open the destination profile, publish natively on the platform, copy the live post URL, and record it in Mark as Published.',
  )
  return steps
}
