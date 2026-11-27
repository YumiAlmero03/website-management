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
