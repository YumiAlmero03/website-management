<script setup lang="ts">
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  KeyRound,
  Plug,
  RefreshCw,
  ShieldCheck,
  Target,
  Unplug,
  Wrench,
} from 'lucide-vue-next'
import type {
  ConnectAccountResponse,
  SocialProfileConnectionItem,
  SocialProfileItem,
  TargetResourceOption,
  Website,
} from '~/types/api'
import {
  getConnectionStatusMeta,
  getEligibilityStatusMeta,
} from '~/utils/ai'
import { extractErrorMessage, formatDateTime } from '~/utils/format'

const route = useRoute()
const router = useRouter()
const { request } = useApiClient()
const uiStore = useUiStore()
const toast = useToast()

const OAUTH_STORAGE_KEY = 'contenthub_pending_oauth_profile_id'

const loading = ref(true)
const errorMessage = ref<string | null>(null)
const connections = ref<SocialProfileConnectionItem[]>([])
const profilesMap = ref<Record<number, SocialProfileItem>>({})
const websites = ref<Website[]>([])
const actionBusyId = ref<number | null>(null)

const websiteFilter = ref<string>('all')
const platformFilter = ref<string>('all')
const statusFilter = ref<string>('all')

// OAuth start modal
const oauthModalOpen = ref(false)
const oauthTarget = ref<SocialProfileConnectionItem | null>(null)
const oauthForm = ref({
  app_id: '',
  app_secret: '',
  redirect_uri: '',
})
const startingOauth = ref(false)

// Credentials modal
const credModalOpen = ref(false)
const credTarget = ref<SocialProfileConnectionItem | null>(null)
const credForm = ref<Record<string, string>>({})
const credExtra = ref({
  external_account_id: '',
  target_resource_id: '',
  target_resource_name: '',
  allow_paid_publishing: false,
})
const savingCreds = ref(false)

// Target picker modal
const targetModalOpen = ref(false)
const targetConn = ref<SocialProfileConnectionItem | null>(null)
const selectedTargetId = ref('')
const savingTarget = ref(false)

const platformOptions = computed(() => {
  const seen = new Map<string, string>()
  for (const c of connections.value) {
    if (!seen.has(c.platform_key)) {
      seen.set(c.platform_key, c.platform_display_name)
    }
  }
  return Array.from(seen.entries()).map(([key, label]) => ({ key, label }))
})

const filteredConnections = computed(() => {
  return connections.value.filter((conn) => {
    if (websiteFilter.value !== 'all' && String(conn.website_id) !== websiteFilter.value) {
      return false
    }
    if (platformFilter.value !== 'all' && conn.platform_key !== platformFilter.value) {
      return false
    }
    if (statusFilter.value === 'connected') {
      return conn.connection_status === 'connected'
    }
    if (statusFilter.value === 'attention') {
      return ['expired', 'expiring_soon', 'missing_permissions', 'restricted', 'error'].includes(
        conn.connection_status,
      )
    }
    if (statusFilter.value === 'manual') {
      return conn.auth_type === 'manual' || conn.eligibility_status === 'manual_only'
    }
    return true
  })
})

const statsSummary = computed(() => {
  const total = connections.value.length
  const apiConnected = connections.value.filter(
    (c) => c.connection_status === 'connected' && c.eligibility_status === 'eligible',
  ).length
  const attention = connections.value.filter((c) =>
    ['expired', 'expiring_soon', 'missing_permissions', 'restricted', 'error'].includes(
      c.connection_status,
    ),
  ).length
  const manual = connections.value.filter(
    (c) => c.auth_type === 'manual' || c.eligibility_status === 'manual_only',
  ).length
  return { total, apiConnected, attention, manual }
})

function websiteNameFor(websiteId: number): string {
  const found = websites.value.find((w) => w.id === websiteId)
  return found?.name || `Website #${websiteId}`
}

async function loadAll() {
  loading.value = true
  errorMessage.value = null
  try {
    const [connsRes, profsRes, sitesRes] = await Promise.all([
      request<SocialProfileConnectionItem[]>('/api/v1/publishing/connections'),
      request<SocialProfileItem[]>('/api/v1/social-profiles'),
      request<{ items: Website[] }>('/api/v1/websites', {
        query: { page: 1, page_size: 100 },
      }),
    ])
    connections.value = connsRes
    const map: Record<number, SocialProfileItem> = {}
    for (const p of profsRes) {
      map[p.id] = p
    }
    profilesMap.value = map
    websites.value = sitesRes.items
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to load connected social accounts.')
  }
  finally {
    loading.value = false
  }
}

