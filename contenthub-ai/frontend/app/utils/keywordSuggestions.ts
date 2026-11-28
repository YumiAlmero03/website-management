import type { ContentKeywordMapping } from '~/types/api'

export interface GameSuggestionWebsiteContext {
  name?: string | null
  brand_name?: string | null
  category_name?: string | null
}

export interface GameSuggestionContentInput {
  content_type: string
  title: string
  url?: string | null
  canonical_url?: string | null
  h1_text?: string | null
  meta_description?: string | null
  optimized_context_preview?: string | null
  optimized_context?: string | null
  markdown_content?: string | null
  extracted_content?: string | null
  categories?: string[] | null
  tags?: string[] | null
  keywords?: string[] | null
  yake_keywords?: string[] | null
  structured_data_json?: Record<string, unknown> | null
  website_name?: string | null
  website_category_name?: string | null
}

const KNOWN_GAME_PROVIDERS: readonly string[] = [
  'Pocket Games Soft',
  'Pragmatic Play',
  'Evolution Gaming',
  'Hacksaw Gaming',
  'Big Time Gaming',
  'Blueprint Gaming',
  'Spadegaming',
  'Spade Gaming',
  'Relax Gaming',
  'Push Gaming',
  'SmartSoft Gaming',
  'Microgaming',
  'Nolimit City',
  'Joker Gaming',
  'Habanero',
  'Red Tiger',
  'Thunderkick',
  'ELK Studios',
  'Games Global',
  'RubyPlay',
  'PopOK Gaming',
  'TaDa Gaming',
  'Spinomenal',
  'Endorphina',
  'Quickspin',
  'Quickfire',
  'Yggdrasil',
  'Playtech',
  'NetEnt',
  'Amusnet',
  'BGaming',
  'Betsoft',
  'Booongo',
  'Playson',
  'Evoplay',
  'Spribe',
  'SmartSoft',
  'Wazdan',
  'iSoftBet',
  'FastSpin',
  'NextSpin',
  'SimplePlay',
  'AdvantPlay',
  'YesGetRich',
  'Rich88',
  'Askmeslot',
  "Play'n GO",
  'Fa Chai',
  'FC Chai',
  'Fachai',
  'KA Gaming',
  'JILI Games',
  'JDB Gaming',
  'CQ9 Gaming',
  'JILI',
  'PG Soft',
  'JDB',
  'CQ9',
  'BNG',
  'BTG',
]

const GENERIC_NON_PROVIDER_TERMS = new Set([
  'slot',
  'slots',
  'slot game',
  'slot games',
  'casino',
  'live casino',
  'games',
  'game',
  'all games',
  'popular',
  'popular games',
  'new games',
  'featured',
  'hot',
  'all',
  'play',
  'demo',
  'free',
  'review',
  'home',
  'blog',
  'unknown',
  'none',
  'online',
])

const BOILERPLATE_GAME_SUFFIX_RE = /\s+(?:online\s+slot\s+games?|slot\s+games?|video\s+slots?|online\s+slots?|casino\s+games?|for\s+real\s+money|play\s+online|free\s+demo|demo\s+free|slots?|slot|games?|game|review|demo|play|online)\s*$/i

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function cleanWhitespace(value: string | null | undefined): string {
  return (value || '').replace(/\s+/g, ' ').trim()
}

function normalizeProviderCandidate(
  raw: string,
  excludedBrandTerms: Set<string>,
): string {
  let text = cleanWhitespace(raw)
    .replace(/^[:\-–•|]+|[:\-–•|.,;!?]+$/g, '')
    .trim()
  for (const b of excludedBrandTerms) {
    if (b) {
      text = text.replace(new RegExp(`\\s+(?:on|at|by|for|in)\\s+${escapeRegExp(b)}$`, 'i'), '').trim()
    }
  }
  const known = findKnownProviderInText(text)
  if (known) {
    return known
  }
  const trimmed = text
    .replace(/\s+(?:slots?|games?|provider)$/i, '')
    .trim()
  if (!trimmed || trimmed.length < 2 || trimmed.length > 48) {
    return ''
  }
  const low = trimmed.toLowerCase()
  if (GENERIC_NON_PROVIDER_TERMS.has(low) || excludedBrandTerms.has(low)) {
    return ''
  }
  if (trimmed.split(/\s+/).length > 4) {
    return ''
  }
  return trimmed
}

function buildExcludedBrandTerms(
  content: GameSuggestionContentInput,
  website?: GameSuggestionWebsiteContext | null,
): Set<string> {
  const out = new Set<string>()
  for (const val of [website?.brand_name, website?.name, content.website_name]) {
    const clean = cleanWhitespace(val).toLowerCase()
    if (clean) {
      out.add(clean)
    }
  }
  return out
}

