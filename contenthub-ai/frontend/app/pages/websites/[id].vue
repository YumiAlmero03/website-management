<script setup lang="ts">
import {
  Activity,
  ArrowLeft,
  CheckCircle,
  Compass,
  ExternalLink,
  ImagePlus,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  SearchCheck,
  Trash2,
} from 'lucide-vue-next'
import type {
  ContentListItem,
  ContentListResponse,
  IndexingAccountTestResult,
  IndexingStatus,
  ScanItem,
  ScanItemListResponse,
  ScanLog,
  ScanLogListResponse,
  Website,
  WebsiteCategory,
  WebsiteCategoryListResponse,
  WebsiteConnectivity,
  WebsiteDiscoverResult,
  WebsiteDiscoverySource,
  WebsiteUrlRule,
} from '~/types/api'
import {
  DISCOVERY_METHOD_OPTIONS,
  WEBSITE_TECHNOLOGY_OPTIONS,
  extractErrorMessage,
  formatDateTime,
  getContentTypeMeta,
} from '~/utils/format'

const route = useRoute()
const { request } = useApiClient()
const uiStore = useUiStore()
const toast = useToast()

const websiteId = computed(() => Number(route.params.id))

const website = ref<Website | null>(null)
const categories = ref<WebsiteCategory[]>([])
const sources = ref<WebsiteDiscoverySource[]>([])
const urlRules = ref<WebsiteUrlRule[]>([])
const scanLogs = ref<ScanLog[]>([])
const websiteContents = ref<ContentListItem[]>([])
const contentTabFilter = ref<string>('all')
const keywordBank = shallowRef<string[]>([])
const keywordSearch = ref('')
const keywordPage = ref(1)
const keywordPageSize = 100
const filteredKeywords = computed(() => {
  const search = keywordSearch.value.trim().toLowerCase().replace(/\s+/g, ' ')
  return search ? keywordBank.value.filter(keyword => keyword.toLowerCase().includes(search)) : keywordBank.value
})
const visibleKeywords = computed(() => {
  const start = (keywordPage.value - 1) * keywordPageSize
  return filteredKeywords.value.slice(start, start + keywordPageSize)
})

const loading = ref(true)
const errorMessage = ref<string | null>(null)
type Section = 'content' | 'scanner' | 'history' | 'settings' | 'keyword_bank'
type WebsiteTab = Section | 'overview' | 'social_profiles' | 'ai_settings'
const activeTab = ref<WebsiteTab>('overview')
const sections: Section[] = ['content', 'scanner', 'history', 'settings', 'keyword_bank']
const sectionStates = reactive(new Map<Section, { loading: boolean; error: string | null }>())
const triggeringScan = ref(false)
const testingConnectivity = ref(false)
const discoveringSources = ref(false)
const uploadingLogo = ref(false)
const uploadingGscServiceAccount = ref(false)
const removingGscServiceAccount = ref(false)
const savingSettings = ref(false)
const indexingStatus = ref<IndexingStatus>({
  state: 'idle',
  progress: 0,
  total: 0,
  processed: 0,
  indexed: 0,
  skipped: 0,
  ready: 0,
  failed: 0,
})
const indexingStatusError = ref<string | null>(null)
const testingGscAccount = ref(false)
const gscAccountTestResult = ref<IndexingAccountTestResult | null>(null)
let indexingPoll: ReturnType<typeof setInterval> | null = null

const connectivityResult = ref<WebsiteConnectivity | null>(null)
const discoverResult = ref<WebsiteDiscoverResult | null>(null)

// Scan items inspection modal
const inspectModalOpen = ref(false)
const inspectedScan = ref<ScanLog | null>(null)
const inspectItems = ref<ScanItem[]>([])
const inspectLoading = ref(false)
const inspectFilter = ref<'all' | 'failures' | 'pending'>('failures')

// URL classification rule modal
const ruleModalOpen = ref(false)
const savingRule = ref(false)
const ruleForm = ref({
  pattern: '/guides/*',
  target_content_type: 'blog_post',
  match_mode: 'glob',
  priority: 50,
  notes: '',
})

// Website + Brand settings form
const settingsForm = ref({
  name: '',
  brand_name: '',
  category_id: '',
  domain: '',
  website_type: 'wordpress',
  discovery_method: 'auto',
  single_source_only: false,
  status: 'active',
  primary_language: 'en',
  secondary_languages_text: '',
  target_country: '',
  target_audience: '',
  tone: '',
  brand_description: '',
  target_keywords_text: '',
  keyword_bank_text: '',
  restricted_keywords_text: '',
  default_hashtags_text: '',
  default_cta: '',
  writing_guidelines: '',
  ai_instructions: '',
  rss_url: '',
  sitemap_url: '',
  llms_url: '',
  api_endpoint: '',
  gsc_property_url: '',
  excluded_url_patterns_text: '',
  scan_interval_minutes: 1440,
  crawl_batch_size: 100,
  crawl_max_urls_per_run: 1000,
  auto_scan: true,
})

let pollTimer: ReturnType<typeof setTimeout> | null = null
let pollVersion = 0
let workspaceVersion = 0

const activeScan = computed(() =>
  scanLogs.value.find((s) => s.status === 'pending' || s.status === 'processing') || null,
)

const resumableScan = computed(() =>
  scanLogs.value.find(
    (s) =>
      (s.status === 'incomplete' || s.status === 'paused' || s.status === 'partially_completed')
      && s.urls_pending_extraction > 0,
  ) || null,
)

const canResumeScan = computed(
  () => Boolean(resumableScan.value) || (website.value?.content_counts.pending ?? 0) > 0,
)
const indexingInProgress = computed(
  () => indexingStatus.value.state === 'queued' || indexingStatus.value.state === 'processing',
)
const gscPropertySaved = computed(
  () => Boolean(
    website.value?.gsc_property_url
    && settingsForm.value.gsc_property_url.trim() === website.value.gsc_property_url,
  ),
)
const canTestGscAccount = computed(
  () => Boolean(website.value?.gsc_service_account_configured && gscPropertySaved.value),
)
const indexingSetupVerified = computed(
  () => Boolean(
    canTestGscAccount.value
    && website.value?.gsc_property_verified_at,
  ),
)
const indexingButtonLabel = computed(() => {
  if (indexingInProgress.value) {
    return `Indexing (${indexingStatus.value.progress}/${indexingStatus.value.total})`
  }
  if (indexingStatus.value.state === 'completed') return 'Completed'
  if (indexingStatus.value.state === 'deferred') return 'Deferred'
  return 'Run Indexing'
})

