import { describe, expect, it } from 'vitest'
import {
  extractErrorMessage,
  formatDateTime,
  formatMegabytes,
  humanizeCategory,
} from '~/utils/format'

describe('format utilities', () => {
  it('formats UTC timestamps in Asia/Manila timezone cleanly', () => {
    const formatted = formatDateTime('2026-11-26T00:00:00Z', 'Asia/Manila')
    expect(formatted).toContain('2026')
    expect(formatted).toContain('08:00:00')
    expect(formatDateTime(null)).toBe('Never')
  })

  it('formats memory megabytes and humanizes categories', () => {
    expect(formatMegabytes(512)).toBe('512 MB')
    expect(formatMegabytes(2048)).toBe('2.00 GB')
    expect(humanizeCategory('resource_guardian')).toBe('Resource Guardian')
  })

  it('extracts FastAPI detail errors with fallback', () => {
    expect(extractErrorMessage({ data: { detail: 'Invalid CSRF token.' } })).toBe('Invalid CSRF token.')
    expect(extractErrorMessage(new Error('Network error'))).toBe('Network error')
    expect(extractErrorMessage(null, 'Fallback message')).toBe('Fallback message')
  })
})