async function handleOAuthCallbackIfPresent() {
  const state = typeof route.query.state === 'string' ? route.query.state : ''
  const code = typeof route.query.code === 'string' ? route.query.code : ''
  const oauthError = typeof route.query.error === 'string' ? route.query.error : ''
  const oauthErrDesc =
    typeof route.query.error_description === 'string' ? route.query.error_description : ''
  if (!state && !oauthError) {
    return
  }
  const storedId = import.meta.client ? sessionStorage.getItem(OAUTH_STORAGE_KEY) : null
  const profileId = storedId ? Number(storedId) : 0
  if (!profileId || !state) {
    toast.add({
      title: 'OAuth callback incomplete',
      description: 'No matching social profile session found in browser storage. Restart Connect Account.',
      color: 'warning',
    })
    return
  }
  try {
    const updated = await request<SocialProfileConnectionItem>(
      `/api/v1/social-profiles/${profileId}/oauth/complete`,
      {
        method: 'POST',
        body: {
          state,
          code: code || null,
          error: oauthError || null,
          error_description: oauthErrDesc || null,
        },
      },
    )
    if (import.meta.client) {
      sessionStorage.removeItem(OAUTH_STORAGE_KEY)
    }
    toast.add({
      title: updated.connection_status === 'error' ? 'OAuth authorization failed' : 'OAuth connected',
      description: updated.last_error_message || `${updated.platform_display_name} connected successfully.`,
      color: updated.connection_status === 'error' ? 'error' : 'success',
    })
    await router.replace({ path: '/connected-accounts', query: {} })
    await loadAll()
  }
  catch (err) {
    toast.add({
      title: 'OAuth completion failed',
      description: extractErrorMessage(err, 'Could not exchange OAuth authorization code.'),
      color: 'error',
    })
  }
}

function openOauthModal(conn: SocialProfileConnectionItem) {
  oauthTarget.value = conn
  const origin = import.meta.client ? window.location.origin : 'http://127.0.0.1:3100'
  oauthForm.value = {
    app_id: '',
    app_secret: '',
    redirect_uri: `${origin}/connected-accounts?oauth_callback=1`,
  }
  oauthModalOpen.value = true
}

async function startOauthFlow() {
  if (!oauthTarget.value) {
    return
  }
  startingOauth.value = true
  try {
    const res = await request<ConnectAccountResponse>(
      `/api/v1/social-profiles/${oauthTarget.value.social_profile_id}/connect`,
      {
        method: 'POST',
        body: {
          mode: 'oauth',
          app_id: oauthForm.value.app_id.trim() || null,
          app_secret: oauthForm.value.app_secret.trim() || null,
          redirect_uri: oauthForm.value.redirect_uri.trim() || null,
        },
      },
    )
    if (res.authorization_url && import.meta.client) {
      sessionStorage.setItem(OAUTH_STORAGE_KEY, String(oauthTarget.value.social_profile_id))
      window.location.assign(res.authorization_url)
    }
  }
  catch (err) {
    toast.add({
      title: 'OAuth start failed',
      description: extractErrorMessage(err, 'Verify App ID/Secret and redirect URI host allowlist.'),
      color: 'error',
    })
  }
  finally {
    startingOauth.value = false
  }
}

function openCredentialsModal(conn: SocialProfileConnectionItem) {
  credTarget.value = conn
  const fields = profilesMap.value[conn.social_profile_id]?.allowed_credential_fields || [
    'app_id',
    'app_secret',
    'access_token',
    'refresh_token',
  ]
  const obj: Record<string, string> = {}
  for (const f of fields) {
    obj[f] = ''
  }
  credForm.value = obj
  credExtra.value = {
    external_account_id: conn.external_account_id || '',
    target_resource_id: conn.target_resource_id || '',
    target_resource_name: conn.target_resource_name || '',
    allow_paid_publishing: conn.allow_paid_publishing,
  }
  credModalOpen.value = true
}