function parseCsvOrLines(raw: string): string[] {
  return raw
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

function syncSettingsForm(site: Website) {
  settingsForm.value = {
    name: site.name,
    brand_name: site.brand_name,
    category_id: site.category_id ? String(site.category_id) : '',
    domain: site.domain,
    website_type: site.website_type,
    discovery_method: site.discovery_method,
    single_source_only: site.single_source_only,
    status: site.status,
    primary_language: site.primary_language,
    secondary_languages_text: site.secondary_languages.join(', '),
    target_country: site.target_country || '',
    target_audience: site.target_audience || '',
    tone: site.tone || '',
    brand_description: site.brand_description || '',
    target_keywords_text: site.target_keywords.join(', '),
    keyword_bank_text: site.keyword_bank.join(', '),
    restricted_keywords_text: site.restricted_keywords.join(', '),
    default_hashtags_text: site.default_hashtags.join(', '),
    default_cta: site.default_cta || '',
    writing_guidelines: site.writing_guidelines || '',
    ai_instructions: site.ai_instructions || '',
    rss_url: site.rss_url || '',
    sitemap_url: site.sitemap_url || '',
    llms_url: site.llms_url || '',
    api_endpoint: site.api_endpoint || '',
    gsc_property_url: site.gsc_property_url || '',
    excluded_url_patterns_text: site.excluded_url_patterns.join('\n'),
    scan_interval_minutes: site.scan_interval_minutes,
    crawl_batch_size: site.crawl_batch_size,
    crawl_max_urls_per_run: site.crawl_max_urls_per_run,
    auto_scan: site.auto_scan,
  }
}

function stopIndexingPolling() {
  if (indexingPoll) {
    clearInterval(indexingPoll)
    indexingPoll = null
  }
}

function ensureIndexingPolling() {
  if (indexingPoll) return
  indexingPoll = setInterval(() => {
    void refreshIndexingStatus()
  }, 3000)
}

async function refreshIndexingStatus() {
  try {
    indexingStatus.value = await request<IndexingStatus>(
      `/api/v1/indexing/websites/${websiteId.value}/status`,
    )
    indexingStatusError.value = null
    if (indexingInProgress.value) ensureIndexingPolling()
    else stopIndexingPolling()
  }
  catch (err) {
    indexingStatusError.value = extractErrorMessage(err, 'Could not load Google indexing status.')
    stopIndexingPolling()
  }
}

async function runIndexing() {
  try {
    indexingStatus.value = await request<IndexingStatus>(
      `/api/v1/indexing/websites/${websiteId.value}/run`,
      { method: 'POST' },
    )
    indexingStatusError.value = null
    ensureIndexingPolling()
    toast.add({
      title: 'Indexing started',
      description: 'The background check will continue if you leave this page.',
      color: 'success',
    })
  }
  catch (err) {
    toast.add({
      title: 'Could not start indexing',
      description: extractErrorMessage(err, 'An indexing job could not be started.'),
      color: 'error',
    })
  }
}

async function testGscAccount() {
  testingGscAccount.value = true
  gscAccountTestResult.value = null
  try {
    const result = await request<IndexingAccountTestResult>(
      `/api/v1/indexing/websites/${websiteId.value}/test-account`,
      { method: 'POST' },
    )
    gscAccountTestResult.value = result
    if (website.value) website.value.gsc_property_verified_at = result.verified_at
    toast.add({
      title: 'Search Console account verified',
      description: `${result.account_email} can access ${result.property_url}.`,
      color: 'success',
    })
  }
  catch (err) {
    toast.add({
      title: 'Search Console account test failed',
      description: extractErrorMessage(err, 'Could not verify access to this Search Console property.'),
      color: 'error',
    })
  }
  finally {
    testingGscAccount.value = false
  }
}

watch(() => indexingStatus.value.state, (state) => {
  if (state === 'completed') {
    toast.add({
      title: 'Indexing completed',
      description: `${indexingStatus.value.processed} processed · ${indexingStatus.value.indexed} indexed · ${indexingStatus.value.skipped} skipped · ${indexingStatus.value.ready} ready to request · ${indexingStatus.value.failed} failed`,
      color: 'success',
    })
    if (activeTab.value === 'content') void loadSection('content', true)
  }
  if (state === 'deferred') {
    toast.add({
      title: 'Indexing deferred',
      description: 'Resource Guardian paused the job. Select Deferred to resume it later.',
      color: 'warning',
    })
  }
})

function stopPolling() {
  pollVersion++
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

function ensurePolling() {
  if (!activeScan.value) {
    stopPolling()
    return
  }
  if (pollTimer) {
    return
  }
  const id = websiteId.value
  const version = pollVersion
  pollTimer = setTimeout(async () => {
    try {
      const logsData = await fetchScanLogs(id)
      if (version !== pollVersion) return
      pollTimer = null
      scanLogs.value = logsData.items
      if (activeScan.value) {
        ensurePolling()
      }
      else {
        const siteData = await request<Website>(`/api/v1/websites/${id}`)
        if (version !== pollVersion) return
        website.value = siteData
        for (const section of ['content', 'scanner', 'keyword_bank'] as const) {
          sectionStates.delete(section)
        }
        loadActiveSection()
      }
    }
    catch {
      if (version === pollVersion) stopPolling()
    }
  }, 2000)
}

function fetchScanLogs(id: number) {
  return request<ScanLogListResponse>(`/api/v1/websites/${id}/scan-logs`, {
    query: { page: 1, page_size: 20 },
  })
}

async function loadSection(section: Section, force = false) {
  if (!force && sectionStates.has(section)) return
  const state = reactive({ loading: true, error: null as string | null })
  sectionStates.set(section, state)
  const id = websiteId.value
  const root = `/api/v1/websites/${id}`
  const isCurrent = () => sectionStates.get(section) === state
  try {
    switch (section) {
      case 'content': {
        const res = await request<ContentListResponse>('/api/v1/contents', {
          query: { website_id: id, tab: contentTabFilter.value, page: 1, page_size: 25 },
        })
        if (isCurrent()) websiteContents.value = res.items
        break
      }
      case 'scanner': {
        const [sourceData, ruleData] = await Promise.all([
          request<WebsiteDiscoverySource[]>(`${root}/sources`),
          request<WebsiteUrlRule[]>(`${root}/rules`),
        ])
        if (isCurrent()) {
          sources.value = sourceData
          urlRules.value = ruleData
        }
        break
      }
      case 'history': {
        const res = await fetchScanLogs(id)
        if (isCurrent()) {
          scanLogs.value = res.items
          ensurePolling()
        }
        break
      }
      case 'settings': {
        const res = await request<WebsiteCategoryListResponse>('/api/v1/website-categories', {
          query: { include_archived: false },
        })
        if (isCurrent()) categories.value = res.items
        break
      }
      case 'keyword_bank': {
        const res = await request<string[]>(`${root}/keyword-bank`)
        if (isCurrent()) {
          keywordBank.value = res
          keywordPage.value = 1
        }
        break
      }
    }
  }
  catch (err) {
    state.error = extractErrorMessage(err, 'Could not load this tab.')
  }
  finally {
    state.loading = false
  }
}

const activeSection = computed(() =>
  sections.find(section => section === activeTab.value),
)
const activeSectionState = computed(() =>
  activeSection.value ? sectionStates.get(activeSection.value) : undefined,
)

function loadActiveSection(force = false) {
  if (activeSection.value) void loadSection(activeSection.value, force)
}

async function loadAll() {
  const version = ++workspaceVersion
  stopPolling()
  stopIndexingPolling()
  sectionStates.clear()
  scanLogs.value = []
  loading.value = true
  errorMessage.value = null
  try {
    const siteData = await request<Website>(`/api/v1/websites/${websiteId.value}`)
    if (version !== workspaceVersion) return
    website.value = siteData
    syncSettingsForm(siteData)
    void refreshIndexingStatus()
    void loadSection('history')
    loadActiveSection()
  }
  catch (err) {
    if (version === workspaceVersion) {
      errorMessage.value = extractErrorMessage(err, 'Failed to load website details.')
    }
  }
  finally {
    if (version === workspaceVersion) loading.value = false
  }
}

async function triggerScan(scanMode: 'discover_only' | 'full' | 'incremental' | 'retry_failed' | 'resume') {
  triggeringScan.value = true
  try {
    const created = await request<ScanLog>(`/api/v1/websites/${websiteId.value}/scan`, {
      method: 'POST',
      body: { scan_mode: scanMode },
    })
    scanLogs.value = [created, ...scanLogs.value]
    ensurePolling()
    toast.add({
      title: `Scan #${created.id} queued (${scanMode.replace('_', ' ')})`,
      description: 'Discovery and extraction progress updates automatically below.',
      color: 'success',
    })
  }
  catch (err) {
    toast.add({
      title: 'Could not start scan',
      description: extractErrorMessage(err, 'An active scan may already be running.'),
      color: 'error',
    })
  }
  finally {
    triggeringScan.value = false
  }
}

async function runConnectivityTest() {
  testingConnectivity.value = true
  try {
    connectivityResult.value = await request<WebsiteConnectivity>(`/api/v1/websites/${websiteId.value}/test`, {
      method: 'POST',
    })
  }
  catch (err) {
    toast.add({
      title: 'Connectivity check failed',
      description: extractErrorMessage(err, 'Website connectivity check failed.'),
      color: 'error',
    })
  }
  finally {
    testingConnectivity.value = false
  }
}

async function runAutoDiscover(applyDetected: boolean) {
  discoveringSources.value = true
  try {
    discoverResult.value = await request<WebsiteDiscoverResult>(
      `/api/v1/websites/${websiteId.value}/discover`,
      { method: 'POST', query: { apply: applyDetected } },
    )
    if (applyDetected) {
      await loadAll()
      toast.add({ title: 'Discovery endpoints updated', color: 'success' })
    }
  }
  catch (err) {
    toast.add({
      title: 'Source discovery failed',
      description: extractErrorMessage(err, 'Could not auto-detect website sources.'),
      color: 'error',
    })
  }
  finally {
    discoveringSources.value = false
  }
}

async function toggleSource(src: WebsiteDiscoverySource) {
  try {
    const updated = await request<WebsiteDiscoverySource>(
      `/api/v1/websites/${websiteId.value}/sources/${src.id}`,
      { method: 'PATCH', body: { is_enabled: !src.is_enabled } },
    )
    sources.value = sources.value.map((s) => (s.id === src.id ? updated : s))
  }
  catch (err) {
    toast.add({
      title: 'Could not update source',
      description: extractErrorMessage(err, 'Failed to toggle discovery source.'),
      color: 'error',
    })
  }
}

async function addRule() {
  if (!ruleForm.value.pattern.trim()) {
    return
  }
  savingRule.value = true
  try {
    const created = await request<WebsiteUrlRule>(`/api/v1/websites/${websiteId.value}/rules`, {
      method: 'POST',
      body: {
        pattern: ruleForm.value.pattern.trim(),
        target_content_type: ruleForm.value.target_content_type,
        match_mode: ruleForm.value.match_mode,
        priority: Number(ruleForm.value.priority) || 50,
        notes: ruleForm.value.notes.trim() || null,
      },
    })
    urlRules.value = [...urlRules.value, created]
    ruleModalOpen.value = false
    toast.add({ title: 'URL classification rule added', color: 'success' })
  }
  catch (err) {
    toast.add({
      title: 'Invalid rule',
      description: extractErrorMessage(err, 'Could not save URL classification rule.'),
      color: 'error',
    })
  }
  finally {
    savingRule.value = false
  }
}

async function deleteRule(rule: WebsiteUrlRule) {
  try {
    await request(`/api/v1/websites/${websiteId.value}/rules/${rule.id}`, { method: 'DELETE' })
    urlRules.value = urlRules.value.filter((r) => r.id !== rule.id)
    toast.add({ title: 'Rule removed', color: 'neutral' })
  }
  catch (err) {
    toast.add({
      title: 'Delete failed',
      description: extractErrorMessage(err, 'Could not delete rule.'),
      color: 'error',
    })
  }
}

async function openInspectModal(scan: ScanLog) {
  inspectedScan.value = scan
  inspectModalOpen.value = true
  await loadInspectedItems()
}

async function loadInspectedItems() {
  if (!inspectedScan.value) {
    return
  }
  inspectLoading.value = true
  try {
    const query: Record<string, string | number | boolean> = { page: 1, page_size: 100 }
    if (inspectFilter.value === 'failures') {
      query.failures_only = true
    }
    else if (inspectFilter.value === 'pending') {
      query.status = 'pending'
    }
    const res = await request<ScanItemListResponse>(`/api/v1/scans/${inspectedScan.value.id}/items`, { query })
    inspectItems.value = res.items
  }
  catch (err) {
    toast.add({
      title: 'Could not load scan items',
      description: extractErrorMessage(err, 'Failed to inspect scan item log.'),
      color: 'error',
    })
  }
  finally {
    inspectLoading.value = false
  }
}

async function retryHistoryScan(scanId: number) {
  try {
    const created = await request<ScanLog>(`/api/v1/scans/${scanId}/retry`, { method: 'POST' })
    scanLogs.value = [created, ...scanLogs.value]
    ensurePolling()
    toast.add({ title: `Retry scan #${created.id} queued`, color: 'success' })
  }
  catch (err) {
    toast.add({
      title: 'Retry failed',
      description: extractErrorMessage(err, 'Could not retry scan.'),
      color: 'error',
    })
  }
}

async function handleLogoUpload(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) {
    return
  }
  uploadingLogo.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const updated = await request<Website>(`/api/v1/websites/${websiteId.value}/logo`, {
      method: 'POST',
      body: fd,
    })
    website.value = updated
    toast.add({ title: 'Website logo uploaded', color: 'success' })
    void uiStore.refreshGlobalSelectors()
  }
  catch (err) {
    toast.add({
      title: 'Logo upload failed',
      description: extractErrorMessage(err, 'Unsupported or oversized image file.'),
      color: 'error',
    })
  }
  finally {
    uploadingLogo.value = false
    target.value = ''
  }
}

