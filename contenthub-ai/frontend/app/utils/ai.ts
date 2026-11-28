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