function findKnownProviderInText(text: string): string {
  if (!text) {
    return ''
  }
  for (const provider of KNOWN_GAME_PROVIDERS) {
    const pattern = new RegExp(`(?<![a-z0-9])${escapeRegExp(provider)}(?![a-z0-9])`, 'i')
    if (pattern.test(text)) {
      return provider
    }
  }
  return ''
}

function extractLabeledProviderFromText(
  text: string,
  excludedBrandTerms: Set<string>,
): string {
  if (!text) {
    return ''
  }
  const labelRe = /(?:game\s+)?(?:provider|developer|studio|software|vendor)\s*[:\-–]\s*([^\n|,.;•·()]{2,45})/gi
  for (const match of text.matchAll(labelRe)) {
    const raw = match[1] || ''
    const cleaned = normalizeProviderCandidate(raw, excludedBrandTerms)
    if (cleaned) {
      return cleaned
    }
  }
  const byMatch = text.match(/(?:^|\s)by\s+([A-Za-z0-9'&.+\- ]{2,40})$/i)
  if (byMatch?.[1]) {
    const known = findKnownProviderInText(byMatch[1])
    if (known) {
      return known
    }
    const cleaned = normalizeProviderCandidate(byMatch[1], excludedBrandTerms)
    if (cleaned) {
      return cleaned
    }
  }
  return ''
}

function extractProviderFromStructuredData(
  structured: Record<string, unknown> | null | undefined,
  excludedBrandTerms: Set<string>,
): string {
  if (!structured) {
    return ''
  }
  const inspectNode = (node: unknown): string => {
    if (!node || typeof node !== 'object') {
      return ''
    }
    const record = node as Record<string, unknown>
    for (const key of ['provider', 'brand', 'publisher', 'manufacturer', 'creator', 'author']) {
      const val = record[key]
      if (typeof val === 'string') {
        const cleaned = normalizeProviderCandidate(val, excludedBrandTerms)
        if (cleaned) {
          return cleaned
        }
      }
      else if (val && typeof val === 'object' && typeof (val as Record<string, unknown>).name === 'string') {
        const cleaned = normalizeProviderCandidate(
          String((val as Record<string, unknown>).name),
          excludedBrandTerms,
        )
        if (cleaned) {
          return cleaned
        }
      }
    }
    return ''
  }

  const direct = inspectNode(structured)
  if (direct) {
    return direct
  }
  if (Array.isArray(structured.jsonld_objects)) {
    for (const obj of structured.jsonld_objects) {
      const found = inspectNode(obj)
      if (found) {
        return found
      }
    }
  }
  return ''
}

export function extractDetectedGameProvider(
  content: GameSuggestionContentInput,
  website?: GameSuggestionWebsiteContext | null,
): string {
  const excludedBrandTerms = buildExcludedBrandTerms(content, website)

  const fromStructured = extractProviderFromStructuredData(
    content.structured_data_json,
    excludedBrandTerms,
  )
  if (fromStructured) {
    return fromStructured
  }

  const richTexts = [
    content.meta_description || '',
    content.optimized_context_preview || '',
    content.optimized_context || '',
    content.markdown_content || '',
    content.extracted_content || '',
    content.h1_text || '',
    content.title || '',
  ]

  for (const text of richTexts) {
    const labeled = extractLabeledProviderFromText(text, excludedBrandTerms)
    if (labeled) {
      return labeled
    }
  }

  for (const term of [...(content.categories || []), ...(content.tags || [])]) {
    const known = findKnownProviderInText(term)
    if (known) {
      return known
    }
    const cand = normalizeProviderCandidate(term, excludedBrandTerms)
    if (cand) {
      return cand
    }
  }

  for (const text of richTexts) {
    const known = findKnownProviderInText(text)
    if (known) {
      return known
    }
  }

  const urlStr = content.canonical_url || content.url || ''
  if (urlStr) {
    try {
      const path = new URL(urlStr).pathname
      const segs = path.split('/').filter(Boolean)
      const gameRootIdx = segs.findIndex((s) => s.toLowerCase() === 'game' || s.toLowerCase() === 'games')
      if (gameRootIdx >= 0 && segs.length > gameRootIdx + 2) {
        const providerSeg = decodeURIComponent(segs[gameRootIdx + 1] || '').replace(/[-_]+/g, ' ')
        const known = findKnownProviderInText(providerSeg)
        if (known) {
          return known
        }
        const cand = normalizeProviderCandidate(providerSeg, excludedBrandTerms)
        if (cand) {
          return cand
        }
      }
      const fromUrlKnown = findKnownProviderInText(path.replace(/[-_/]+/g, ' '))
      if (fromUrlKnown) {
        return fromUrlKnown
      }
    }
    catch {
      // Ignore malformed URLs cleanly
    }
  }

  for (const kw of [...(content.keywords || []), ...(content.yake_keywords || [])]) {
    const known = findKnownProviderInText(kw)
    if (known) {
      return known
    }
  }

  return ''
}

function stripTitleSeparators(
  rawTitle: string,
  excludedBrandTerms: Set<string>,
  detectedProvider: string,
): string {
  let current = cleanWhitespace(rawTitle)
  if (!current) {
    return ''
  }
  const providerLow = detectedProvider.toLowerCase()
  for (const sep of [' | ', ' — ', ' :: ', ' - ']) {
    if (!current.includes(sep)) {
      continue
    }
    const parts = current.split(sep).map((p) => p.trim()).filter(Boolean)
    while (parts.length > 1) {
      const tailLow = parts[parts.length - 1]!.toLowerCase()
      const matchesBrand = Array.from(excludedBrandTerms).some((b) => b && tailLow.includes(b))
      const matchesProvider = Boolean(providerLow && tailLow.includes(providerLow))
      const isShortBoilerplate = tailLow.length <= 28 && /(?:slot|game|casino|review|play|demo|guide)/i.test(tailLow)
      if (matchesBrand || matchesProvider || isShortBoilerplate || parts[parts.length - 1]!.length <= 20) {
        parts.pop()
      }
      else {
        break
      }
    }
    current = parts.join(sep).trim()
  }
  if (detectedProvider) {
    current = current
      .replace(new RegExp(`\\s+by\\s+${escapeRegExp(detectedProvider)}$`, 'i'), '')
      .replace(new RegExp(`\\s+${escapeRegExp(detectedProvider)}$`, 'i'), '')
      .trim()
  }
  return current
}

function stripBoilerplateGameSuffixes(rawName: string): string {
  let out = cleanWhitespace(rawName).replace(/^[:\-–•|]+|[:\-–•|.,;!?]+$/g, '')
  for (let i = 0; i < 3; i++) {
    const stripped = out.replace(BOILERPLATE_GAME_SUFFIX_RE, '').trim()
    if (!stripped || stripped.length < 2) {
      break
    }
    out = stripped
  }
  return out
}

function slugToTitle(rawUrl: string | null | undefined): string {
  if (!rawUrl) {
    return ''
  }
  try {
    const segs = new URL(rawUrl).pathname
      .split('/')
      .map((s) => decodeURIComponent(s).trim())
      .filter(Boolean)
    const slug = (segs[segs.length - 1] || '').replace(/\.[a-z0-9]{2,5}$/i, '')
    if (!slug) {
      return ''
    }
    return slug
      .split(/[-_]+/)
      .filter(Boolean)
      .map((w) => (/^\d+$/.test(w) || (w.length <= 4 && w === w.toUpperCase())
        ? w
        : `${w.charAt(0).toUpperCase()}${w.slice(1).toLowerCase()}`))
      .join(' ')
  }
  catch {
    return ''
  }
}

export function extractGameName(
  content: GameSuggestionContentInput,
  website?: GameSuggestionWebsiteContext | null,
  detectedProvider?: string,
): string {
  const excludedBrandTerms = buildExcludedBrandTerms(content, website)
  const provider = detectedProvider ?? extractDetectedGameProvider(content, website)
  const candidates = [
    stripTitleSeparators(content.h1_text || '', excludedBrandTerms, provider),
    stripTitleSeparators(content.title || '', excludedBrandTerms, provider),
    slugToTitle(content.canonical_url || content.url),
  ]
  for (const raw of candidates) {
    const cleaned = stripBoilerplateGameSuffixes(raw)
    if (cleaned && !GENERIC_NON_PROVIDER_TERMS.has(cleaned.toLowerCase())) {
      return cleaned.slice(0, 120)
    }
  }
  return cleanWhitespace(content.h1_text || content.title || slugToTitle(content.canonical_url || content.url) || 'Slot Game').slice(0, 120)
}

export function buildSyncedAnchors(
  focusKeyphrase: string,
  secondaryKeywords: string[],
): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const raw of [focusKeyphrase, ...secondaryKeywords]) {
    const clean = cleanWhitespace(raw)
    const norm = clean.toLowerCase()
    if (clean && !seen.has(norm)) {
      seen.add(norm)
      out.push(clean)
    }
  }
  return out
}

export function areAnchorsSyncedWithKeywords(
  focusKeyphrase: string,
  secondaryKeywords: string[],
  anchors: string[] | null | undefined,
): boolean {
  const cleanAnchors = (anchors || []).map((a) => cleanWhitespace(a)).filter(Boolean)
  if (cleanAnchors.length === 0) {
    return true
  }
  const expected = buildSyncedAnchors(focusKeyphrase, secondaryKeywords)
  if (cleanAnchors.length !== expected.length) {
    return false
  }
  return cleanAnchors.every((anc, idx) => anc.toLowerCase() === expected[idx]!.toLowerCase())
}

export function shouldAutoSyncAnchorsForMapping(
  keywordMapping:
    | Pick<
      ContentKeywordMapping,
      | 'focus_keyphrase'
      | 'secondary_keywords'
      | 'anchor_text_variations'
      | 'suggestion_source'
      | 'is_admin_locked'
    >
    | null
    | undefined,
): boolean {
  if (!keywordMapping) {
    return true
  }
  if (!keywordMapping.is_admin_locked && keywordMapping.suggestion_source === 'python_auto') {
    return true
  }
  return areAnchorsSyncedWithKeywords(
    keywordMapping.focus_keyphrase,
    keywordMapping.secondary_keywords,
    keywordMapping.anchor_text_variations,
  )
}

export function buildGamePageKeywords(
  content: GameSuggestionContentInput,
  website?: GameSuggestionWebsiteContext | null,
): {
  gameName: string
  providerName: string
  brandName: string
  focusKeyphrase: string
  secondaryKeywords: string[]
  anchorTextVariations: string[]
} {
  const brandName = cleanWhitespace(website?.brand_name || website?.name || content.website_name)
  const detectedProvider = extractDetectedGameProvider(content, website)
  const gameName = extractGameName(content, website, detectedProvider)
  // Brand/website name is tracked independently and is never substituted as game provider.
  const providerName = detectedProvider

  const focusKeyphrase = `${gameName} slots`
  const focusNorm = focusKeyphrase.toLowerCase()
  const rawSecondary = [
    `${gameName} provider`,
    providerName ? `${gameName} ${providerName} slots` : '',
    brandName ? `${gameName} ${brandName}` : '',
    `${gameName} slot game`,
  ]
  const secondaryKeywords: string[] = []
  const seen = new Set<string>([focusNorm])
  for (const item of rawSecondary) {
    const clean = cleanWhitespace(item)
    const norm = clean.toLowerCase()
    if (clean && !seen.has(norm)) {
      seen.add(norm)
      secondaryKeywords.push(clean)
    }
  }
  const anchorTextVariations = buildSyncedAnchors(focusKeyphrase, secondaryKeywords)
  return {
    gameName,
    providerName,
    brandName,
    focusKeyphrase,
    secondaryKeywords,
    anchorTextVariations,
  }
}

export function resolveInitialKeywordSuggestion(options: {
  content: GameSuggestionContentInput
  keywordMapping?: ContentKeywordMapping | null
  approvalStatus?: string | null
  website?: GameSuggestionWebsiteContext | null
  overrideContentType?: string
}): {
  focusKeyphrase: string
  secondaryKeywords: string[]
  anchorTextVariations: string[]
  shouldSyncAnchors: boolean
} {
  const { content, keywordMapping, approvalStatus, website, overrideContentType } = options
  const effectiveType = overrideContentType || content.content_type
  const isLockedOrManual = Boolean(
    keywordMapping?.is_admin_locked
    || keywordMapping?.suggestion_source === 'manual'
    || approvalStatus === 'approved',
  )
  const backendTemplateReady = Boolean(
    keywordMapping?.focus_keyphrase
    && (
      keywordMapping.suggestion_source === 'template_generated'
      || keywordMapping.keyword_generation_method === 'template'
      || keywordMapping.keyword_generation_status === 'generated'
    ),
  )
  const shouldSyncAnchors = shouldAutoSyncAnchorsForMapping(keywordMapping)

  if (!isLockedOrManual && effectiveType === 'game_page' && (!backendTemplateReady || overrideContentType === 'game_page')) {
    const gameSuggestion = buildGamePageKeywords(content, website)
    return {
      focusKeyphrase: gameSuggestion.focusKeyphrase,
      secondaryKeywords: gameSuggestion.secondaryKeywords,
      anchorTextVariations: gameSuggestion.anchorTextVariations,
      shouldSyncAnchors: true,
    }
  }

  const focusKeyphrase = cleanWhitespace(keywordMapping?.focus_keyphrase)
  const secondaryKeywords = [...(keywordMapping?.secondary_keywords || [])]
  const anchorTextVariations = shouldSyncAnchors
    ? buildSyncedAnchors(focusKeyphrase, secondaryKeywords)
    : [...(keywordMapping?.anchor_text_variations || [])]

  return {
    focusKeyphrase,
    secondaryKeywords,
    anchorTextVariations,
    shouldSyncAnchors,
  }
}