async function handleGscServiceAccountUpload(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.json') || file.size > 64 * 1024) {
    toast.add({
      title: 'Invalid service-account file',
      description: 'Select a Google service-account .json file up to 64 KB.',
      color: 'error',
    })
    target.value = ''
    return
  }

  uploadingGscServiceAccount.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const updated = await request<Website>(
      `/api/v1/websites/${websiteId.value}/google-index-service-account`,
      { method: 'POST', body: fd },
    )
    website.value = updated
    toast.add({ title: 'Google indexing service account saved securely', color: 'success' })
  }
  catch (err) {
    toast.add({
      title: 'Service-account upload failed',
      description: extractErrorMessage(err, 'Could not save this Google service-account file.'),
      color: 'error',
    })
  }
  finally {
    uploadingGscServiceAccount.value = false
    target.value = ''
  }
}

async function removeGscServiceAccount() {
  removingGscServiceAccount.value = true
  try {
    website.value = await request<Website>(
      `/api/v1/websites/${websiteId.value}/google-index-service-account`,
      { method: 'DELETE' },
    )
    toast.add({ title: 'Google indexing service account removed', color: 'success' })
  }
  catch (err) {
    toast.add({
      title: 'Could not remove service account',
      description: extractErrorMessage(err, 'Could not remove the Google service-account key.'),
      color: 'error',
    })
  }
  finally {
    removingGscServiceAccount.value = false
  }
}

async function saveWebsiteSettings() {
  savingSettings.value = true
  try {
    const f = settingsForm.value
    const payload = {
      name: f.name.trim(),
      brand_name: f.brand_name.trim() || f.name.trim(),
      category_id: f.category_id ? Number(f.category_id) : null,
      clear_category: !f.category_id,
      domain: f.domain.trim(),
      website_type: f.website_type,
      discovery_method: f.discovery_method,
      single_source_only: f.single_source_only,
      status: f.status,
      primary_language: f.primary_language.trim() || 'en',
      secondary_languages: parseCsvOrLines(f.secondary_languages_text),
      target_country: f.target_country.trim() || null,
      target_audience: f.target_audience.trim() || null,
      tone: f.tone.trim() || null,
      brand_description: f.brand_description.trim() || null,
      target_keywords: parseCsvOrLines(f.target_keywords_text),
      keyword_bank: parseCsvOrLines(f.keyword_bank_text),
      restricted_keywords: parseCsvOrLines(f.restricted_keywords_text),
      default_hashtags: parseCsvOrLines(f.default_hashtags_text),
      default_cta: f.default_cta.trim() || null,
      writing_guidelines: f.writing_guidelines.trim() || null,
      ai_instructions: f.ai_instructions.trim() || null,
      rss_url: f.rss_url.trim() || null,
      sitemap_url: f.sitemap_url.trim() || null,
      llms_url: f.llms_url.trim() || null,
      api_endpoint: f.api_endpoint.trim() || null,
      gsc_property_url: f.gsc_property_url.trim() || null,
      excluded_url_patterns: parseCsvOrLines(f.excluded_url_patterns_text),
      scan_interval_minutes: Number(f.scan_interval_minutes) || 1440,
      crawl_batch_size: Number(f.crawl_batch_size) || 100,
      crawl_max_urls_per_run: Number(f.crawl_max_urls_per_run) || 1000,
      auto_scan: f.auto_scan,
    }
    const updated = await request<Website>(`/api/v1/websites/${websiteId.value}`, {
      method: 'PATCH',
      body: payload,
    })
    website.value = updated
    gscAccountTestResult.value = null
    syncSettingsForm(updated)
    toast.add({ title: 'Website & brand settings saved', color: 'success' })
    sectionStates.delete('scanner')
    sectionStates.delete('keyword_bank')
    await uiStore.refreshGlobalSelectors()
  }
  catch (err) {
    toast.add({
      title: 'Save failed',
      description: extractErrorMessage(err, 'Could not update website configuration.'),
      color: 'error',
    })
  }
  finally {
    savingSettings.value = false
  }
}

watch(contentTabFilter, () => {
  if (website.value && !loading.value) void loadSection('content', true)
})

watch(activeTab, () => {
  if (website.value && !loading.value) loadActiveSection()
})

watch(keywordSearch, () => {
  keywordPage.value = 1
})