async function saveCredentials() {
  if (!credTarget.value) {
    return
  }
  savingCreds.value = true
  try {
    const body: Record<string, unknown> = {
      mode: 'credentials',
      external_account_id: credExtra.value.external_account_id.trim() || null,
      target_resource_id: credExtra.value.target_resource_id.trim() || null,
      target_resource_name: credExtra.value.target_resource_name.trim() || null,
      allow_paid_publishing: credExtra.value.allow_paid_publishing,
    }
    for (const [k, v] of Object.entries(credForm.value)) {
      if (v.trim()) {
        body[k] = v.trim()
      }
    }
    await request<ConnectAccountResponse>(
      `/api/v1/social-profiles/${credTarget.value.social_profile_id}/connect`,
      { method: 'POST', body },
    )
    toast.add({ title: 'Credentials saved & verified', color: 'success' })
    credModalOpen.value = false
    await loadAll()
  }
  catch (err) {
    toast.add({
      title: 'Connection update failed',
      description: extractErrorMessage(err, 'Verify API credentials and account configuration.'),
      color: 'error',
    })
  }
  finally {
    savingCreds.value = false
  }
}

function openTargetModal(conn: SocialProfileConnectionItem) {
  targetConn.value = conn
  selectedTargetId.value = conn.target_resource_id || conn.available_targets[0]?.target_id || ''
  targetModalOpen.value = true
}

async function saveSelectedTarget() {
  if (!targetConn.value || !selectedTargetId.value.trim()) {
    return
  }
  savingTarget.value = true
  const opt: TargetResourceOption | undefined = targetConn.value.available_targets.find(
    (t) => t.target_id === selectedTargetId.value,
  )
  try {
    await request<SocialProfileConnectionItem>(
      `/api/v1/social-profiles/${targetConn.value.social_profile_id}/select-target`,
      {
        method: 'POST',
        body: {
          target_resource_id: selectedTargetId.value.trim(),
          target_resource_name: opt?.name || null,
        },
      },
    )
    toast.add({ title: 'Destination target updated', color: 'success' })
    targetModalOpen.value = false
    await loadAll()
  }
  catch (err) {
    toast.add({
      title: 'Target selection failed',
      description: extractErrorMessage(err, 'Could not select destination resource.'),
      color: 'error',
    })
  }
  finally {
    savingTarget.value = false
  }
}

async function verifyConnection(conn: SocialProfileConnectionItem) {
  actionBusyId.value = conn.social_profile_id
  try {
    const res = await request<SocialProfileConnectionItem>(
      `/api/v1/social-profiles/${conn.social_profile_id}/verify`,
      { method: 'POST' },
    )
    toast.add({
      title: 'Verification complete',
      description: res.eligibility_notes || `Status: ${res.connection_status}`,
      color: ['error', 'expired', 'restricted'].includes(res.connection_status) ? 'warning' : 'success',
    })
    await loadAll()
  }
  catch (err) {
    toast.add({
      title: 'Verification failed',
      description: extractErrorMessage(err, 'Could not verify account.'),
      color: 'error',
    })
  }
  finally {
    actionBusyId.value = null
  }
}

async function refreshConnection(conn: SocialProfileConnectionItem) {
  actionBusyId.value = conn.social_profile_id
  try {
    await request<SocialProfileConnectionItem>(
      `/api/v1/social-profiles/${conn.social_profile_id}/refresh`,
      { method: 'POST' },
    )
    toast.add({ title: 'Access token refreshed', color: 'success' })
    await loadAll()
  }
  catch (err) {
    toast.add({
      title: 'Token refresh failed',
      description: extractErrorMessage(err, 'Reconnect via OAuth or enter a fresh token.'),
      color: 'error',
    })
  }
  finally {
    actionBusyId.value = null
  }
}

async function switchToManual(conn: SocialProfileConnectionItem) {
  actionBusyId.value = conn.social_profile_id
  try {
    await request<ConnectAccountResponse>(
      `/api/v1/social-profiles/${conn.social_profile_id}/connect`,
      { method: 'POST', body: { mode: 'manual' } },
    )
    toast.add({ title: 'Switched profile to Manual Publishing', color: 'info' })
    await loadAll()
  }
  catch (err) {
    toast.add({
      title: 'Mode switch failed',
      description: extractErrorMessage(err, 'Could not switch to manual mode.'),
      color: 'error',
    })
  }
  finally {
    actionBusyId.value = null
  }
}

