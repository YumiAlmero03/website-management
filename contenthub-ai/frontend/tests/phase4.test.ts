import { describe, expect, it } from 'vitest'
import {
  buildManualPublishChecklist,
  buildUrlWithUtm,
  formatUtcForLocalInput,
  getConnectionStatusMeta,
  getEligibilityStatusMeta,
  getPublishingStatusMeta,
  localInputToUtcIso,
} from '../app/utils/ai'
import { SIDEBAR_MODULES } from '../app/utils/navigation'

describe('Phase 4 publishing navigation & utilities', () => {
  it('activates connected-accounts and publishing-calendar while keeping Phase 5-6 honest', () => {
    const byId = Object.fromEntries(SIDEBAR_MODULES.map((m) => [m.id, m]))
    expect(byId['connected-accounts']?.implemented).toBe(true)
    expect(byId['publishing-calendar']?.implemented).toBe(true)
    expect(byId['editorial-planner']?.implemented).toBeFalsy()
    expect(byId['seo-analytics']?.implemented).toBeFalsy()
  })

  it('builds UTM URLs cleanly without clobbering existing query params or fragments', () => {
    const result = buildUrlWithUtm('https://bygame.ph/blog/odds?ref=home#section', {
      utm_source: 'facebook',
      utm_medium: 'social',
      utm_campaign: 'q4_launch',
      utm_content: '',
    })
    const parsed = new URL(result)
    expect(parsed.searchParams.get('ref')).toBe('home')
    expect(parsed.searchParams.get('utm_source')).toBe('facebook')
    expect(parsed.searchParams.get('utm_medium')).toBe('social')
    expect(parsed.searchParams.get('utm_campaign')).toBe('q4_launch')
    expect(parsed.searchParams.has('utm_content')).toBe(false)
    expect(parsed.hash).toBe('#section')
  })

  it('converts Asia/Manila schedule input to UTC ISO and back accurately', () => {
    const utcIso = localInputToUtcIso('2026-12-01T21:30', 'Asia/Manila')
    expect(utcIso).toBeTruthy()
    expect(utcIso?.startsWith('2026-12-01T13:30:00')).toBe(true)

    const backLocal = formatUtcForLocalInput('2026-12-01T13:30:00Z', 'Asia/Manila')
    expect(backLocal).toBe('2026-12-01T21:30')
  })

  it('returns coherent status metadata and manual checklist steps', () => {
    expect(getPublishingStatusMeta('verification_required').color).toBe('warning')
    expect(getPublishingStatusMeta('manually_published').label).toContain('Manual')
    expect(getConnectionStatusMeta('expiring_soon').color).toBe('warning')
    expect(getEligibilityStatusMeta('requires_review').color).toBe('warning')

    const igChecklist = buildManualPublishChecklist('instagram')
    expect(igChecklist.some((step) => step.toLowerCase().includes('image media'))).toBe(true)
  })
})
