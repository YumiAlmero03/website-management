<script setup lang="ts">
import {
  CheckCircle2,
  KeyRound,
  Pencil,
  Plug,
  Plus,
  Share2,
  Trash2,
} from 'lucide-vue-next'
import type {
  PlatformItem,
  SocialProfileCredentialsPayload,
  SocialProfileItem,
} from '~/types/api'
import {
  getConnectionStatusMeta,
  getEligibilityStatusMeta,
  PUBLISHING_TZ_OPTIONS,
  WEEKDAY_OPTIONS,
} from '~/utils/ai'
import { extractErrorMessage, formatDateTime } from '~/utils/format'

const props = defineProps<{
  websiteId: number
  websiteName: string
  defaultLanguage: string
  defaultTone: string | null
  defaultCta: string | null
  defaultHashtags: string[]
}>()

const { request } = useApiClient()
const toast = useToast()

const platforms = ref<PlatformItem[]>([])
const profiles = ref<SocialProfileItem[]>([])
const loading = ref(true)
const errorMessage = ref<string | null>(null)

const modalOpen = ref(false)
const saving = ref(false)
const editingProfile = ref<SocialProfileItem | null>(null)

const deleteTarget = ref<SocialProfileItem | null>(null)
const deleting = ref(false)

const form = ref({
  platform_key: 'facebook',
  profile_name: '',
  profile_url: '',
  external_account_id: '',
  publishing_method: 'manual' as 'manual' | 'api',
  is_active: true,
  generation_enabled: true,
  automatic_generation_enabled: false,
  publishing_enabled: true,
  display_timezone: 'Asia/Manila',
  preferred_publishing_days: ['mon', 'wed', 'fri'] as string[],
  preferred_publishing_times_text: '09:00, 18:00',
  daily_publishing_limit_text: '10',
  min_interval_minutes_text: '30',
  require_approval_before_publish: true,
  default_media_required: false,
  custom_language: '',
  writing_tone: '',
  platform_ai_instructions: '',
  default_hashtags_text: '',
  default_cta: '',
  preferred_length: 'medium',
  character_limit_text: '',
  include_source_url: true,
  include_hashtags: true,
  include_emojis: true,
  content_restrictions: '',
  credentials: {
    api_key: '',
    api_secret: '',
    access_token: '',
    refresh_token: '',
    app_id: '',
    app_secret: '',
  } as Record<string, string>,
  clear_fields: [] as string[],
})

const selectedPlatform = computed<PlatformItem | null>(() => {
  return platforms.value.find((p) => p.platform_key === form.value.platform_key) || null
})