async function togglePaidPolicy(conn: SocialProfileConnectionItem) {
  actionBusyId.value = conn.social_profile_id
  try {
    await request<SocialProfileConnectionItem>(
      `/api/v1/social-profiles/${conn.social_profile_id}/paid-policy`,
      { method: 'POST', body: { allow_paid_publishing: !conn.allow_paid_publishing } },
    )
    toast.add({
      title: !conn.allow_paid_publishing ? 'Paid X API authorized' : 'Paid X API disabled',
      color: 'info',
    })
    await loadAll()
  }
  catch (err) {
    toast.add({
      title: 'Policy update failed',
      description: extractErrorMessage(err, 'Could not update paid publishing opt-in.'),
      color: 'error',
    })
  }
  finally {
    actionBusyId.value = null
  }
}

async function disconnectAccount(conn: SocialProfileConnectionItem) {
  actionBusyId.value = conn.social_profile_id
  try {
    await request<SocialProfileConnectionItem>(
      `/api/v1/social-profiles/${conn.social_profile_id}/disconnect`,
      { method: 'POST', body: { clear_credentials: true, switch_to_manual: false } },
    )
    toast.add({ title: 'Account disconnected and tokens cleared', color: 'neutral' })
    await loadAll()
  }
  catch (err) {
    toast.add({
      title: 'Disconnect failed',
      description: extractErrorMessage(err, 'Could not disconnect account.'),
      color: 'error',
    })
  }
  finally {
    actionBusyId.value = null
  }
}

watch(
  () => uiStore.selectedWebsiteId,
  (val) => {
    websiteFilter.value = val !== null ? String(val) : 'all'
  },
  { immediate: true },
)

