export function formatDateTime(
  value: string | null | undefined,
  timezone = 'Asia/Manila',
): string {
  if (!value) {
    return 'Never'
  }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }
  try {
    return new Intl.DateTimeFormat('en-PH', {
      timeZone: timezone,
      year: 'numeric',
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }).format(parsed)
  }
  catch {
    return parsed.toISOString()
  }
}

export function formatMegabytes(mb: number): string {
  if (mb >= 1024) {
    return `${(mb / 1024).toFixed(2)} GB`
  }
  return `${Math.round(mb)} MB`
}

export function extractErrorMessage(error: unknown, fallback = 'An unexpected error occurred.'): string {
  if (error && typeof error === 'object') {
    const err = error as {
      data?: { detail?: string }
      response?: { _data?: { detail?: string } }
      statusMessage?: string
      message?: string
    }
    if (typeof err.data?.detail === 'string' && err.data.detail.trim()) {
      return err.data.detail
    }
    if (typeof err.response?._data?.detail === 'string' && err.response._data.detail.trim()) {
      return err.response._data.detail
    }
    if (typeof err.message === 'string' && err.message.trim()) {
      return err.message
    }
  }
  return fallback
}

export function humanizeCategory(category: string): string {
  return category
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

export const APPROVAL_ELIGIBLE_CONTENT_TYPES = [
  'homepage',
  'page',
  'game_page',
  'blog_post',
] as const

export function isApprovalEligibleContentType(contentType: string): boolean {
  return (APPROVAL_ELIGIBLE_CONTENT_TYPES as readonly string[]).includes(contentType)
}

export const CONTENT_TYPE_OPTIONS = [
  { label: 'Homepage', value: 'homepage' },
  { label: 'Page', value: 'page' },
  { label: 'Game Page', value: 'game_page' },
  { label: 'Blog Index', value: 'blog_index' },
  { label: 'Blog Post', value: 'blog_post' },
  { label: 'Category', value: 'category' },
  { label: 'Tag', value: 'tag' },
  { label: 'Archive', value: 'archive' },
  { label: 'Custom', value: 'custom' },
]

export const WEBSITE_TECHNOLOGY_OPTIONS = [
  { label: 'WordPress', value: 'wordpress' },
  { label: 'Nuxt', value: 'nuxt' },
  { label: 'Next.js', value: 'nextjs' },
  { label: 'Custom PHP', value: 'custom_php' },
  { label: 'Static HTML', value: 'static_html' },
  { label: 'Other CMS', value: 'other_cms' },
  { label: 'Custom REST API', value: 'custom_rest_api' },
]

export const DISCOVERY_METHOD_OPTIONS = [
  { label: 'Auto-Aggregated (Recommended — All Sources)', value: 'auto' },
  { label: 'Sitemap Only', value: 'sitemap' },
  { label: 'RSS / Atom Feed', value: 'rss' },
  { label: 'WordPress REST API', value: 'wordpress' },
  { label: 'HTML Internal Links', value: 'html' },
  { label: 'llms.txt', value: 'llms_txt' },
  { label: 'Custom REST API', value: 'rest_api' },
]

type UiBadgeColor = 'primary' | 'secondary' | 'success' | 'info' | 'warning' | 'error' | 'neutral'

const CONTENT_TYPE_META: Record<string, { label: string; color: UiBadgeColor }> = {
  homepage: { label: 'Homepage', color: 'info' },
  page: { label: 'Page', color: 'secondary' },
  game_page: { label: 'Game Page', color: 'success' },
  blog_index: { label: 'Blog Index', color: 'warning' },
  blog_post: { label: 'Blog Post', color: 'primary' },
  category: { label: 'Category', color: 'neutral' },
  tag: { label: 'Tag', color: 'neutral' },
  archive: { label: 'Archive', color: 'neutral' },
  custom: { label: 'Custom', color: 'success' },
}

export function getContentTypeMeta(contentType: string): { label: string; color: UiBadgeColor } {
  return CONTENT_TYPE_META[contentType] ?? {
    label: humanizeCategory(contentType || 'page'),
    color: 'neutral',
  }
}
