import { describe, expect, it } from 'vitest'
import {
  buildAssembledSocialDraft,
  estimateAssembledLength,
  getDraftStatusMeta,
  getJobStatusMeta,
  getQuotaStatusMeta,
  isContentEligibleForManualGeneration,
} from '../app/utils/ai'
import { SIDEBAR_MODULES } from '../app/utils/navigation'

describe('Phase 3 navigation & AI helpers', () => {
  it('activates AI Management and Social Media in Phase 3 without restoring removed modules', () => {
    const social = SIDEBAR_MODULES.find((m) => m.id === 'social-media')
    const ai = SIDEBAR_MODULES.find((m) => m.id === 'ai-management')
    expect(social?.implemented).toBe(true)
    expect(social?.phase).toBe(3)
    expect(ai?.implemented).toBe(true)
    expect(ai?.phase).toBe(3)
    expect(SIDEBAR_MODULES.find((m) => m.id === 'connected-accounts')?.implemented).toBe(true)
    expect(SIDEBAR_MODULES.find((m) => m.id === 'publishing-calendar')?.implemented).toBe(true)
    expect(SIDEBAR_MODULES.find((m) => m.id === 'editorial-planner')?.implemented).toBeFalsy()
    expect(SIDEBAR_MODULES.find((m) => m.id === 'articles')?.implemented).toBeFalsy()
  })

  it('validates content eligibility for manual social generation', () => {
    expect(
      isContentEligibleForManualGeneration({
        extraction_status: 'extracted',
        content_type: 'blog_post',
        is_excluded: false,
      }),
    ).toBe(true)
    expect(
      isContentEligibleForManualGeneration({
        extraction_status: 'extracted',
        content_type: 'game_page',
        is_excluded: false,
      }),
    ).toBe(true)
    expect(
      isContentEligibleForManualGeneration({
        extraction_status: 'pending',
        content_type: 'blog_post',
        is_excluded: false,
      }),
    ).toBe(false)
    expect(
      isContentEligibleForManualGeneration({
        extraction_status: 'extracted',
        content_type: 'category',
        is_excluded: false,
      }),
    ).toBe(false)
    expect(
      isContentEligibleForManualGeneration({
        extraction_status: 'extracted',
        content_type: 'page',
        is_excluded: true,
      }),
    ).toBe(false)
  })

  it('calculates X/Twitter character counts treating URLs as 23 characters', () => {
    const longUrl = 'https://bygame.ph/blog/ultra-long-slug-parameter-testing-url-count-behavior'
    const text = `Check this guide!\n\n${longUrl}`
    expect(estimateAssembledLength(text, 'twitter')).toBe('Check this guide!\n\n'.length + 23)
    expect(estimateAssembledLength(text, 'facebook')).toBe(text.length)
  })

  it('assembles social draft text cleanly without duplicating CTA or hashtags', () => {
    const assembled = buildAssembledSocialDraft({
      caption: 'Big weekend kickoff!',
      ctaText: 'Join now',
      sourceUrl: 'https://bygame.ph/blog/kickoff',
      hashtags: ['Bygame', '#LiveSports'],
    })
    expect(assembled).toContain('Big weekend kickoff!')
    expect(assembled).toContain('Join now')
    expect(assembled).toContain('https://bygame.ph/blog/kickoff')
    expect(assembled).toContain('#Bygame #LiveSports')

    const deduped = buildAssembledSocialDraft({
      caption: 'Big weekend kickoff! Join now',
      ctaText: 'Join now',
      sourceUrl: 'https://bygame.ph/blog/kickoff',
      hashtags: [],
    })
    expect(deduped.match(/Join now/g)?.length).toBe(1)
  })

  it('maps draft, job, and quota status badges deterministically', () => {
    expect(getDraftStatusMeta('pending_review').color).toBe('info')
    expect(getDraftStatusMeta('approved').color).toBe('success')
    expect(getJobStatusMeta('deferred').color).toBe('warning')
    expect(getQuotaStatusMeta('daily_requests_exhausted').color).toBe('error')
  })
})
