<script setup lang="ts">
import { KeyRound, Pencil, Plus, Share2, ShieldAlert, Trash2 } from 'lucide-vue-next'
import type {
  PlatformItem,
  SocialProfileCredentialsPayload,
  SocialProfileItem,
} from '~/types/api'
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
  is_active: true,
  publishing_method: 'manual' as 'manual' | 'api',
  generation_enabled: true,
  automatic_generation_enabled: false,
  custom_language: '',
  clear_custom_language: false,
  writing_tone: '',
  platform_ai_instructions: '',
  default_hashtags_text: '',
  default_cta: '',
  preferred_length: 'medium',
  character_limit_text: '',
  clear_character_limit: false,
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
  clear_fields: [] as string[],
})

const selectedPlatform = computed<PlatformItem | null>(() => {
  if (editingProfile.value) {
    return platforms.value.find((p) => p.id === editingProfile.value?.platform_id) || null
  }
  return platforms.value.find((p) => p.platform_key === form.value.platform_key) || null
})

function parseTags(raw: string): string[] {
  return raw
    .split(/[\n,]/)
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
      return 'Access Token'
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
  const next = new Set(form.value.clear_fields)
  if (checked) {
    next.add(field)
  }
  else {
    next.delete(field)
  }
  form.value.clear_fields = Array.from(next)
}