onMounted(async () => {
  await handleOAuthCallbackIfPresent()
  await loadAll()
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">
          Connected Social Accounts & API Permissions
        </h1>
        <p class="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
          Configure official OAuth 2.0 / PKCE apps, select Pages, Locations &amp; Boards, verify permissions, and manage manual fallback.
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <UButton to="/publishing-calendar" color="neutral" variant="outline" size="xs">
          Publishing Calendar
        </UButton>
        <UButton to="/social-media" color="neutral" variant="outline" size="xs">
          Social Publishing Hub
        </UButton>
        <UButton color="primary" size="xs" :loading="loading" @click="loadAll">
          <RefreshCw class="mr-1 h-3.5 w-3.5" />
          Refresh
        </UButton>
      </div>
    </div>

    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <div class="rounded-lg border border-slate-200 bg-white p-3.5 dark:border-slate-800 dark:bg-slate-900">
        <p class="text-[11px] uppercase tracking-wide text-slate-500">Social Profiles</p>
        <p class="mt-1 text-xl font-semibold text-slate-900 dark:text-slate-100">{{ statsSummary.total }}</p>
      </div>
      <div class="rounded-lg border border-emerald-200 bg-emerald-50/40 p-3.5 dark:border-emerald-900/50 dark:bg-emerald-950/20">
        <p class="text-[11px] uppercase tracking-wide text-emerald-700 dark:text-emerald-300">API Connected &amp; Eligible</p>
        <p class="mt-1 text-xl font-semibold text-emerald-800 dark:text-emerald-200">{{ statsSummary.apiConnected }}</p>
      </div>
      <div class="rounded-lg border border-amber-200 bg-amber-50/40 p-3.5 dark:border-amber-900/50 dark:bg-amber-950/20">
        <p class="text-[11px] uppercase tracking-wide text-amber-700 dark:text-amber-300">Needs Attention / Expiring</p>
        <p class="mt-1 text-xl font-semibold text-amber-800 dark:text-amber-200">{{ statsSummary.attention }}</p>
      </div>
      <div class="rounded-lg border border-slate-200 bg-white p-3.5 dark:border-slate-800 dark:bg-slate-900">
        <p class="text-[11px] uppercase tracking-wide text-slate-500">Manual Publishing Mode</p>
        <p class="mt-1 text-xl font-semibold text-slate-900 dark:text-slate-100">{{ statsSummary.manual }}</p>
      </div>
    </div>

    <div class="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-white p-3 text-xs dark:border-slate-800 dark:bg-slate-900">
      <select
        v-model="websiteFilter"
        class="h-8 rounded-md border border-slate-200 bg-white px-2.5 dark:border-slate-700 dark:bg-slate-900"
      >
        <option value="all">All Websites</option>
        <option v-for="site in websites" :key="site.id" :value="String(site.id)">
          {{ site.name }}
        </option>
      </select>
      <select
        v-model="platformFilter"
        class="h-8 rounded-md border border-slate-200 bg-white px-2.5 dark:border-slate-700 dark:bg-slate-900"
      >
        <option value="all">All Platforms</option>
        <option v-for="opt in platformOptions" :key="opt.key" :value="opt.key">
          {{ opt.label }}
        </option>
      </select>
      <select
        v-model="statusFilter"
        class="h-8 rounded-md border border-slate-200 bg-white px-2.5 dark:border-slate-700 dark:bg-slate-900"
      >
        <option value="all">All Statuses</option>
        <option value="connected">Connected Only</option>
        <option value="attention">Needs Attention / Expiring</option>
        <option value="manual">Manual Publishing Only</option>
      </select>
    </div>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="Connected accounts unavailable"
      :message="errorMessage"
      retryable
      @retry="loadAll()"
    />

    <div v-else-if="loading" class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <USkeleton v-for="idx in 4" :key="idx" class="h-52 w-full" />
    </div>

    <AppEmptyState
      v-else-if="filteredConnections.length === 0"
      title="No social profiles match the active filters"
      description="Create social profiles under Websites -> Social Profiles first, then connect or verify them here."
    >
      <template #actions>
        <UButton to="/websites" color="primary" size="xs">Go to Websites</UButton>
      </template>
    </AppEmptyState>

    <div v-else class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <article
        v-for="conn in filteredConnections"
        :key="conn.social_profile_id"
        class="flex flex-col justify-between rounded-lg border border-slate-200 bg-white p-4 text-xs shadow-xs dark:border-slate-800 dark:bg-slate-900"
      >
        <div class="space-y-3">
          <div class="flex flex-wrap items-start justify-between gap-2">
            <div>
              <div class="flex flex-wrap items-center gap-1.5">
                <Plug class="h-3.5 w-3.5 text-teal-600" />
                <span class="font-semibold text-slate-900 dark:text-slate-100">
                  {{ profilesMap[conn.social_profile_id]?.profile_name || `Profile #${conn.social_profile_id}` }}
                </span>
                <UBadge color="neutral" variant="outline" size="xs">
                  {{ conn.platform_display_name }}
                </UBadge>
                <UBadge :color="getConnectionStatusMeta(conn.connection_status).color" variant="subtle" size="xs">
                  {{ getConnectionStatusMeta(conn.connection_status).label }}
                </UBadge>
                <UBadge :color="getEligibilityStatusMeta(conn.eligibility_status).color" variant="soft" size="xs">
                  {{ getEligibilityStatusMeta(conn.eligibility_status).label }}
                </UBadge>
              </div>
              <p class="mt-1 text-[11px] text-slate-500">
                Website: <strong>{{ websiteNameFor(conn.website_id) }}</strong>
                <span v-if="conn.api_version"> · API {{ conn.api_version }}</span>
                <span v-if="conn.access_tier"> · Tier: {{ conn.access_tier }}</span>
              </p>
            </div>
            <a
              v-if="conn.profile_url"
              :href="conn.profile_url"
              target="_blank"
              rel="noopener noreferrer"
              class="inline-flex items-center gap-1 text-[11px] text-teal-600 hover:underline dark:text-teal-400"
            >
              Profile <ExternalLink class="h-3 w-3" />
            </a>
          </div>

          <div class="grid grid-cols-2 gap-2 rounded-md bg-slate-50 p-2.5 text-[11px] dark:bg-slate-950/60">
            <div>
              <span class="text-slate-500">Target:</span>
              <span class="ml-1 font-medium">{{ conn.target_resource_name || conn.target_resource_id || 'Not selected' }}</span>
            </div>
            <div>
              <span class="text-slate-500">Account ID:</span>
              <span class="ml-1 font-mono">{{ conn.external_account_id || '-' }}</span>
            </div>
            <div>
              <span class="text-slate-500">Last Verified:</span>
              <span class="ml-1">{{ formatDateTime(conn.last_verified_at) }}</span>
            </div>
            <div>
              <span class="text-slate-500">Token Expires:</span>
              <span :class="['ml-1', conn.expires_soon ? 'font-semibold text-amber-600' : '']">
                {{ conn.token_expires_at ? formatDateTime(conn.token_expires_at) : 'N/A' }}
              </span>
            </div>
          </div>

          <p v-if="conn.eligibility_notes" class="text-[11px] text-slate-600 dark:text-slate-300">
            {{ conn.eligibility_notes }}
          </p>

          <div
            v-if="conn.last_error_message"
            class="flex items-start gap-2 rounded border border-rose-200 bg-rose-50 px-2.5 py-2 text-[11px] text-rose-800 dark:border-rose-900/50 dark:bg-rose-950/30 dark:text-rose-200"
          >
            <AlertTriangle class="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span><strong>{{ conn.last_error_code || 'ERROR' }}:</strong> {{ conn.last_error_message }}</span>
          </div>

          <div v-if="conn.required_scopes.length > 0" class="flex flex-wrap gap-1">
            <UBadge
              v-for="scope in conn.granted_scopes"
              :key="`g-${scope}`"
              color="success"
              variant="soft"
              size="xs"
            >
              ✓ {{ scope }}
            </UBadge>
            <UBadge
              v-for="scope in conn.missing_scopes"
              :key="`m-${scope}`"
              color="warning"
              variant="soft"
              size="xs"
            >
              Missing: {{ scope }}
            </UBadge>
          </div>

          <div
            v-if="conn.capabilities?.limitations_summary"
            class="rounded border border-slate-200 bg-slate-50/70 px-2.5 py-2 text-[11px] text-slate-600 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-400"
          >
            <strong>Official API Rules:</strong> {{ conn.capabilities.limitations_summary }}
          </div>
        </div>

        <div class="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3 dark:border-slate-800">
          <div class="flex flex-wrap gap-1.5">
            <UButton
              v-if="conn.capabilities?.supports_oauth"
              color="primary"
              size="xs"
              :loading="actionBusyId === conn.social_profile_id"
              @click="openOauthModal(conn)"
            >
              <ShieldCheck class="mr-1 h-3 w-3" />
              Connect OAuth
            </UButton>
            <UButton
              v-if="conn.platform_key !== 'custom_social'"
              color="neutral"
              variant="outline"
              size="xs"
              :loading="actionBusyId === conn.social_profile_id"
              @click="openCredentialsModal(conn)"
            >
              <KeyRound class="mr-1 h-3 w-3" />
              Credentials
            </UButton>
            <UButton
              v-if="conn.available_targets.length > 0"
              color="neutral"
              variant="outline"
              size="xs"
              @click="openTargetModal(conn)"
            >
              <Target class="mr-1 h-3 w-3" />
              Target ({{ conn.available_targets.length }})
            </UButton>
            <UButton
              color="neutral"
              variant="subtle"
              size="xs"
              :loading="actionBusyId === conn.social_profile_id"
              @click="verifyConnection(conn)"
            >
              <CheckCircle2 class="mr-1 h-3 w-3" />
              Verify
            </UButton>
            <UButton
              v-if="conn.capabilities?.supports_refresh && conn.connection_status !== 'not_connected'"
              color="neutral"
              variant="ghost"
              size="xs"
              :loading="actionBusyId === conn.social_profile_id"
              @click="refreshConnection(conn)"
            >
              Refresh Token
            </UButton>
          </div>

          <div class="flex flex-wrap gap-1">
            <SocialProfileTestPost v-if="profilesMap[conn.social_profile_id]" :profile="profilesMap[conn.social_profile_id]!" />
            <SocialProfileCredentialGuide :platform-key="conn.platform_key" :platform-name="conn.platform_display_name" />
            <UButton
              v-if="conn.capabilities?.requires_paid_api_ack"
              :color="conn.allow_paid_publishing ? 'warning' : 'neutral'"
              variant="subtle"
              size="xs"
              @click="togglePaidPolicy(conn)"
            >
              {{ conn.allow_paid_publishing ? 'Paid X API Enabled' : 'Enable Paid X API' }}
            </UButton>
            <UButton
              v-if="conn.auth_type !== 'manual'"
              color="info"
              variant="ghost"
              size="xs"
              @click="switchToManual(conn)"
            >
              <Wrench class="mr-1 h-3 w-3" />
              Manual Mode
            </UButton>
            <UButton
              v-if="conn.connection_status !== 'not_connected' && conn.connection_status !== 'disconnected'"
              color="error"
              variant="ghost"
              size="xs"
              @click="disconnectAccount(conn)"
            >
              <Unplug class="h-3.5 w-3.5" />
            </UButton>
          </div>
        </div>
      </article>
    </div>

    <!-- Start OAuth Modal -->
    <UModal v-model:open="oauthModalOpen" :title="`Connect ${oauthTarget?.platform_display_name || ''} via OAuth 2.0`">
      <template #body>
        <form class="space-y-3 text-xs" @submit.prevent="startOauthFlow">
          <p class="text-slate-600 dark:text-slate-300">
            Enter your developer App/Client credentials (optional if already saved encrypted) and verify the callback URI matches your developer console allowlist.
          </p>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label class="mb-1 block font-medium">App ID / Client ID</label>
              <UInput v-model="oauthForm.app_id" size="sm" autocomplete="off" placeholder="Leave blank if already saved" />
            </div>
            <div>
              <label class="mb-1 block font-medium">App Secret / Client Secret</label>
              <UInput v-model="oauthForm.app_secret" type="password" size="sm" autocomplete="off" placeholder="Optional for PKCE public apps" />
            </div>
          </div>
          <div>
            <label class="mb-1 block font-medium">OAuth Redirect Callback URI *</label>
            <UInput v-model="oauthForm.redirect_uri" size="sm" required />
          </div>
          <div class="flex justify-end gap-2 pt-2">
            <UButton type="button" color="neutral" variant="outline" size="xs" @click="oauthModalOpen = false">
              Cancel
            </UButton>
            <UButton type="submit" color="primary" size="xs" :loading="startingOauth">
              Authorize with Platform
            </UButton>
          </div>
        </form>
      </template>
    </UModal>

    <!-- Manual Token / Credentials Modal -->
    <UModal v-model:open="credModalOpen" :title="`Configure ${credTarget?.platform_display_name || ''} Credentials`">
      <template #body>
        <form class="space-y-3 text-xs" @submit.prevent="saveCredentials">
          <div class="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            <div v-for="field in Object.keys(credForm)" :key="field">
              <label class="mb-1 block font-medium uppercase tracking-wide text-[10px] text-slate-500">
                {{ field.replace(/_/g, ' ') }}
              </label>
              <UInput
                v-model="credForm[field]"
                type="password"
                size="sm"
                autocomplete="off"
                placeholder="Blank keeps existing saved secret"
              />
            </div>
          </div>
          <div class="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            <div>
              <label class="mb-1 block font-medium">External Account / IG User ID</label>
              <UInput v-model="credExtra.external_account_id" size="sm" />
            </div>
            <div>
              <label class="mb-1 block font-medium">Target Resource ID (Page/Location/Board)</label>
              <UInput v-model="credExtra.target_resource_id" size="sm" />
            </div>
          </div>
          <label v-if="credTarget?.capabilities?.requires_paid_api_ack" class="flex cursor-pointer items-center gap-2 rounded border border-amber-200 bg-amber-50 p-2 text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200">
            <input v-model="credExtra.allow_paid_publishing" type="checkbox">
            <span>Explicitly authorize pay-per-use / paid API publishing credits for X</span>
          </label>
          <div class="flex justify-end gap-2 pt-2">
            <UButton type="button" color="neutral" variant="outline" size="xs" @click="credModalOpen = false">
              Cancel
            </UButton>
            <UButton type="submit" color="primary" size="xs" :loading="savingCreds">
              Save &amp; Verify
            </UButton>
          </div>
        </form>
      </template>
    </UModal>

    <!-- Target Resource Selection Modal -->
    <UModal v-model:open="targetModalOpen" :title="`Select Destination Target — ${targetConn?.platform_display_name || ''}`">
      <template #body>
        <form class="space-y-3 text-xs" @submit.prevent="saveSelectedTarget">
          <div v-if="targetConn" class="space-y-2">
            <label
              v-for="opt in targetConn.available_targets"
              :key="opt.target_id"
              class="flex cursor-pointer items-start gap-2 rounded border border-slate-200 p-2.5 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800/50"
            >
              <input v-model="selectedTargetId" type="radio" :value="opt.target_id" class="mt-0.5">
              <div class="min-w-0">
                <p class="font-semibold text-slate-900 dark:text-slate-100">{{ opt.name }}</p>
                <p class="font-mono text-[10px] text-slate-500">{{ opt.account_type }} · {{ opt.target_id }}</p>
              </div>
            </label>
          </div>
          <div class="flex justify-end gap-2 pt-2">
            <UButton type="button" color="neutral" variant="outline" size="xs" @click="targetModalOpen = false">
              Cancel
            </UButton>
            <UButton type="submit" color="primary" size="xs" :loading="savingTarget">
              Confirm Target
            </UButton>
          </div>
        </form>
      </template>
    </UModal>
  </div>
</template>