watch(inspectFilter, () => {
  void loadInspectedItems()
})

watch(websiteId, () => {
  stopIndexingPolling()
  indexingStatus.value = {
    state: 'idle',
    progress: 0,
    total: 0,
    processed: 0,
    indexed: 0,
    skipped: 0,
    ready: 0,
    failed: 0,
  }
  website.value = null
  contentTabFilter.value = 'all'
  keywordSearch.value = ''
  keywordBank.value = []
  void loadAll()
})

onMounted(() => {
  const qTab = String(route.query.tab || '').trim().toLowerCase()
  if (qTab === 'social-profiles' || qTab === 'social_profiles') {
    activeTab.value = 'social_profiles'
  }
  else if (qTab === 'ai-settings' || qTab === 'ai_settings') {
    activeTab.value = 'ai_settings'
  }
  else if (qTab === 'keyword-bank' || qTab === 'keyword_bank') {
    activeTab.value = 'keyword_bank'
  }
  void loadAll()
})

onUnmounted(() => {
  stopPolling()
  stopIndexingPolling()
  workspaceVersion++
  sectionStates.clear()
})
</script>

<template>
  <div class="space-y-6">
    <!-- Top Header -->
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div class="flex items-start gap-3">
        <UButton
          to="/websites"
          color="neutral"
          variant="outline"
          size="xs"
        >
          <ArrowLeft class="mr-1 h-3.5 w-3.5" />
          Back
        </UButton>

        <div
          v-if="website?.logo_url"
          class="h-11 w-11 shrink-0 overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-700"
        >
          <img
            :src="website.logo_url"
            :alt="website.brand_name"
            class="h-full w-full object-contain"
          >
        </div>

        <div>
          <div class="flex flex-wrap items-center gap-2">
            <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">
              {{ website?.name || `Website #${websiteId}` }}
            </h1>
            <UBadge
              v-if="website?.category_name"
              color="neutral"
              variant="subtle"
              size="xs"
            >
              {{ website.category_name }}
            </UBadge>
            <UBadge
              v-if="website"
              color="info"
              variant="subtle"
              size="xs"
            >
              {{ website.website_type }}
            </UBadge>
          </div>
          <p
            v-if="website"
            class="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400"
          >
            <span>Brand: <strong class="text-slate-700 dark:text-slate-200">{{ website.brand_name }}</strong></span>
            <span>·</span>
            <span>{{ website.primary_language }}{{ website.target_country ? ` · ${website.target_country}` : '' }}</span>
            <span>·</span>
            <a
              :href="`https://${website.domain}`"
              target="_blank"
              rel="noopener noreferrer"
              class="inline-flex items-center gap-1 font-mono text-teal-600 hover:underline dark:text-teal-400"
            >
              {{ website.domain }}
              <ExternalLink class="h-3 w-3" />
            </a>
          </p>
        </div>
      </div>

      <!-- 5 Explicit Scan Actions -->
      <div
        v-if="website"
        class="flex flex-wrap items-center gap-2"
      >
        <UButton
          color="neutral"
          variant="outline"
          size="xs"
          :disabled="triggeringScan || Boolean(activeScan)"
          @click="triggerScan('discover_only')"
        >
          <SearchCheck class="mr-1 h-3.5 w-3.5" />
          Discover URLs
        </UButton>
        <UButton
          color="primary"
          size="xs"
          :disabled="triggeringScan || Boolean(activeScan)"
          @click="triggerScan('full')"
        >
          <Play class="mr-1 h-3.5 w-3.5" />
          Full Scan
        </UButton>
        <UButton
          color="neutral"
          variant="outline"
          size="xs"
          :disabled="triggeringScan || Boolean(activeScan)"
          @click="triggerScan('incremental')"
        >
          <RefreshCw class="mr-1 h-3.5 w-3.5" />
          Check New Content
        </UButton>
        <UButton
          v-if="website.content_counts.failed > 0"
          color="error"
          variant="subtle"
          size="xs"
          :disabled="triggeringScan || Boolean(activeScan)"
          @click="triggerScan('retry_failed')"
        >
          <RotateCcw class="mr-1 h-3.5 w-3.5" />
          Retry Failed URLs ({{ website.content_counts.failed }})
        </UButton>
        <UButton
          v-if="canResumeScan"
          color="warning"
          size="xs"
          :disabled="triggeringScan || Boolean(activeScan)"
          @click="triggerScan('resume')"
        >
          <Play class="mr-1 h-3.5 w-3.5" />
          Resume Incomplete Scan ({{ website.content_counts.pending }})
        </UButton>
      </div>
    </div>

    <!-- Live Scan Progress Banner -->
    <div
      v-if="activeScan"
      class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-teal-200 bg-teal-50/70 px-4 py-3 text-xs dark:border-teal-900 dark:bg-teal-950/40"
    >
      <div class="space-y-0.5">
        <p class="font-semibold text-teal-900 dark:text-teal-200">
          Scan #{{ activeScan.id }} running ({{ activeScan.scan_mode }}) — {{ activeScan.status }}
        </p>
        <p class="font-mono text-[11px] text-teal-700 dark:text-teal-300">
          {{ activeScan.current_source || 'initializing' }}: {{ activeScan.current_url || 'Discovering endpoints...' }}
        </p>
      </div>
      <div class="font-mono text-xs text-teal-800 dark:text-teal-200">
        Found: {{ activeScan.urls_found }} · Extracted: {{ activeScan.articles_processed }} · Pending: {{ activeScan.urls_pending_extraction }}
      </div>
    </div>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="Could not load website workspace"
      :message="errorMessage"
      retryable
      @retry="loadAll()"
    />

    <USkeleton
      v-else-if="loading"
      class="h-64 w-full"
    />

    <template v-else-if="website">
      <div class="flex flex-wrap gap-1 border-b border-slate-200 dark:border-slate-800">
        <button
          v-for="tab in [
            { id: 'overview', label: 'Overview' },
            { id: 'content', label: `Content (${website.content_counts.total_discovered})` },
            { id: 'keyword_bank', label: 'Keyword Bank' },
            { id: 'scanner', label: 'Scanner & URL Rules' },
            { id: 'history', label: `Scan History (${scanLogs.length})` },
            { id: 'social_profiles', label: 'Social Profiles' },
            { id: 'ai_settings', label: 'AI Settings' },
            { id: 'settings', label: 'Settings & Brand Profile' },
          ]"
          :key="tab.id"
          type="button"
          :class="[
            'border-b-2 px-4 py-2 text-xs font-medium transition-colors',
            activeTab === tab.id
              ? 'border-teal-600 text-teal-700 dark:text-teal-300'
              : 'border-transparent text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100',
          ]"
          @click="activeTab = tab.id as typeof activeTab"
        >
          {{ tab.label }}
        </button>
      </div>

      <AppErrorState
        v-if="activeTab !== 'content' && activeSectionState?.error"
        title="Could not load this tab"
        :message="activeSectionState.error"
        retryable
        @retry="loadActiveSection(true)"
      />
      <USkeleton
        v-else-if="activeTab !== 'content' && activeSectionState?.loading"
        class="h-48 w-full"
      />

      <!-- TAB 1: OVERVIEW -->
      <div
        v-else-if="activeTab === 'overview'"
        class="space-y-6"
      >
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-6">
          <div class="rounded-lg border border-slate-200 bg-white p-3.5 dark:border-slate-800 dark:bg-slate-900">
            <p class="text-[11px] text-slate-500">Discovered URLs</p>
            <p class="mt-1 text-lg font-semibold">{{ website.content_counts.total_discovered }}</p>
          </div>
          <div class="rounded-lg border border-slate-200 bg-white p-3.5 dark:border-slate-800 dark:bg-slate-900">
            <p class="text-[11px] text-slate-500">Homepage</p>
            <p class="mt-1 text-lg font-semibold">{{ website.content_counts.homepage }}</p>
          </div>
          <div class="rounded-lg border border-slate-200 bg-white p-3.5 dark:border-slate-800 dark:bg-slate-900">
            <p class="text-[11px] text-slate-500">Pages / Games</p>
            <p class="mt-1 text-lg font-semibold">
              {{ website.content_counts.page }} / {{ website.content_counts.game_page ?? 0 }}
            </p>
          </div>
          <div class="rounded-lg border border-slate-200 bg-white p-3.5 dark:border-slate-800 dark:bg-slate-900">
            <p class="text-[11px] text-slate-500">Blog Indexes</p>
            <p class="mt-1 text-lg font-semibold">{{ website.content_counts.blog_index }}</p>
          </div>
          <div class="rounded-lg border border-slate-200 bg-white p-3.5 dark:border-slate-800 dark:bg-slate-900">
            <p class="text-[11px] text-slate-500">Blog Posts</p>
            <p class="mt-1 text-lg font-semibold">{{ website.content_counts.blog_post }}</p>
          </div>
          <div class="rounded-lg border border-slate-200 bg-white p-3.5 dark:border-slate-800 dark:bg-slate-900">
            <p class="text-[11px] text-slate-500">Pending / Failed</p>
            <p class="mt-1 text-lg font-semibold">
              {{ website.content_counts.pending }} /
              <span :class="website.content_counts.failed > 0 ? 'text-rose-600' : ''">{{ website.content_counts.failed }}</span>
            </p>
          </div>
        </div>

        <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div class="rounded-lg border border-slate-200 bg-white p-4 text-xs dark:border-slate-800 dark:bg-slate-900">
            <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Brand Identity & Writing Guidance
            </h2>
            <dl class="mt-3 space-y-2">
              <div class="flex justify-between gap-2">
                <dt class="text-slate-500">Brand Name:</dt>
                <dd class="font-medium">{{ website.brand_name }}</dd>
              </div>
              <div class="flex justify-between gap-2">
                <dt class="text-slate-500">Tone / Audience:</dt>
                <dd>{{ website.tone || 'Default' }} · {{ website.target_audience || 'General' }}</dd>
              </div>
              <div class="flex justify-between gap-2">
                <dt class="text-slate-500">Keywords:</dt>
                <dd class="text-right">{{ website.target_keywords.join(', ') || 'None configured' }}</dd>
              </div>
              <div class="flex justify-between gap-2">
                <dt class="text-slate-500">Default Hashtags:</dt>
                <dd class="text-right">{{ website.default_hashtags.join(' ') || 'None configured' }}</dd>
              </div>
            </dl>
            <p
              v-if="website.writing_guidelines"
              class="mt-3 rounded bg-slate-50 p-2.5 text-slate-600 dark:bg-slate-950 dark:text-slate-300"
            >
              {{ website.writing_guidelines }}
            </p>
          </div>

          <div class="rounded-lg border border-slate-200 bg-white p-4 text-xs dark:border-slate-800 dark:bg-slate-900">
            <div class="flex items-center justify-between">
              <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
                Diagnostics & Source Probe
              </h2>
              <div class="flex gap-2">
                <UButton
                  size="xs"
                  color="neutral"
                  variant="outline"
                  :loading="testingConnectivity"
                  @click="runConnectivityTest"
                >
                  <Activity class="mr-1 h-3.5 w-3.5" />
                  Test Connectivity
                </UButton>
                <UButton
                  size="xs"
                  color="neutral"
                  variant="outline"
                  :loading="discoveringSources"
                  @click="runAutoDiscover(true)"
                >
                  <Compass class="mr-1 h-3.5 w-3.5" />
                  Detect Sources
                </UButton>
              </div>
            </div>

            <div class="mt-3 space-y-2 text-slate-600 dark:text-slate-300">
              <p>Last scanned: {{ formatDateTime(website.last_scanned_at) }}</p>
              <p>Next auto-scan: {{ formatDateTime(website.next_scan_at) }}</p>
              <p>Batching: {{ website.crawl_batch_size }} URLs/batch · max {{ website.crawl_max_urls_per_run }} URLs/run</p>
            </div>

            <div
              v-if="connectivityResult"
              class="mt-3 rounded border border-slate-200 bg-slate-50 p-2.5 dark:border-slate-800 dark:bg-slate-950"
            >
              <p class="flex items-center gap-1.5 font-medium">
                <CheckCircle class="h-3.5 w-3.5 text-teal-600" />
                {{ connectivityResult.reachable ? `Reachable (HTTP ${connectivityResult.status_code})` : 'Unreachable' }}
                <span v-if="connectivityResult.detected_website_type">· Detected {{ connectivityResult.detected_website_type }}</span>
              </p>
              <p
                v-if="connectivityResult.error"
                class="mt-1 text-rose-600"
              >
                {{ connectivityResult.error }}
              </p>
            </div>

            <div
              v-if="discoverResult"
              class="mt-2 rounded border border-slate-200 bg-slate-50 p-2.5 dark:border-slate-800 dark:bg-slate-950"
            >
              <p class="font-medium">
                Recommended: {{ discoverResult.recommended_method }} · Sitemaps: {{ discoverResult.sitemap_urls.length }} · RSS: {{ discoverResult.rss_urls.length }}
              </p>
            </div>
          </div>
        </div>
      </div>

      <!-- TAB 2: CONTENT -->
      <div
        v-else-if="activeTab === 'content'"
        class="space-y-4"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="flex flex-wrap gap-1.5">
            <UButton
              v-for="t in [
                { key: 'all', label: 'All' },
                { key: 'homepage', label: 'Homepage' },
                { key: 'pages', label: 'Pages' },
                { key: 'game_pages', label: 'Game Pages' },
                { key: 'blog_posts', label: 'Blog Posts' },
                { key: 'blog_indexes', label: 'Blog Indexes' },
                { key: 'other', label: 'Other' },
                { key: 'failed', label: 'Failed' },
              ]"
              :key="t.key"
              size="xs"
              :color="contentTabFilter === t.key ? 'primary' : 'neutral'"
              :variant="contentTabFilter === t.key ? 'solid' : 'outline'"
              @click="contentTabFilter = t.key"
            >
              {{ t.label }}
            </UButton>
          </div>

          <UButton
            :to="`/content-library?website_id=${website.id}`"
            color="neutral"
            variant="outline"
            size="xs"
          >
            Open Full Content Library
          </UButton>
        </div>

        <AppErrorState
          v-if="activeSectionState?.error"
          title="Could not load content"
          :message="activeSectionState.error"
          retryable
          @retry="loadActiveSection(true)"
        />
        <USkeleton v-else-if="activeSectionState?.loading" class="h-48 w-full" />
        <div v-else class="overflow-x-auto rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
            <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
              <tr>
                <th class="px-4 py-2.5 font-medium">Title & URL</th>
                <th class="px-4 py-2.5 font-medium">Type</th>
                <th class="px-4 py-2.5 font-medium">Extraction</th>
                <th class="px-4 py-2.5 font-medium">Sources</th>
                <th class="px-4 py-2.5 font-medium">Words</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
              <tr
                v-for="item in websiteContents"
                :key="item.id"
                class="hover:bg-slate-50/70 dark:hover:bg-slate-800/40"
              >
                <td class="px-4 py-2.5">
                  <NuxtLink
                    :to="`/content-library/${item.id}`"
                    class="font-medium text-teal-700 hover:underline dark:text-teal-300"
                  >
                    {{ item.title }}
                  </NuxtLink>
                  <p class="font-mono text-[11px] text-slate-500">{{ item.canonical_url }}</p>
                </td>
                <td class="px-4 py-2.5">
                  <UBadge
                    :color="getContentTypeMeta(item.content_type).color"
                    variant="subtle"
                    size="xs"
                  >
                    {{ getContentTypeMeta(item.content_type).label }}
                  </UBadge>
                </td>
                <td class="px-4 py-2.5">
                  <HealthStatusBadge
                    :status="item.extraction_status === 'extracted' ? 'ok' : item.extraction_status === 'pending' ? 'warning' : 'error'"
                    :label="item.extraction_status"
                  />
                </td>
                <td class="px-4 py-2.5 font-mono text-[11px] text-slate-500">
                  {{ item.discovery_sources.join(', ') }}
                </td>
                <td class="px-4 py-2.5 font-mono">{{ item.word_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <section
        v-else-if="activeTab === 'keyword_bank'"
        class="space-y-4 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
      >
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 class="text-sm font-semibold">Keyword Bank</h2>
            <p class="text-xs text-slate-500 dark:text-slate-400">
              Keywords from this website’s content and manually added entries.
            </p>
          </div>
          <UInput
            v-model="keywordSearch"
            type="search"
            aria-label="Search keyword bank"
            placeholder="Search keywords"
            class="w-full sm:w-64"
          />
        </div>
        <p aria-live="polite" class="text-xs text-slate-500 dark:text-slate-400">
          {{ filteredKeywords.length.toLocaleString() }} of {{ keywordBank.length.toLocaleString() }} keywords
        </p>
        <div v-if="visibleKeywords.length" class="flex flex-wrap gap-2">
          <UBadge
            v-for="keyword in visibleKeywords"
            :key="keyword"
            color="neutral"
            variant="subtle"
            class="max-w-full whitespace-normal break-words rounded-full px-2.5"
          >
            {{ keyword }}
          </UBadge>
        </div>
        <p v-else class="text-sm text-slate-500 dark:text-slate-400">
          {{ keywordBank.length ? 'No keywords match your search.' : 'No keywords yet. They’ll appear after content extraction or when you add them in Settings.' }}
        </p>
        <UPagination
          v-if="filteredKeywords.length > keywordPageSize"
          v-model:page="keywordPage"
          :total="filteredKeywords.length"
          :items-per-page="keywordPageSize"
          size="sm"
        />
      </section>

      <!-- TAB 3: SCANNER & URL RULES -->
      <div
        v-else-if="activeTab === 'scanner'"
        class="space-y-6"
      >
        <!-- Discovery Sources Endpoint Health -->
        <section class="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
            <div>
              <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
                Discovery Endpoints (Isolated Per-Source Caching)
              </h2>
              <p class="text-xs text-slate-500">
                A 304 Not Modified on one endpoint preserves existing URLs without blocking sitemaps, feeds, or homepage links.
              </p>
            </div>
            <UButton
              size="xs"
              color="neutral"
              variant="outline"
              :loading="discoveringSources"
              @click="runAutoDiscover(true)"
            >
              Re-Detect Sources
            </UButton>
          </div>

          <div class="overflow-x-auto">
            <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
              <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
                <tr>
                  <th class="px-4 py-2.5 font-medium">Type</th>
                  <th class="px-4 py-2.5 font-medium">Endpoint URL</th>
                  <th class="px-4 py-2.5 font-medium">Last Status</th>
                  <th class="px-4 py-2.5 font-medium">URLs Found</th>
                  <th class="px-4 py-2.5 font-medium">ETag / Cache</th>
                  <th class="px-4 py-2.5 font-medium">Enabled</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
                <tr
                  v-for="src in sources"
                  :key="src.id"
                >
                  <td class="px-4 py-2.5 font-mono">{{ src.source_type }}</td>
                  <td class="max-w-xs truncate px-4 py-2.5 font-mono text-[11px]">
                    {{ src.endpoint_url }}
                    <p
                      v-if="src.last_error"
                      class="text-rose-600"
                    >
                      {{ src.last_error }}
                    </p>
                  </td>
                  <td class="px-4 py-2.5 font-mono">{{ src.last_status_code ?? '—' }}</td>
                  <td class="px-4 py-2.5 font-mono">{{ src.last_urls_found }}</td>
                  <td class="px-4 py-2.5 font-mono text-[11px] text-slate-500">
                    {{ src.etag ? 'ETag saved' : (src.last_modified_header ? 'Last-Mod saved' : 'None') }}
                  </td>
                  <td class="px-4 py-2.5">
                    <USwitch
                      :model-value="src.is_enabled"
                      @update:model-value="toggleSource(src)"
                    />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- URL Classification Rules -->
        <section class="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
            <div>
              <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
                Custom URL Classification Rules
              </h2>
              <p class="text-xs text-slate-500">
                Override deterministic path rules per website (lower priority number runs first).
              </p>
            </div>
            <UButton
              size="xs"
              color="primary"
              @click="ruleModalOpen = true"
            >
              <Plus class="mr-1 h-3.5 w-3.5" />
              Add URL Rule
            </UButton>
          </div>

          <div
            v-if="urlRules.length === 0"
            class="p-4 text-xs text-slate-500"
          >
            Using default deterministic URL classification (`/` homepage, `/blog/` blog index, `/blog/*` blog post, `/category/*`, `/tag/*`, `/author/*`, others page).
          </div>

          <div
            v-else
            class="overflow-x-auto"
          >
            <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
              <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
                <tr>
                  <th class="px-4 py-2.5 font-medium">Priority</th>
                  <th class="px-4 py-2.5 font-medium">Pattern</th>
                  <th class="px-4 py-2.5 font-medium">Mode</th>
                  <th class="px-4 py-2.5 font-medium">Target Type</th>
                  <th class="px-4 py-2.5 font-medium">Notes</th>
                  <th class="px-4 py-2.5 text-right font-medium">Delete</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
                <tr
                  v-for="rule in urlRules"
                  :key="rule.id"
                >
                  <td class="px-4 py-2.5 font-mono">{{ rule.priority }}</td>
                  <td class="px-4 py-2.5 font-mono font-semibold">{{ rule.pattern }}</td>
                  <td class="px-4 py-2.5 font-mono">{{ rule.match_mode }}</td>
                  <td class="px-4 py-2.5">
                    <UBadge
                      :color="getContentTypeMeta(rule.target_content_type).color"
                      variant="subtle"
                      size="xs"
                    >
                      {{ rule.target_content_type }}
                    </UBadge>
                  </td>
                  <td class="px-4 py-2.5 text-slate-500">{{ rule.notes || '—' }}</td>
                  <td class="px-4 py-2.5 text-right">
                    <UButton
                      color="error"
                      variant="ghost"
                      size="xs"
                      @click="deleteRule(rule)"
                    >
                      <Trash2 class="h-3.5 w-3.5" />
                    </UButton>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <!-- TAB 4: SCAN HISTORY -->
      <div
        v-else-if="activeTab === 'history'"
        class="overflow-x-auto rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
      >
        <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
          <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
            <tr>
              <th class="px-4 py-2.5 font-medium">Scan #</th>
              <th class="px-4 py-2.5 font-medium">Mode & Method</th>
              <th class="px-4 py-2.5 font-medium">Status</th>
              <th class="px-4 py-2.5 font-medium">Found / Extracted / Pending</th>
              <th class="px-4 py-2.5 font-medium">New / Upd / Fail / Excl</th>
              <th class="px-4 py-2.5 font-medium">Created</th>
              <th class="px-4 py-2.5 text-right font-medium">Diagnostics</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
            <tr
              v-for="scan in scanLogs"
              :key="scan.id"
              class="hover:bg-slate-50/70 dark:hover:bg-slate-800/40"
            >
              <td class="px-4 py-2.5 font-mono">#{{ scan.id }}</td>
              <td class="px-4 py-2.5 font-mono text-[11px]">{{ scan.scan_mode }} · {{ scan.scan_method }}</td>
              <td class="px-4 py-2.5">
                <HealthStatusBadge
                  :status="scan.status === 'completed' ? 'ok' : ['partially_completed', 'incomplete', 'paused'].includes(scan.status) ? 'warning' : scan.status"
                  :label="scan.status"
                />
                <p
                  v-if="scan.error_message"
                  class="mt-1 max-w-xs truncate text-[11px] text-slate-500"
                  :title="scan.error_message"
                >
                  {{ scan.error_message }}
                </p>
              </td>
              <td class="px-4 py-2.5 font-mono">
                {{ scan.urls_found }} / {{ scan.articles_processed }} / {{ scan.urls_pending_extraction }}
              </td>
              <td class="px-4 py-2.5 font-mono text-[11px]">
                +{{ scan.new_articles }} / ~{{ scan.updated_articles }} / !{{ scan.failed_articles }} / -{{ scan.excluded_count }}
              </td>
              <td class="px-4 py-2.5 whitespace-nowrap text-slate-500">
                {{ formatDateTime(scan.created_at) }}
              </td>
              <td class="px-4 py-2.5 text-right">
                <div class="flex justify-end gap-1.5">
                  <UButton
                    size="xs"
                    color="neutral"
                    variant="outline"
                    @click="openInspectModal(scan)"
                  >
                    Inspect Items
                  </UButton>
                  <UButton
                    v-if="['failed', 'partially_completed', 'incomplete', 'paused'].includes(scan.status)"
                    size="xs"
                    color="primary"
                    variant="subtle"
                    @click="retryHistoryScan(scan.id)"
                  >
                    Retry
                  </UButton>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- TAB 5: SOCIAL PROFILES -->
      <WebsiteSocialProfilesTab
        v-else-if="activeTab === 'social_profiles'"
        :website-id="website.id"
        :website-name="website.name"
        :default-language="website.primary_language"
        :default-tone="website.tone"
        :default-cta="website.default_cta"
        :default-hashtags="website.default_hashtags"
      />

      <!-- TAB 6: AI SETTINGS & KNOWLEDGE PROFILE -->
      <WebsiteAiSettingsTab
        v-else-if="activeTab === 'ai_settings'"
        :website="website"
        @updated="website = $event; syncSettingsForm($event)"
      />

      <!-- TAB 7: SETTINGS & BRAND PROFILE -->
      <form
        v-else
        class="space-y-6 rounded-lg border border-slate-200 bg-white p-5 text-xs dark:border-slate-800 dark:bg-slate-900"
        @submit.prevent="saveWebsiteSettings"
      >
        <div class="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 pb-4 dark:border-slate-800">
          <div class="flex items-center gap-3">
            <label class="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800">
              <ImagePlus class="h-3.5 w-3.5" />
              <span>{{ uploadingLogo ? 'Uploading...' : 'Upload Brand Logo' }}</span>
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                class="hidden"
                :disabled="uploadingLogo"
                @change="handleLogoUpload"
              >
            </label>
            <span
              v-if="website.logo_url"
              class="text-slate-500"
            >
              Logo saved
            </span>
          </div>

          <UButton
            type="submit"
            color="primary"
            size="sm"
            :loading="savingSettings"
          >
            <Save class="mr-1.5 h-3.5 w-3.5" />
            Save All Changes
          </UButton>
        </div>

        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div>
            <label class="mb-1 block font-medium">Website Name *</label>
            <UInput v-model="settingsForm.name" required />
          </div>
          <div>
            <label class="mb-1 block font-medium">Brand Name *</label>
            <UInput v-model="settingsForm.brand_name" required />
          </div>
          <div>
            <label class="mb-1 block font-medium">Domain *</label>
            <UInput v-model="settingsForm.domain" required />
          </div>
          <div>
            <label class="mb-1 block font-medium">Website Category</label>
            <select
              v-model="settingsForm.category_id"
              class="h-9 w-full rounded-md border border-slate-200 bg-white px-2.5 dark:border-slate-700 dark:bg-slate-950"
            >
              <option value="">Uncategorized</option>
              <option
                v-for="cat in categories"
                :key="cat.id"
                :value="String(cat.id)"
              >
                {{ cat.name }}
              </option>
            </select>
          </div>
          <div>
            <label class="mb-1 block font-medium">Technology</label>
            <select
              v-model="settingsForm.website_type"
              class="h-9 w-full rounded-md border border-slate-200 bg-white px-2.5 dark:border-slate-700 dark:bg-slate-950"
            >
              <option
                v-for="opt in WEBSITE_TECHNOLOGY_OPTIONS"
                :key="opt.value"
                :value="opt.value"
              >
                {{ opt.label }}
              </option>
            </select>
          </div>
          <div>
            <label class="mb-1 block font-medium">Status</label>
            <select
              v-model="settingsForm.status"
              class="h-9 w-full rounded-md border border-slate-200 bg-white px-2.5 dark:border-slate-700 dark:bg-slate-950"
            >
              <option value="active">Active</option>
              <option value="paused">Paused</option>
              <option value="archived">Archived</option>
            </select>
          </div>
          <div>
            <label class="mb-1 block font-medium">Primary Language *</label>
            <UInput v-model="settingsForm.primary_language" required />
          </div>
          <div>
            <label class="mb-1 block font-medium">Target Country</label>
            <UInput v-model="settingsForm.target_country" />
          </div>
          <div>
            <label class="mb-1 block font-medium">Target Audience</label>
            <UInput v-model="settingsForm.target_audience" />
          </div>
          <div>
            <label class="mb-1 block font-medium">Tone</label>
            <UInput v-model="settingsForm.tone" />
          </div>
          <div>
            <label class="mb-1 block font-medium">Target Keywords</label>
            <UInput v-model="settingsForm.target_keywords_text" placeholder="comma-separated" />
          </div>
          <div class="md:col-span-2">
            <label class="mb-1 block font-medium">Manual Keyword Bank Entries</label>
            <UTextarea
              v-model="settingsForm.keyword_bank_text"
              :rows="3"
              placeholder="Reference keywords for new blogs/articles (comma or newline separated)"
            />
            <p class="mt-1 text-xs text-slate-500">These appear in the Keyword Bank alongside keywords from this website’s content.</p>
          </div>
          <div>
            <label class="mb-1 block font-medium">Default Hashtags</label>
            <UInput v-model="settingsForm.default_hashtags_text" placeholder="#Tag1, #Tag2" />
          </div>
          <div>
            <label class="mb-1 block font-medium">Discovery Mode</label>
            <select
              v-model="settingsForm.discovery_method"
              class="h-9 w-full rounded-md border border-slate-200 bg-white px-2.5 dark:border-slate-700 dark:bg-slate-950"
            >
              <option
                v-for="opt in DISCOVERY_METHOD_OPTIONS"
                :key="opt.value"
                :value="opt.value"
              >
                {{ opt.label }}
              </option>
            </select>
          </div>
          <div>
            <label class="mb-1 block font-medium">Batch Size (URLs)</label>
            <UInput v-model="settingsForm.crawl_batch_size" type="number" />
          </div>
          <div>
            <label class="mb-1 block font-medium">Max URLs Per Run</label>
            <UInput v-model="settingsForm.crawl_max_urls_per_run" type="number" />
          </div>
          <div>
            <label class="mb-1 block font-medium">Sitemap URL</label>
            <UInput v-model="settingsForm.sitemap_url" />
          </div>
          <div>
            <label class="mb-1 block font-medium">RSS URL</label>
            <UInput v-model="settingsForm.rss_url" />
          </div>
          <div>
            <label class="mb-1 block font-medium">Scan Interval (minutes)</label>
            <UInput v-model="settingsForm.scan_interval_minutes" type="number" />
          </div>
        </div>

        <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div>
            <label class="mb-1 block font-medium">Writing Guidelines</label>
            <textarea
              v-model="settingsForm.writing_guidelines"
              rows="3"
              class="w-full rounded-md border border-slate-200 p-2 dark:border-slate-700 dark:bg-slate-950"
            />
          </div>
          <div>
            <label class="mb-1 block font-medium">AI Instructions</label>
            <textarea
              v-model="settingsForm.ai_instructions"
              rows="3"
              class="w-full rounded-md border border-slate-200 p-2 dark:border-slate-700 dark:bg-slate-950"
            />
          </div>
        </div>

        <div>
          <label class="mb-1 block font-medium">Excluded URL Patterns (one per line)</label>
          <textarea
            v-model="settingsForm.excluded_url_patterns_text"
            rows="3"
            class="w-full rounded-md border border-slate-200 p-2 font-mono text-[11px] dark:border-slate-700 dark:bg-slate-950"
          />
        </div>

        <div class="flex flex-wrap gap-6">
          <label class="flex items-center gap-2">
            <USwitch v-model="settingsForm.auto_scan" />
            <span>Enable Scheduled Auto-Scan</span>
          </label>
          <label class="flex items-center gap-2">
            <USwitch v-model="settingsForm.single_source_only" />
            <span>Single-Source Manual Override Mode</span>
          </label>
        </div>

        <section class="space-y-4 rounded-lg border border-slate-200 p-4 dark:border-slate-700">
          <div>
            <h3 class="text-sm font-semibold">Google Index Checker — Articles &amp; Posts</h3>
            <p class="mt-1 text-slate-500">
              Configure the authorized Search Console property and service account used to inspect this website's article and post URLs.
              Credentials are encrypted before storage. This uses URL Inspection, not the restricted Indexing API.
            </p>
          </div>
          <div class="flex flex-wrap items-center gap-3">
            <UButton
              type="button"
              color="primary"
              size="sm"
              :loading="indexingInProgress"
              :disabled="indexingInProgress || !indexingSetupVerified"
              :aria-label="indexingStatus.state === 'completed' ? 'Run the next eligible indexing batch' : undefined"
              @click="runIndexing"
            >
              {{ indexingButtonLabel }}
            </UButton>
            <span
              v-if="indexingStatus.state === 'completed'"
              class="text-slate-500"
            >
              Last batch complete. Run again to check the next eligible URLs.
            </span>
            <span
              v-if="indexingStatus.state === 'deferred'"
              class="text-amber-700 dark:text-amber-300"
            >
              Resource Guardian deferred this job. Select Deferred to resume.
            </span>
          </div>
          <p
            v-if="indexingStatusError"
            class="text-rose-600 dark:text-rose-400"
          >
            {{ indexingStatusError }}
          </p>
          <div class="max-w-2xl">
            <label class="mb-1 block font-medium">Search Console Property</label>
            <UInput
              v-model="settingsForm.gsc_property_url"
              placeholder="sc-domain:example.com or https://example.com/"
            />
            <p class="mt-1 text-[11px] text-slate-500">
              Enter a property the uploaded service account can access, then select Save All Changes.
            </p>
          </div>
          <div class="flex flex-wrap items-center gap-3">
            <UButton
              type="button"
              color="neutral"
              variant="outline"
              size="sm"
              :loading="testingGscAccount"
              :disabled="testingGscAccount || !canTestGscAccount || indexingInProgress"
              @click="testGscAccount"
            >
              Test Account
            </UButton>
            <label class="inline-flex cursor-pointer items-center gap-2 rounded-md border border-slate-200 px-3 py-2 font-medium hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800">
              <span>{{ uploadingGscServiceAccount ? 'Uploading...' : 'Upload Service Account JSON' }}</span>
              <input
                type="file"
                accept=".json,application/json"
                class="hidden"
                :disabled="uploadingGscServiceAccount"
                @change="handleGscServiceAccountUpload"
              >
            </label>
            <UBadge
              :color="website.gsc_service_account_configured ? 'success' : 'neutral'"
              variant="subtle"
            >
              {{ website.gsc_service_account_configured ? 'Service account uploaded' : 'No service account uploaded' }}
            </UBadge>
            <UButton
              v-if="website.gsc_service_account_configured"
              type="button"
              color="error"
              variant="outline"
              size="xs"
              :loading="removingGscServiceAccount"
              @click="removeGscServiceAccount"
            >
              <Trash2 class="mr-1 h-3.5 w-3.5" />
              Remove Key
            </UButton>
          </div>
          <p
            v-if="gscAccountTestResult && indexingSetupVerified"
            class="text-emerald-700 dark:text-emerald-300"
          >
            Verified {{ gscAccountTestResult.account_email }} for {{ gscAccountTestResult.property_url }}.
          </p>
          <p
            v-else-if="indexingSetupVerified && website.gsc_property_verified_at"
            class="text-emerald-700 dark:text-emerald-300"
          >
            Search Console access verified {{ formatDateTime(website.gsc_property_verified_at) }}.
          </p>
          <p
            v-else-if="!website.gsc_service_account_configured"
            class="text-amber-700 dark:text-amber-300"
          >
            Upload a service-account key before testing access.
          </p>
          <p
            v-else-if="!gscPropertySaved"
            class="text-amber-700 dark:text-amber-300"
          >
            Save the Search Console property before testing access.
          </p>
          <p
            v-else
            class="text-amber-700 dark:text-amber-300"
          >
            Test the account before running indexing. The test only lists properties available to the account.
          </p>
          <p class="text-[11px] text-slate-500">
            Add the service account's email as a user of the matching Search Console property before running indexing.
          </p>
        </section>
      </form>
    </template>

    <!-- Add URL Rule Modal -->
    <UModal
      v-model:open="ruleModalOpen"
      title="Add URL Classification Rule"
    >
      <template #body>
        <form
          class="space-y-3 text-xs"
          @submit.prevent="addRule"
        >
          <div>
            <label class="mb-1 block font-medium">URL Path Pattern *</label>
            <UInput
              v-model="ruleForm.pattern"
              placeholder="e.g., /game/* or /promo/*"
              required
              class="w-full"
            />
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="mb-1 block font-medium">Match Mode</label>
              <select
                v-model="ruleForm.match_mode"
                class="h-9 w-full rounded-md border border-slate-200 bg-white px-2 dark:border-slate-700 dark:bg-slate-950"
              >
                <option value="glob">Glob (*)</option>
                <option value="prefix">Prefix</option>
                <option value="exact">Exact</option>
                <option value="regex">Regex</option>
              </select>
            </div>
            <div>
              <label class="mb-1 block font-medium">Target Content Type</label>
              <select
                v-model="ruleForm.target_content_type"
                class="h-9 w-full rounded-md border border-slate-200 bg-white px-2 dark:border-slate-700 dark:bg-slate-950"
              >
                <option value="blog_post">Blog Post</option>
                <option value="blog_index">Blog Index</option>
                <option value="page">Page</option>
                <option value="game_page">Game Page</option>
                <option value="category">Category</option>
                <option value="tag">Tag</option>
                <option value="archive">Archive</option>
                <option value="custom">Custom</option>
                <option value="exclude">Exclude</option>
              </select>
            </div>
          </div>
          <div>
            <label class="mb-1 block font-medium">Priority (lower = higher precedence)</label>
            <UInput v-model="ruleForm.priority" type="number" class="w-32" />
          </div>
          <div>
            <label class="mb-1 block font-medium">Notes</label>
            <UInput v-model="ruleForm.notes" placeholder="Optional explanation" class="w-full" />
          </div>
          <div class="flex justify-end gap-2 pt-2">
            <UButton color="neutral" variant="outline" size="xs" @click="ruleModalOpen = false">Cancel</UButton>
            <UButton type="submit" color="primary" size="xs" :loading="savingRule">Add Rule</UButton>
          </div>
        </form>
      </template>
    </UModal>

    <!-- Inspect Scan Items Modal -->
    <UModal
      v-model:open="inspectModalOpen"
      :title="inspectedScan ? `Scan #${inspectedScan.id} URL Diagnostics` : 'Scan URL Diagnostics'"
    >
      <template #body>
        <div class="space-y-3 text-xs">
          <div class="flex flex-wrap gap-1.5">
            <UButton
              size="xs"
              :color="inspectFilter === 'failures' ? 'primary' : 'neutral'"
              :variant="inspectFilter === 'failures' ? 'solid' : 'outline'"
              @click="inspectFilter = 'failures'"
            >
              Failed & Excluded
            </UButton>
            <UButton
              size="xs"
              :color="inspectFilter === 'pending' ? 'primary' : 'neutral'"
              :variant="inspectFilter === 'pending' ? 'solid' : 'outline'"
              @click="inspectFilter = 'pending'"
            >
              Pending
            </UButton>
            <UButton
              size="xs"
              :color="inspectFilter === 'all' ? 'primary' : 'neutral'"
              :variant="inspectFilter === 'all' ? 'solid' : 'outline'"
              @click="inspectFilter = 'all'"
            >
              All Discovered
            </UButton>
          </div>

          <p
            v-if="inspectLoading"
            class="py-4 text-slate-500"
          >
            Loading scan item diagnostics...
          </p>
          <p
            v-else-if="inspectItems.length === 0"
            class="py-4 text-slate-500"
          >
            No matching URLs recorded under this filter.
          </p>
          <div
            v-else
            class="max-h-96 space-y-2 overflow-y-auto"
          >
            <div
              v-for="item in inspectItems"
              :key="item.id"
              class="rounded border border-slate-200 p-2.5 dark:border-slate-800"
            >
              <div class="flex items-center justify-between gap-2">
                <span class="font-mono text-[11px] text-slate-700 dark:text-slate-200">{{ item.normalized_url }}</span>
                <UBadge
                  :color="item.status === 'failed' ? 'error' : item.status === 'excluded' ? 'neutral' : 'success'"
                  variant="subtle"
                  size="xs"
                >
                  {{ item.failure_reason?.startsWith('ignored_') ? 'ignored' : item.status }}{{ item.http_status ? ` (${item.http_status})` : '' }}
                </UBadge>
              </div>
              <p class="mt-1 text-[11px] text-slate-500">
                Type: {{ item.content_type }} · Sources: {{ item.discovery_sources.join(', ') }}
              </p>
              <p
                v-if="item.error_detail || item.failure_reason"
                class="mt-1 text-[11px] text-rose-600 dark:text-rose-400"
              >
                {{ item.failure_reason }} — {{ item.error_detail }}
              </p>
            </div>
          </div>
        </div>
      </template>
    </UModal>
  </div>
</template>