async function loadData() {
  loading.value = true
  errorMessage.value = null
  try {
    const [platRes, profRes] = await Promise.all([
      request<PlatformItem[]>('/api/v1/platforms'),
      request<SocialProfileItem[]>(`/api/v1/websites/${props.websiteId}/social-profiles`),
    ])
    platforms.value = platRes
    profiles.value = profRes
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
  form.value = {
    platform_key: platforms.value[0]?.platform_key || 'facebook',
    profile_name: `${props.websiteName} Page`,
    profile_url: '',
    external_account_id: '',
    is_active: true,
    publishing_method: 'manual',
    generation_enabled: true,
    automatic_generation_enabled: false,
    custom_language: '',
    clear_custom_language: false,
    writing_tone: props.defaultTone || '',
    platform_ai_instructions: '',
    default_hashtags_text: props.defaultHashtags.join(', '),
    default_cta: props.defaultCta || '',
    preferred_length: 'medium',
    character_limit_text: '',
    clear_character_limit: false,
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
    is_active: profile.is_active,
    publishing_method: (profile.publishing_method === 'api' ? 'api' : 'manual'),
    generation_enabled: profile.generation_enabled,
    automatic_generation_enabled: profile.automatic_generation_enabled,
    custom_language: profile.custom_language || '',
    clear_custom_language: false,
    writing_tone: profile.writing_tone || '',
    platform_ai_instructions: profile.platform_ai_instructions || '',
    default_hashtags_text: profile.default_hashtags.join(', '),
    default_cta: profile.default_cta || '',
    preferred_length: profile.preferred_length || 'medium',
    character_limit_text: profile.character_limit !== null ? String(profile.character_limit) : '',
    clear_character_limit: false,
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
  const allowed = selectedPlatform.value?.credential_fields || []
  const payload: SocialProfileCredentialsPayload = {}
  let hasChanges = false
  for (const field of allowed) {
    const val = (form.value.credentials as Record<string, string>)[field]?.trim()
    if (val) {
      ;(payload as Record<string, unknown>)[field] = val
      hasChanges = true
    }
  }
  if (form.value.clear_fields.length > 0) {
    payload.clear_fields = [...form.value.clear_fields]
    hasChanges = true
  }
  return hasChanges ? payload : null
}

async function saveProfile() {
  saving.value = true
  try {
    const credsPayload = buildCredentialsPayload()
    const parsedCharLimit = form.value.character_limit_text.trim()
      ? Number(form.value.character_limit_text)
      : null

    if (editingProfile.value) {
      const body = {
        profile_name: form.value.profile_name.trim(),
        profile_url: form.value.profile_url.trim() || null,
        external_account_id: form.value.external_account_id.trim() || null,
        is_active: form.value.is_active,
        publishing_method: form.value.publishing_method,
        generation_enabled: form.value.generation_enabled,
        automatic_generation_enabled: form.value.automatic_generation_enabled,
        auto_publish_enabled: false,
        custom_language: form.value.custom_language.trim() || null,
        clear_custom_language: !form.value.custom_language.trim(),
        writing_tone: form.value.writing_tone.trim() || null,
        platform_ai_instructions: form.value.platform_ai_instructions.trim() || null,
        default_hashtags: parseTags(form.value.default_hashtags_text),
        default_cta: form.value.default_cta.trim() || null,
        preferred_length: form.value.preferred_length,
        character_limit: parsedCharLimit,
        clear_character_limit: parsedCharLimit === null,
        include_source_url: form.value.include_source_url,
        include_hashtags: form.value.include_hashtags,
        include_emojis: form.value.include_emojis,
        content_restrictions: form.value.content_restrictions.trim() || null,
        credentials: credsPayload,
      }
      const updated = await request<SocialProfileItem>(
        `/api/v1/social-profiles/${editingProfile.value.id}`,
        { method: 'PATCH', body },
      )
      profiles.value = profiles.value.map((p) => (p.id === updated.id ? updated : p))
      toast.add({ title: `Updated ${updated.profile_name}`, color: 'success' })
    }
    else {
      const body = {
        platform_key: form.value.platform_key,
        profile_name: form.value.profile_name.trim(),
        profile_url: form.value.profile_url.trim() || null,
        external_account_id: form.value.external_account_id.trim() || null,
        is_active: form.value.is_active,
        publishing_method: form.value.publishing_method,
        generation_enabled: form.value.generation_enabled,
        automatic_generation_enabled: form.value.automatic_generation_enabled,
        auto_publish_enabled: false,
        custom_language: form.value.custom_language.trim() || null,
        writing_tone: form.value.writing_tone.trim() || null,
        platform_ai_instructions: form.value.platform_ai_instructions.trim() || null,
        default_hashtags: parseTags(form.value.default_hashtags_text),
        default_cta: form.value.default_cta.trim() || null,
        preferred_length: form.value.preferred_length,
        character_limit: parsedCharLimit,
        include_source_url: form.value.include_source_url,
        include_hashtags: form.value.include_hashtags,
        include_emojis: form.value.include_emojis,
        content_restrictions: form.value.content_restrictions.trim() || null,
        credentials: credsPayload,
      }
      const created = await request<SocialProfileItem>(
        `/api/v1/websites/${props.websiteId}/social-profiles`,
        { method: 'POST', body },
      )
      profiles.value = [...profiles.value, created]
      toast.add({ title: `Added ${created.profile_name}`, color: 'success' })
    }
    modalOpen.value = false
  }
  catch (err) {
    toast.add({
      title: 'Could not save social profile',
      description: extractErrorMessage(err, 'Verify fields and credential format.'),
      color: 'error',
    })
  }
  finally {
    saving.value = false
  }
}

async function quickToggle(profile: SocialProfileItem, field: 'is_active' | 'generation_enabled' | 'automatic_generation_enabled') {
  try {
    const updated = await request<SocialProfileItem>(
      `/api/v1/social-profiles/${profile.id}`,
      {
        method: 'PATCH',
        body: { [field]: !profile[field] },
      },
    )
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

async function confirmDelete() {
  if (!deleteTarget.value) {
    return
  }
  deleting.value = true
  try {
    await request(`/api/v1/social-profiles/${deleteTarget.value.id}`, { method: 'DELETE' })
    profiles.value = profiles.value.filter((p) => p.id !== deleteTarget.value?.id)
    toast.add({ title: 'Social profile deleted', color: 'neutral' })
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

watch(
  () => props.websiteId,
  () => {
    void loadData()
  },
)

onMounted(() => {
  void loadData()
})
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
      <div>
        <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
          Website Social Profiles & Destination Rules
        </h2>
        <p class="text-xs text-slate-500 dark:text-slate-400">
          Multiple profiles per platform are supported. AI content generation automatically targets all active profiles with generation enabled.
        </p>
      </div>
      <UButton
        color="primary"
        size="xs"
        @click="openCreateModal"
      >
        <Plus class="mr-1 h-3.5 w-3.5" />
        Add Social Profile
      </UButton>
    </div>

    <div class="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50/70 px-3.5 py-2.5 text-xs text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200">
      <ShieldAlert class="mt-0.5 h-4 w-4 shrink-0" />
      <span>
        Phase 3 supports draft generation, manual copy/review, and Fernet-encrypted credential storage for Phase 4 readiness. Live external social publishing & auto-posting are intentionally disabled.
      </span>
    </div>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="Social profiles unavailable"
      :message="errorMessage"
      retryable
      @retry="loadData()"
    />

    <div
      v-else-if="loading"
      class="grid grid-cols-1 gap-3 md:grid-cols-2"
    >
      <USkeleton
        v-for="idx in 2"
        :key="idx"
        class="h-40 w-full"
      />
    </div>

    <AppEmptyState
      v-else-if="profiles.length === 0"
      title="No social profiles configured yet"
      description="Add one or more Facebook, Instagram, X, Threads, LinkedIn, Google Business, or Pinterest profiles for this website before generating social drafts."
    >
      <template #actions>
        <UButton
          color="primary"
          size="xs"
          @click="openCreateModal"
        >
          <Plus class="mr-1 h-3.5 w-3.5" />
          Configure First Social Profile
        </UButton>
      </template>
    </AppEmptyState>

    <div
      v-else
      class="grid grid-cols-1 gap-4 lg:grid-cols-2"
    >
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
                <UBadge
                  color="neutral"
                  variant="subtle"
                  size="xs"
                >
                  {{ prof.platform_display_name }}
                </UBadge>
                <UBadge
                  :color="prof.is_active ? 'success' : 'neutral'"
                  variant="subtle"
                  size="xs"
                >
                  {{ prof.is_active ? 'Active' : 'Inactive' }}
                </UBadge>
              </div>
              <p
                v-if="prof.profile_url"
                class="mt-1 truncate font-mono text-[11px] text-slate-500"
              >
                {{ prof.profile_url }}
              </p>
            </div>
            <div class="flex shrink-0 items-center gap-1">
              <UButton
                color="neutral"
                variant="outline"
                size="xs"
                @click="openEditModal(prof)"
              >
                <Pencil class="h-3 w-3" />
              </UButton>
              <UButton
                color="error"
                variant="ghost"
                size="xs"
                @click="deleteTarget = prof"
              >
                <Trash2 class="h-3 w-3" />
              </UButton>
            </div>
          </div>

          <div class="grid grid-cols-2 gap-2 rounded-md bg-slate-50 p-2.5 text-[11px] dark:bg-slate-950/60">
            <div>
              <span class="text-slate-500">Method:</span>
              <span class="ml-1 font-medium">{{ prof.publishing_method === 'api' ? 'API Ready' : 'Manual Copy' }}</span>
            </div>
            <div>
              <span class="text-slate-500">Language:</span>
              <span class="ml-1 font-medium">{{ prof.effective_language }}</span>
            </div>
            <div>
              <span class="text-slate-500">Limit:</span>
              <span class="ml-1 font-mono">{{ prof.effective_character_limit ?? 'Unlimited' }}</span>
            </div>
            <div>
              <span class="text-slate-500">Credentials:</span>
              <span class="ml-1 inline-flex items-center gap-1 font-medium">
                <KeyRound class="h-3 w-3 text-slate-400" />
                {{ prof.has_credentials ? 'Encrypted' : 'None (Manual)' }}
              </span>
            </div>
          </div>

          <div
            v-if="prof.default_hashtags.length > 0"
            class="flex flex-wrap gap-1"
          >
            <UBadge
              v-for="tag in prof.default_hashtags"
              :key="tag"
              color="info"
              variant="soft"
              size="xs"
            >
              {{ tag }}
            </UBadge>
          </div>
        </div>

        <div class="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3 dark:border-slate-800">
          <div class="flex flex-wrap items-center gap-3 text-[11px]">
            <label class="flex cursor-pointer items-center gap-1.5">
              <USwitch
                :model-value="prof.generation_enabled"
                size="xs"
                @update:model-value="quickToggle(prof, 'generation_enabled')"
              />
              <span>AI Generate</span>
            </label>
            <label class="flex cursor-pointer items-center gap-1.5">
              <USwitch
                :model-value="prof.automatic_generation_enabled"
                size="xs"
                @update:model-value="quickToggle(prof, 'automatic_generation_enabled')"
              />
              <span>Auto-Scan Drafts</span>
            </label>
          </div>
          <span class="text-[10px] text-slate-400">
            Auto-publish: Phase 4 · Updated {{ formatDateTime(prof.updated_at) }}
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
        <form
          class="max-h-[75vh] space-y-4 overflow-y-auto pr-1 text-xs"
          @submit.prevent="saveProfile"
        >
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label class="mb-1 block font-medium">Platform *</label>
              <select
                v-model="form.platform_key"
                :disabled="Boolean(editingProfile)"
                class="h-9 w-full rounded-md border border-slate-200 bg-white px-2.5 text-xs disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900"
              >
                <option
                  v-for="plat in platforms"
                  :key="plat.id"
                  :value="plat.platform_key"
                >
                  {{ plat.display_name }}
                </option>
              </select>
            </div>
            <div>
              <label class="mb-1 block font-medium">Profile Name *</label>
              <UInput
                v-model="form.profile_name"
                size="sm"
                required
                placeholder="e.g. Bygame Main Facebook"
              />
            </div>
            <div>
              <label class="mb-1 block font-medium">Profile URL</label>
              <UInput
                v-model="form.profile_url"
                size="sm"
                placeholder="https://facebook.com/bygame"
              />
            </div>
            <div>
              <label class="mb-1 block font-medium">External Account / Page ID</label>
              <UInput
                v-model="form.external_account_id"
                size="sm"
                placeholder="Optional Page/Account ID"
              />
            </div>
            <div>
              <label class="mb-1 block font-medium">Publishing Method</label>
              <select
                v-model="form.publishing_method"
                class="h-9 w-full rounded-md border border-slate-200 bg-white px-2.5 text-xs dark:border-slate-700 dark:bg-slate-900"
              >
                <option value="manual">Manual Copy & Post (Phase 3 Ready)</option>
                <option value="api">API Credentials Stored (Phase 4 Publishing)</option>
              </select>
            </div>
            <div>
              <label class="mb-1 block font-medium">Preferred Length</label>
              <select
                v-model="form.preferred_length"
                class="h-9 w-full rounded-md border border-slate-200 bg-white px-2.5 text-xs dark:border-slate-700 dark:bg-slate-900"
              >
                <option value="short">Short & Punchy</option>
                <option value="medium">Balanced (Default)</option>
                <option value="long">Detailed Story</option>
              </select>
            </div>
            <div>
              <label class="mb-1 block font-medium">Custom Language (Blank = {{ defaultLanguage }})</label>
              <UInput
                v-model="form.custom_language"
                size="sm"
                :placeholder="`Inherit (${defaultLanguage})`"
              />
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
              <UInput
                v-model="form.writing_tone"
                size="sm"
                :placeholder="defaultTone || 'Conversational'"
              />
            </div>
            <div>
              <label class="mb-1 block font-medium">Default CTA</label>
              <UInput
                v-model="form.default_cta"
                size="sm"
                :placeholder="defaultCta || 'Read full article'"
              />
            </div>
          </div>

          <div>
            <label class="mb-1 block font-medium">Default Hashtags (Comma separated)</label>
            <UInput
              v-model="form.default_hashtags_text"
              size="sm"
              placeholder="#Brand, #News"
            />
          </div>

          <div>
            <label class="mb-1 block font-medium">Platform AI Instructions</label>
            <UTextarea
              v-model="form.platform_ai_instructions"
              :rows="2"
              size="sm"
              placeholder="Specific style, emoji policy, or hook rules for this profile..."
            />
          </div>

          <div>
            <label class="mb-1 block font-medium">Profile Content Restrictions</label>
            <UTextarea
              v-model="form.content_restrictions"
              :rows="2"
              size="sm"
              placeholder="Words, claims, or compliance rules to avoid..."
            />
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
                Optional for Manual Copy · Stored Fernet-encrypted
              </span>
            </div>
            <div class="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              <div
                v-for="field in selectedPlatform.credential_fields"
                :key="field"
              >
                <div class="mb-1 flex items-center justify-between gap-2">
                  <label class="font-medium">{{ getCredentialLabel(field) }}</label>
                  <span
                    v-if="getMaskedValue(field)"
                    class="font-mono text-[10px] text-teal-600 dark:text-teal-400"
                  >
                    Saved: {{ getMaskedValue(field) }}
                  </span>
                </div>
                <UInput
                  v-model="(form.credentials as Record<string, string>)[field]"
                  type="password"
                  size="sm"
                  autocomplete="off"
                  :placeholder="getMaskedValue(field) ? 'Leave blank to keep saved secret' : 'Enter secret value (optional)'"
                />
                <label
                  v-if="getMaskedValue(field)"
                  class="mt-1 inline-flex cursor-pointer items-center gap-1 text-[10px] text-rose-600"
                >
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
            <UButton
              type="button"
              color="neutral"
              variant="outline"
              size="sm"
              @click="modalOpen = false"
            >
              Cancel
            </UButton>
            <UButton
              type="submit"
              color="primary"
              size="sm"
              :loading="saving"
            >
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
          Delete <strong>{{ deleteTarget?.profile_name }}</strong>? Existing generated social drafts linked to this profile remain accessible or should be archived first.
        </p>
        <div class="mt-4 flex justify-end gap-2">
          <UButton
            color="neutral"
            variant="outline"
            size="xs"
            @click="deleteTarget = null"
          >
            Cancel
          </UButton>
          <UButton
            color="error"
            size="xs"
            :loading="deleting"
            @click="confirmDelete"
          >
            Confirm Delete
          </UButton>
        </div>
      </template>
    </UModal>
  </div>
</template>
