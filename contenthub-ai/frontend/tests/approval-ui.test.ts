import { describe, expect, it } from 'vitest'
import { getApprovalStatusMeta } from '~/utils/ai'
import {
  CONTENT_TYPE_OPTIONS,
  getContentTypeMeta,
  isApprovalEligibleContentType,
} from '~/utils/format'
import {
  areAnchorsSyncedWithKeywords,
  buildGamePageKeywords,
  buildSyncedAnchors,
  resolveInitialKeywordSuggestion,
  shouldAutoSyncAnchorsForMapping,
} from '~/utils/keywordSuggestions'

describe('approval status helpers', () => {
  it('maps all Phase 3 approval workflow states cleanly', () => {
    expect(getApprovalStatusMeta('awaiting_extraction')).toEqual({
      label: 'Awaiting Extraction',
      color: 'info',
    })
    expect(getApprovalStatusMeta('pending_review')).toEqual({
      label: 'Pending Review',
      color: 'warning',
    })
    expect(getApprovalStatusMeta('needs_rereview')).toEqual({
      label: 'Needs Re-review',
      color: 'error',
    })
    expect(getApprovalStatusMeta('approved')).toEqual({
      label: 'Approved',
      color: 'success',
    })
    expect(getApprovalStatusMeta('rejected')).toEqual({
      label: 'Rejected',
      color: 'neutral',
    })
  })

  it('includes game_page in content type options, metadata, and approval eligibility', () => {
    expect(CONTENT_TYPE_OPTIONS.some((o) => o.value === 'game_page' && o.label === 'Game Page')).toBe(true)
    expect(getContentTypeMeta('game_page').label).toBe('Game Page')
    expect(isApprovalEligibleContentType('game_page')).toBe(true)
    expect(isApprovalEligibleContentType('category')).toBe(false)
  })

  it('builds game_page focus, secondary keywords, and matching anchor text variations with detected provider', () => {
    const result = buildGamePageKeywords(
      {
        content_type: 'game_page',
        title: 'Gates of Olympus Slot Game | Bygame',
        h1_text: 'Gates of Olympus',
        canonical_url: 'https://bygame.ph/games/gates-of-olympus',
        meta_description: 'Play Gates of Olympus slot by Provider: Pragmatic Play on Bygame.',
      },
      { name: 'Bygame Casino', brand_name: 'Bygame', category_name: 'Casino' },
    )
    expect(result.gameName).toBe('Gates of Olympus')
    expect(result.providerName).toBe('Pragmatic Play')
    expect(result.focusKeyphrase).toBe('Gates of Olympus slots')
    expect(result.secondaryKeywords).toEqual([
      'Gates of Olympus provider',
      'Gates of Olympus Pragmatic Play slots',
      'Gates of Olympus Bygame',
      'Gates of Olympus slot game',
    ])
    expect(result.anchorTextVariations).toEqual([
      result.focusKeyphrase,
      ...result.secondaryKeywords,
    ])
  })

  it('omits provider slot variation when no game provider is found and avoids false title positives', () => {
    const fallbackResult = buildGamePageKeywords(
      {
        content_type: 'game_page',
        title: "Joker's Jewels - Play Online | Arena",
        canonical_url: 'https://arena.ph/games/jokers-jewels',
        meta_description: 'Classic gem slot action.',
      },
      { name: 'Arena Slots', brand_name: 'Arena', category_name: 'Casino' },
    )
    expect(fallbackResult.gameName).toBe("Joker's Jewels")
    expect(fallbackResult.providerName).toBe('')
    expect(fallbackResult.focusKeyphrase).toBe("Joker's Jewels slots")
    expect(fallbackResult.secondaryKeywords).toEqual([
      "Joker's Jewels provider",
      "Joker's Jewels Arena",
      "Joker's Jewels slot game",
    ])

    const backendTemplatePreserved = resolveInitialKeywordSuggestion({
      content: {
        content_type: 'game_page',
        title: "Joker's Jewels",
        canonical_url: 'https://arena.ph/games/jokers-jewels',
      },
      keywordMapping: {
        id: 2,
        website_id: 1,
        website_content_id: 2,
        focus_keyphrase: "Joker's Jewels slots",
        secondary_keywords: ["Joker's Jewels provider", "Joker's Jewels Arena", "Joker's Jewels slot game"],
        anchor_text_variations: ["Joker's Jewels slots", "Joker's Jewels provider", "Joker's Jewels Arena", "Joker's Jewels slot game"],
        image_alt_suggestions: [],
        approval_status: 'pending_review',
        suggestion_source: 'template_generated',
        keyword_generation_method: 'template',
        keyword_generation_status: 'generated',
        keyword_evidence: [],
        keyword_scores: {},
        keyword_model: null,
        keyword_input_hash: null,
        keyword_generated_at: null,
        game_name: "Joker's Jewels",
        provider_name: null,
        is_admin_locked: false,
        version: 1,
        cannibalization_warnings: [],
        last_reviewed_at: null,
        approved_by: null,
        approved_at: null,
        created_at: '2026-11-27T00:00:00Z',
        updated_at: '2026-11-27T00:00:00Z',
      },
      website: { name: 'Arena Slots', brand_name: 'Arena', category_name: 'Casino' },
    })
    expect(backendTemplatePreserved.secondaryKeywords).toEqual([
      "Joker's Jewels provider",
      "Joker's Jewels Arena",
      "Joker's Jewels slot game",
    ])
  })

  it('syncs anchor variations with focus + secondary unless custom modal anchors were saved', () => {
    const synced = buildSyncedAnchors('Fixed Odds', ['Dynamic Odds', 'Fixed Odds'])
    expect(synced).toEqual(['Fixed Odds', 'Dynamic Odds'])
    expect(areAnchorsSyncedWithKeywords('Fixed Odds', ['Dynamic Odds'], ['Fixed Odds', 'Dynamic Odds'])).toBe(true)
    expect(areAnchorsSyncedWithKeywords('Fixed Odds', ['Dynamic Odds'], ['Click here for odds'])).toBe(false)

    expect(
      shouldAutoSyncAnchorsForMapping({
        focus_keyphrase: 'Fixed Odds',
        secondary_keywords: ['Dynamic Odds'],
        anchor_text_variations: ['learn about fixed odds'],
        suggestion_source: 'python_auto',
        is_admin_locked: false,
      }),
    ).toBe(true)

    expect(
      shouldAutoSyncAnchorsForMapping({
        focus_keyphrase: 'Fixed Odds',
        secondary_keywords: ['Dynamic Odds'],
        anchor_text_variations: ['Custom Modal Anchor'],
        suggestion_source: 'manual',
        is_admin_locked: true,
      }),
    ).toBe(false)

    const preservedManual = resolveInitialKeywordSuggestion({
      content: {
        content_type: 'game_page',
        title: 'Super Ace',
        canonical_url: 'https://bygame.ph/games/super-ace',
      },
      keywordMapping: {
        id: 1,
        website_id: 1,
        website_content_id: 1,
        focus_keyphrase: 'Custom Super Ace Keyphrase',
        secondary_keywords: ['Custom Secondary'],
        anchor_text_variations: ['Custom Anchor'],
        image_alt_suggestions: [],
        approval_status: 'pending_review',
        suggestion_source: 'manual',
        keyword_generation_method: 'manual',
        keyword_generation_status: 'generated',
        keyword_evidence: [],
        keyword_scores: {},
        keyword_model: null,
        keyword_input_hash: null,
        keyword_generated_at: null,
        game_name: 'Super Ace',
        provider_name: null,
        is_admin_locked: true,
        version: 2,
        cannibalization_warnings: [],
        last_reviewed_at: null,
        approved_by: null,
        approved_at: null,
        created_at: '2026-11-27T00:00:00Z',
        updated_at: '2026-11-27T00:00:00Z',
      },
      website: { name: 'Bygame', brand_name: 'Bygame', category_name: 'Casino' },
    })
    expect(preservedManual.focusKeyphrase).toBe('Custom Super Ace Keyphrase')
    expect(preservedManual.anchorTextVariations).toEqual(['Custom Anchor'])
  })
})