function parseList(raw: string): string[] {
  return raw
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

function getCredentialLabel(field: string): string {
  switch (field) {
    case 'api_key':
      return 'API Key'
    case 'api_secret':
      return 'API Secret'
    case 'access_token':
      return 'Access Token / Page Token'
    case 'refresh_token':
      return 'Refresh Token'
    case 'app_id':
      return 'App ID / Client ID'
    case 'app_secret':
      return 'App Secret / Client Secret'
    default:
      return field
  }
}

function getMaskedValue(field: string): string | null {
  const mask = editingProfile.value?.credential_masks.find((m) => m.field === field)
  return mask?.configured ? (mask.masked_value || '••••••••') : null
}

function toggleClearField(field: string, checked: boolean) {
  if (checked) {
    if (!form.value.clear_fields.includes(field)) {
      form.value.clear_fields.push(field)
    }
  }
  else {
    form.value.clear_fields = form.value.clear_fields.filter((f) => f !== field)
  }
}

function toggleWeekday(day: string) {
  if (form.value.preferred_publishing_days.includes(day)) {
    form.value.preferred_publishing_days = form.value.preferred_publishing_days.filter(
      (d) => d !== day,
    )
  }
  else {
    form.value.preferred_publishing_days = [...form.value.preferred_publishing_days, day]
  }
}

async function loadData() {
  loading.value = true
  errorMessage.value = null
  try {
    const [plats, profs] = await Promise.all([
      request<PlatformItem[]>('/api/v1/platforms'),
      request<SocialProfileItem[]>(`/api/v1/websites/${props.websiteId}/social-profiles`),
    ])
    platforms.value = plats
    profiles.value = profs
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to load website social profiles.')
  }
  finally {
    loading.value = false
  }
}

function openCreateModal() {
  editingProfile.value = null
  const firstPlat = platforms.value[0]?.platform_key || 'facebook'
  form.value = {
    platform_key: firstPlat,
    profile_name: `${props.websiteName} `,
    profile_url: '',
    external_account_id: '',
    publishing_method: 'manual',
    is_active: true,
    generation_enabled: true,
    automatic_generation_enabled: false,
    publishing_enabled: true,
    display_timezone: 'Asia/Manila',
    preferred_publishing_days: ['mon', 'wed', 'fri'],
    preferred_publishing_times_text: '09:00, 18:00',
    daily_publishing_limit_text: '10',
    min_interval_minutes_text: '30',
    require_approval_before_publish: true,
    default_media_required: firstPlat === 'instagram' || firstPlat === 'pinterest',
    custom_language: '',
    writing_tone: props.defaultTone || '',
    platform_ai_instructions: '',
    default_hashtags_text: (props.defaultHashtags || []).join(', '),
    default_cta: props.defaultCta || '',
    preferred_length: 'medium',
    character_limit_text: '',
    include_source_url: true,
    include_hashtags: true,
    include_emojis: true,
    content_restrictions: '',
    credentials: {
      api_key: '',
      api_secret: '',
      access_token: '',
      refresh_token: '',
      app_id: '',
      app_secret: '',
    },
    clear_fields: [],
  }
  modalOpen.value = true
}

function openEditModal(profile: SocialProfileItem) {
  editingProfile.value = profile
  form.value = {
    platform_key: profile.platform_key,
    profile_name: profile.profile_name,
    profile_url: profile.profile_url || '',
    external_account_id: profile.external_account_id || '',
    publishing_method: profile.publishing_method === 'api' ? 'api' : 'manual',
    is_active: profile.is_active,
    generation_enabled: profile.generation_enabled,
    automatic_generation_enabled: profile.automatic_generation_enabled,
    publishing_enabled: profile.publishing_enabled,
    display_timezone: profile.display_timezone || profile.effective_timezone || 'Asia/Manila',
    preferred_publishing_days: [...(profile.preferred_publishing_days || [])],
    preferred_publishing_times_text: (profile.preferred_publishing_times || []).join(', '),
    daily_publishing_limit_text:
      profile.daily_publishing_limit !== null ? String(profile.daily_publishing_limit) : '',
    min_interval_minutes_text:
      profile.min_interval_minutes !== null ? String(profile.min_interval_minutes) : '',
    require_approval_before_publish: profile.require_approval_before_publish,
    default_media_required: profile.default_media_required,
    custom_language: profile.custom_language || '',
    writing_tone: profile.writing_tone || '',
    platform_ai_instructions: profile.platform_ai_instructions || '',
    default_hashtags_text: profile.default_hashtags.join(', '),
    default_cta: profile.default_cta || '',
    preferred_length: profile.preferred_length || 'medium',
    character_limit_text:
      profile.character_limit !== null ? String(profile.character_limit) : '',
    include_source_url: profile.include_source_url,
    include_hashtags: profile.include_hashtags,
    include_emojis: profile.include_emojis,
    content_restrictions: profile.content_restrictions || '',
    credentials: {
      api_key: '',
      api_secret: '',
      access_token: '',
      refresh_token: '',
      app_id: '',
      app_secret: '',
    },
    clear_fields: [],
  }
  modalOpen.value = true
}

function buildCredentialsPayload(): SocialProfileCredentialsPayload | null {
  const allowed = new Set(selectedPlatform.value?.credential_fields || [])
  const out: Record<string, unknown> = {}
  let touched = false
  for (const field of allowed) {
    const val = (form.value.credentials[field] || '').trim()
    if (val) {
      out[field] = val
      touched = true
    }
  }
  if (form.value.clear_fields.length > 0) {
    out.clear_fields = [...form.value.clear_fields]
    touched = true
  }
  return touched ? (out as SocialProfileCredentialsPayload) : null
}

async function saveProfile() {
  if (!form.value.profile_name.trim()) {
    return
  }
  saving.value = true
  try {
    const parsedCharLimit = form.value.character_limit_text.trim()
      ? Number.parseInt(form.value.character_limit_text.trim(), 10)
      : null
    const parsedDailyLimit = form.value.daily_publishing_limit_text.trim()
      ? Number.parseInt(form.value.daily_publishing_limit_text.trim(), 10)
      : null
    const parsedMinInterval = form.value.min_interval_minutes_text.trim()
      ? Number.parseInt(form.value.min_interval_minutes_text.trim(), 10)
      : null

    const body: Record<string, unknown> = {
      profile_name: form.value.profile_name.trim(),
      profile_url: form.value.profile_url.trim() || null,
      external_account_id: form.value.external_account_id.trim() || null,
      publishing_method: form.value.publishing_method,
      is_active: form.value.is_active,
      generation_enabled: form.value.generation_enabled,
      automatic_generation_enabled: form.value.automatic_generation_enabled,
      publishing_enabled: form.value.publishing_enabled,
      display_timezone: form.value.display_timezone || 'Asia/Manila',
      preferred_publishing_days: form.value.preferred_publishing_days,
      preferred_publishing_times: parseList(form.value.preferred_publishing_times_text),
      daily_publishing_limit: parsedDailyLimit,
      clear_daily_publishing_limit: Boolean(editingProfile.value) && parsedDailyLimit === null,
      min_interval_minutes: parsedMinInterval,
      clear_min_interval_minutes: Boolean(editingProfile.value) && parsedMinInterval === null,
      require_approval_before_publish: form.value.require_approval_before_publish,
      default_media_required: form.value.default_media_required,
      custom_language: form.value.custom_language.trim() || null,
      clear_custom_language: Boolean(editingProfile.value) && !form.value.custom_language.trim(),
      writing_tone: form.value.writing_tone.trim() || null,
      platform_ai_instructions: form.value.platform_ai_instructions.trim() || null,
      default_hashtags: parseList(form.value.default_hashtags_text),
      default_cta: form.value.default_cta.trim() || null,
      preferred_length: form.value.preferred_length || 'medium',
      character_limit: parsedCharLimit,
      clear_character_limit: Boolean(editingProfile.value) && parsedCharLimit === null,
      include_source_url: form.value.include_source_url,
      include_hashtags: form.value.include_hashtags,
      include_emojis: form.value.include_emojis,
      content_restrictions: form.value.content_restrictions.trim() || null,
    }
    const creds = buildCredentialsPayload()
    if (creds) {
      body.credentials = creds
    }

    if (editingProfile.value) {
      await request<SocialProfileItem>(`/api/v1/social-profiles/${editingProfile.value.id}`, {
        method: 'PATCH',
        body,
      })
      toast.add({ title: 'Social profile updated', color: 'success' })
    }
    else {
      body.platform_key = form.value.platform_key
      await request<SocialProfileItem>(
        `/api/v1/websites/${props.websiteId}/social-profiles`,
        { method: 'POST', body },
      )
      toast.add({ title: 'Social profile added', color: 'success' })
    }
    modalOpen.value = false
    await loadData()
  }
  catch (err) {
    toast.add({
      title: 'Could not save social profile',
      description: extractErrorMessage(err, 'Verify fields, timezone, and credential format.'),
      color: 'error',
    })
  }
  finally {
    saving.value = false
  }
}

async function quickToggle(
  profile: SocialProfileItem,
  field:
    | 'is_active'
    | 'generation_enabled'
    | 'automatic_generation_enabled'
    | 'publishing_enabled',
) {
  try {
    const updated = await request<SocialProfileItem>(`/api/v1/social-profiles/${profile.id}`, {
      method: 'PATCH',
      body: { [field]: !profile[field] },
    })
    profiles.value = profiles.value.map((p) => (p.id === updated.id ? updated : p))
  }
  catch (err) {
    toast.add({
      title: 'Update failed',
      description: extractErrorMessage(err, 'Could not toggle social profile option.'),
      color: 'error',
    })
  }
}

async function verifyProfileNow(profile: SocialProfileItem) {
  try {
    await request(`/api/v1/social-profiles/${profile.id}/verify`, { method: 'POST' })
    toast.add({ title: 'Connection verified', color: 'success' })
    await loadData()
  }
  catch (err) {
    toast.add({
      title: 'Verification failed',
      description: extractErrorMessage(err, 'Check credentials in Connected Accounts.'),
      color: 'error',
    })
  }
}

async function confirmDelete() {
  if (!deleteTarget.value) {
    return
  }
  deleting.value = true
  try {
    await request(`/api/v1/social-profiles/${deleteTarget.value.id}`, { method: 'DELETE' })
    profiles.value = profiles.value.filter((p) => p.id !== deleteTarget.value?.id)
    toast.add({ title: 'Social profile deleted (publication history preserved)', color: 'neutral' })
    deleteTarget.value = null
  }
  catch (err) {
    toast.add({
      title: 'Delete failed',
      description: extractErrorMessage(err, 'Profile could not be removed.'),
      color: 'error',
    })
  }
  finally {
    deleting.value = false
  }
}

watch(() => props.websiteId, () => void loadData())
onMounted(() => void loadData())
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
      <div>
        <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
          Website Social Profiles, Connections &amp; Publishing Preferences
        </h2>
        <p class="text-xs text-slate-500 dark:text-slate-400">
          Multiple profiles per platform are supported with per-profile rate caps, timezone rendering, and OAuth / Manual publishing configuration.
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <UButton to="/connected-accounts" color="neutral" variant="outline" size="xs">
          <Plug class="mr-1 h-3.5 w-3.5" />
          Connect Accounts
        </UButton>
        <UButton color="primary" size="xs" @click="openCreateModal">
          <Plus class="mr-1 h-3.5 w-3.5" />
          Add Social Profile
        </UButton>
      </div>
    </div>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="Social profiles unavailable"
      :message="errorMessage"
      retryable
      @retry="loadData()"
    />

    <div v-else-if="loading" class="grid grid-cols-1 gap-3 md:grid-cols-2">
      <USkeleton v-for="idx in 2" :key="idx" class="h-44 w-full" />
    </div>

    <AppEmptyState
      v-else-if="profiles.length === 0"
      title="No social profiles configured yet"
      description="Add one or more Facebook, Instagram, Google Business Profile, Threads, LinkedIn, Pinterest, or X profiles for this website."
    >
      <template #actions>
        <UButton color="primary" size="xs" @click="openCreateModal">
          <Plus class="mr-1 h-3.5 w-3.5" />
          Configure First Social Profile
        </UButton>
      </template>
    </AppEmptyState>

    <div v-else class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div
        v-for="prof in profiles"
        :key="prof.id"
        class="flex flex-col justify-between rounded-lg border border-slate-200 bg-white p-4 text-xs shadow-xs dark:border-slate-800 dark:bg-slate-900"
      >
        <div class="space-y-3">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="flex flex-wrap items-center gap-1.5">
                <Share2 class="h-3.5 w-3.5 text-teal-600" />
                <span class="font-semibold text-slate-900 dark:text-slate-100">{{ prof.profile_name }}</span>
                <UBadge color="neutral" variant="subtle" size="xs">
                  {{ prof.platform_display_name }}
                </UBadge>
                <UBadge :color="getConnectionStatusMeta(prof.connection_status).color" variant="subtle" size="xs">
                  {{ getConnectionStatusMeta(prof.connection_status).label }}
                </UBadge>
                <UBadge :color="getEligibilityStatusMeta(prof.publishing_eligibility_status).color" variant="soft" size="xs">
                  {{ getEligibilityStatusMeta(prof.publishing_eligibility_status).label }}
                </UBadge>
              </div>
              <p v-if="prof.target_resource_name || prof.profile_url" class="mt-1 truncate font-mono text-[11px] text-slate-500">
                {{ prof.target_resource_name ? `Target: ${prof.target_resource_name}` : prof.profile_url }}
              </p>
            </div>
            <div class="flex shrink-0 items-center gap-1">
              <UButton color="neutral" variant="ghost" size="xs" title="Verify connection" @click="verifyProfileNow(prof)">
                <CheckCircle2 class="h-3.5 w-3.5" />
              </UButton>
              <UButton color="neutral" variant="outline" size="xs" @click="openEditModal(prof)">
                <Pencil class="h-3 w-3" />
              </UButton>
              <UButton color="error" variant="ghost" size="xs" @click="deleteTarget = prof">
                <Trash2 class="h-3 w-3" />
              </UButton>
            </div>
          </div>

          <div class="grid grid-cols-2 gap-2 rounded-md bg-slate-50 p-2.5 text-[11px] dark:bg-slate-950/60">
            <div>
              <span class="text-slate-500">Method:</span>
              <span class="ml-1 font-medium">{{ prof.publishing_method === 'api' ? 'Official API' : 'Manual Publish' }}</span>
            </div>
            <div>
              <span class="text-slate-500">Timezone:</span>
              <span class="ml-1 font-mono">{{ prof.effective_timezone }}</span>
            </div>
            <div>
              <span class="text-slate-500">Daily Cap / Spacing:</span>
              <span class="ml-1 font-mono">{{ prof.daily_publishing_limit ?? '∞' }} / {{ prof.min_interval_minutes ?? 0 }}m</span>
            </div>
            <div>
              <span class="text-slate-500">Credentials:</span>
              <span class="ml-1 inline-flex items-center gap-1 font-medium">
                <KeyRound class="h-3 w-3 text-slate-400" />
                {{ prof.has_credentials ? 'Encrypted' : 'None' }}
              </span>
            </div>
          </div>

          <p v-if="prof.last_connection_error" class="text-[11px] text-rose-600">
            Connection issue: {{ prof.last_connection_error }}
          </p>

          <div v-if="prof.default_hashtags.length > 0" class="flex flex-wrap gap-1">
            <UBadge v-for="tag in prof.default_hashtags" :key="tag" color="info" variant="soft" size="xs">
              {{ tag }}
            </UBadge>
          </div>
          <div class="flex flex-wrap gap-1.5">
            <SocialProfileTestPost :profile="prof" />
            <SocialProfileCredentialGuide :platform-key="prof.platform_key" :platform-name="prof.platform_display_name" />
          </div>
        </div>

        <div class="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3 dark:border-slate-800">
          <div class="flex flex-wrap items-center gap-3 text-[11px]">
            <label class="flex cursor-pointer items-center gap-1.5">
              <USwitch :model-value="prof.generation_enabled" size="xs" @update:model-value="quickToggle(prof, 'generation_enabled')" />
              <span>AI Gen</span>
            </label>
            <label class="flex cursor-pointer items-center gap-1.5">
              <USwitch :model-value="prof.publishing_enabled" size="xs" @update:model-value="quickToggle(prof, 'publishing_enabled')" />
              <span>Publishing</span>
            </label>
            <label class="flex cursor-pointer items-center gap-1.5">
              <USwitch :model-value="prof.automatic_generation_enabled" size="xs" @update:model-value="quickToggle(prof, 'automatic_generation_enabled')" />
              <span>Auto-Draft</span>
            </label>
          </div>
          <span class="text-[10px] text-slate-400">
            Last pub: {{ prof.last_published_at ? formatDateTime(prof.last_published_at, prof.effective_timezone) : 'Never' }}
          </span>
        </div>
      </div>
    </div>

    <!-- Add / Edit Social Profile Modal -->
    <UModal
      v-model:open="modalOpen"
      :title="editingProfile ? `Edit ${editingProfile.profile_name}` : 'Add Social Profile'"
    >
      <template #body>
        <form class="max-h-[78vh] space-y-4 overflow-y-auto pr-1 text-xs" @submit.prevent="saveProfile">
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label class="mb-1 block font-medium">Platform *</label>
              <select
                v-model="form.platform_key"
                :disabled="Boolean(editingProfile)"
                class="h-9 w-full rounded-md border border-slate-200 bg-white px-2.5 text-xs disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900"
              >
                <option v-for="plat in platforms" :key="plat.id" :value="plat.platform_key">
                  {{ plat.display_name }}
                </option>
              </select>
            </div>
            <div>
              <label class="mb-1 block font-medium">Profile Name *</label>
              <UInput v-model="form.profile_name" size="sm" required placeholder="e.g. Bygame Main Facebook" />
            </div>
            <div>
              <label class="mb-1 block font-medium">Profile URL</label>
              <UInput v-model="form.profile_url" size="sm" placeholder="https://facebook.com/bygame" />
            </div>
            <div>
              <label class="mb-1 block font-medium">External Account / Page ID</label>
              <UInput v-model="form.external_account_id" size="sm" placeholder="Optional Page/Account ID" />
            </div>
            <div>
              <label class="mb-1 block font-medium">Publishing Method</label>
              <select
                v-model="form.publishing_method"
                class="h-9 w-full rounded-md border border-slate-200 bg-white px-2.5 text-xs dark:border-slate-700 dark:bg-slate-900"
              >
                <option value="manual">Manual Publishing (Copy + Record URL)</option>
                <option value="api">Official API Publishing</option>
              </select>
            </div>
            <div>
              <label class="mb-1 block font-medium">Display Timezone</label>
              <select
                v-model="form.display_timezone"
                class="h-9 w-full rounded-md border border-slate-200 bg-white px-2.5 text-xs dark:border-slate-700 dark:bg-slate-900"
              >
                <option v-for="tz in PUBLISHING_TZ_OPTIONS" :key="tz.value" :value="tz.value">
                  {{ tz.label }}
                </option>
              </select>
            </div>
          </div>

          <!-- Publishing Schedule Preferences & Limits -->
          <div class="space-y-3 rounded-md border border-slate-200 bg-slate-50/70 p-3 dark:border-slate-700 dark:bg-slate-950/60">
            <div class="flex items-center justify-between">
              <span class="font-semibold">Phase 4 Publishing Preferences &amp; Safeguards</span>
              <span class="text-[10px] text-slate-500">Auto-publish stays off unless explicitly confirmed</span>
            </div>
            <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label class="mb-1 block font-medium">Daily Publishing Limit</label>
                <UInput v-model="form.daily_publishing_limit_text" type="number" size="sm" placeholder="e.g. 10" />
              </div>
              <div>
                <label class="mb-1 block font-medium">Minimum Interval Between Posts (min)</label>
                <UInput v-model="form.min_interval_minutes_text" type="number" size="sm" placeholder="e.g. 30" />
              </div>
            </div>
            <div>
              <label class="mb-1 block font-medium">Preferred Publishing Days</label>
              <div class="flex flex-wrap gap-1.5">
                <button
                  v-for="d in WEEKDAY_OPTIONS"
                  :key="d.value"
                  type="button"
                  :class="[
                    'rounded border px-2 py-1 text-[11px] font-medium transition-colors',
                    form.preferred_publishing_days.includes(d.value)
                      ? 'border-teal-600 bg-teal-50 text-teal-800 dark:bg-teal-950/60 dark:text-teal-200'
                      : 'border-slate-200 text-slate-500 dark:border-slate-700',
                  ]"
                  @click="toggleWeekday(d.value)"
                >
                  {{ d.label }}
                </button>
              </div>
            </div>
            <div>
              <label class="mb-1 block font-medium">Preferred Times ({{ form.display_timezone }}, HH:MM CSV)</label>
              <UInput v-model="form.preferred_publishing_times_text" size="sm" placeholder="09:00, 14:00, 19:30" />
            </div>
            <div class="grid grid-cols-2 gap-2 pt-1 sm:grid-cols-3">
              <label class="flex cursor-pointer items-center gap-2">
                <USwitch v-model="form.publishing_enabled" size="xs" />
                <span>Publishing Enabled</span>
              </label>
              <label class="flex cursor-pointer items-center gap-2">
                <USwitch v-model="form.require_approval_before_publish" size="xs" />
                <span>Require Approval</span>
              </label>
              <label class="flex cursor-pointer items-center gap-2">
                <USwitch v-model="form.default_media_required" size="xs" />
                <span>Require Image</span>
              </label>
            </div>
          </div>

          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label class="mb-1 block font-medium">Preferred Length</label>
              <select
                v-model="form.preferred_length"
                class="h-9 w-full rounded-md border border-slate-200 bg-white px-2.5 text-xs dark:border-slate-700 dark:bg-slate-900"
              >
                <option value="short">Short &amp; Punchy</option>
                <option value="medium">Balanced (Default)</option>
                <option value="long">Detailed Story</option>
              </select>
            </div>
            <div>
              <label class="mb-1 block font-medium">Custom Language (Blank = {{ defaultLanguage }})</label>
              <UInput v-model="form.custom_language" size="sm" :placeholder="`Inherit (${defaultLanguage})`" />
            </div>
            <div>
              <label class="mb-1 block font-medium">
                Character Limit (Default: {{ selectedPlatform?.default_max_chars ?? 'None' }})
              </label>
              <UInput
                v-model="form.character_limit_text"
                type="number"
                size="sm"
                :placeholder="String(selectedPlatform?.default_max_chars ?? '')"
              />
            </div>
            <div>
              <label class="mb-1 block font-medium">Writing Tone Override</label>
              <UInput v-model="form.writing_tone" size="sm" :placeholder="defaultTone || 'Conversational'" />
            </div>
            <div>
              <label class="mb-1 block font-medium">Default CTA</label>
              <UInput v-model="form.default_cta" size="sm" :placeholder="defaultCta || 'Read full article'" />
            </div>
            <div>
              <label class="mb-1 block font-medium">Default Hashtags (CSV)</label>
              <UInput v-model="form.default_hashtags_text" size="sm" placeholder="#Brand, #News" />
            </div>
          </div>

          <div>
            <label class="mb-1 block font-medium">Platform AI Instructions</label>
            <UTextarea v-model="form.platform_ai_instructions" :rows="2" size="sm" />
          </div>

          <div>
            <label class="mb-1 block font-medium">Profile Content Restrictions</label>
            <UTextarea v-model="form.content_restrictions" :rows="2" size="sm" />
          </div>

          <div class="grid grid-cols-2 gap-2 rounded-md border border-slate-200 p-3 dark:border-slate-700 sm:grid-cols-3">
            <label class="flex cursor-pointer items-center gap-2">
              <USwitch v-model="form.is_active" size="xs" />
              <span>Profile Active</span>
            </label>
            <label class="flex cursor-pointer items-center gap-2">
              <USwitch v-model="form.generation_enabled" size="xs" />
              <span>AI Draft Gen</span>
            </label>
            <label class="flex cursor-pointer items-center gap-2">
              <USwitch v-model="form.automatic_generation_enabled" size="xs" />
              <span>Auto-Scan Gen</span>
            </label>
            <label class="flex cursor-pointer items-center gap-2">
              <USwitch v-model="form.include_source_url" size="xs" />
              <span>Include URL</span>
            </label>
            <label class="flex cursor-pointer items-center gap-2">
              <USwitch v-model="form.include_hashtags" size="xs" />
              <span>Include Hashtags</span>
            </label>
            <label class="flex cursor-pointer items-center gap-2">
              <USwitch v-model="form.include_emojis" size="xs" />
              <span>Include Emojis</span>
            </label>
          </div>

          <!-- Dynamic Encrypted Credentials Section -->
          <div
            v-if="selectedPlatform && selectedPlatform.credential_fields.length > 0"
            class="space-y-3 rounded-md border border-slate-200 bg-slate-50/70 p-3 dark:border-slate-700 dark:bg-slate-950/60"
          >
            <div class="flex items-center justify-between">
              <span class="font-semibold">
                Encrypted API Credentials ({{ selectedPlatform.display_name }})
              </span>
              <span class="text-[10px] text-slate-500">
                Optional for Manual · Stored Fernet-encrypted
              </span>
            </div>
            <div class="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              <div v-for="field in selectedPlatform.credential_fields" :key="field">
                <div class="mb-1 flex items-center justify-between gap-2">
                  <label class="font-medium">{{ getCredentialLabel(field) }}</label>
                  <span v-if="getMaskedValue(field)" class="font-mono text-[10px] text-teal-600 dark:text-teal-400">
                    Saved: {{ getMaskedValue(field) }}
                  </span>
                </div>
                <UInput
                  v-model="(form.credentials as Record<string, string>)[field]"
                  type="password"
                  size="sm"
                  autocomplete="off"
                  :placeholder="getMaskedValue(field) ? 'Blank keeps saved secret' : 'Optional secret'"
                />
                <label v-if="getMaskedValue(field)" class="mt-1 inline-flex cursor-pointer items-center gap-1 text-[10px] text-rose-600">
                  <input
                    type="checkbox"
                    :checked="form.clear_fields.includes(field)"
                    @change="toggleClearField(field, ($event.target as HTMLInputElement).checked)"
                  >
                  Clear stored {{ getCredentialLabel(field) }}
                </label>
              </div>
            </div>
          </div>

          <div class="flex justify-end gap-2 pt-2">
            <UButton type="button" color="neutral" variant="outline" size="sm" @click="modalOpen = false">
              Cancel
            </UButton>
            <UButton type="submit" color="primary" size="sm" :loading="saving">
              {{ editingProfile ? 'Save Profile' : 'Create Social Profile' }}
            </UButton>
          </div>
        </form>
      </template>
    </UModal>

    <!-- Delete Profile Confirmation Modal -->
    <UModal
      :open="Boolean(deleteTarget)"
      title="Delete Social Profile"
      @update:open="(val) => { if (!val) deleteTarget = null }"
    >
      <template #body>
        <p class="text-xs text-slate-600 dark:text-slate-300">
          Delete <strong>{{ deleteTarget?.profile_name }}</strong>? Existing publication history snapshots remain preserved in MySQL even after deletion.
        </p>
        <div class="mt-4 flex justify-end gap-2">
          <UButton color="neutral" variant="outline" size="xs" @click="deleteTarget = null">Cancel</UButton>
          <UButton color="error" size="xs" :loading="deleting" @click="confirmDelete">Confirm Delete</UButton>
        </div>
      </template>
    </UModal>
  </div>
</template>
