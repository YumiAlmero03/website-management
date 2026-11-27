<script setup lang="ts">
import { Lock, RotateCcw, Save } from 'lucide-vue-next'
import type { SettingItem, SettingsListResponse } from '~/types/api'
import { extractErrorMessage, humanizeCategory } from '~/utils/format'

const { request } = useApiClient()
const toast = useToast()

const settingsData = ref<SettingsListResponse | null>(null)
const draftValues = ref<Record<string, unknown>>({})
const originalValues = ref<Record<string, unknown>>({})
const loading = ref(true)
const saving = ref(false)
const confirmOpen = ref(false)
const errorMessage = ref<string | null>(null)

const PUBLISHING_MODE_OPTIONS = [
  { label: 'Manual (Copy & Publish Manually)', value: 'manual' },
  { label: 'Semi-Automatic (Approve Before Publishing — Recommended)', value: 'semi_automatic' },
  { label: 'Automatic (Explicit Rule-Based Publishing)', value: 'automatic' },
]

const groupedSettings = computed<Record<string, SettingItem[]>>(() => {
  const groups: Record<string, SettingItem[]> = {}
  if (!settingsData.value) {
    return groups
  }
  for (const item of settingsData.value.items) {
    const bucket = groups[item.category] ?? []
    bucket.push(item)
    groups[item.category] = bucket
  }
  return groups
})

const dirtyItems = computed(() => {
  if (!settingsData.value) {
    return []
  }
  return settingsData.value.items.filter((item) => {
    const current = draftValues.value[item.key]
    if (item.is_secret) {
      return typeof current === 'string' && current.trim().length > 0
    }
    return current !== originalValues.value[item.key]
  })
})

function syncDrafts(payload: SettingsListResponse) {
  const nextDraft: Record<string, unknown> = {}
  const nextOriginal: Record<string, unknown> = {}
  for (const item of payload.items) {
    if (item.is_secret) {
      nextDraft[item.key] = ''
      nextOriginal[item.key] = ''
    }
    else {
      nextDraft[item.key] = item.value
      nextOriginal[item.key] = item.value
    }
  }
  draftValues.value = nextDraft
  originalValues.value = nextOriginal
}

async function loadSettings() {
  loading.value = true
  errorMessage.value = null
  try {
    const data = await request<SettingsListResponse>('/api/v1/settings')
    settingsData.value = data
    syncDrafts(data)
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to load application settings.')
  }
  finally {
    loading.value = false
  }
}

function resetDrafts() {
  if (settingsData.value) {
    syncDrafts(settingsData.value)
  }
}

function coerceValue(item: SettingItem, raw: unknown): unknown {
  if (item.value_type === 'integer') {
    return Number.parseInt(String(raw), 10)
  }
  if (item.value_type === 'number') {
    return Number.parseFloat(String(raw))
  }
  if (item.value_type === 'boolean') {
    return Boolean(raw)
  }
  return typeof raw === 'string' ? raw.trim() : raw
}

async function saveChanges() {
  if (dirtyItems.value.length === 0) {
    confirmOpen.value = false
    return
  }

  saving.value = true
  errorMessage.value = null
  try {
    const payload = {
      items: dirtyItems.value.map((item) => ({
        key: item.key,
        value: coerceValue(item, draftValues.value[item.key]),
      })),
    }
    const updated = await request<SettingsListResponse>('/api/v1/settings', {
      method: 'PUT',
      body: payload,
    })
    settingsData.value = updated
    syncDrafts(updated)
    confirmOpen.value = false
    toast.add({
      title: 'Settings saved',
      description: `Updated ${payload.items.length} setting(s) in MySQL.`,
      color: 'success',
    })
  }
  catch (err) {
    confirmOpen.value = false
    const msg = extractErrorMessage(err, 'Failed to update settings.')
    errorMessage.value = msg
    toast.add({
      title: 'Save failed',
      description: msg,
      color: 'error',
    })
  }
  finally {
    saving.value = false
  }
}

onMounted(() => {
  void loadSettings()
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">
          Application Settings
        </h1>
        <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          Configure timezone, publishing defaults, Resource Guardian thresholds, SEO guidance, and encrypted secrets.
        </p>
      </div>

      <div class="flex items-center gap-2">
        <UButton
          color="neutral"
          variant="outline"
          size="sm"
          :disabled="dirtyItems.length === 0 || saving"
          @click="resetDrafts"
        >
          <RotateCcw class="mr-1.5 h-3.5 w-3.5" />
          Reset
        </UButton>
        <UButton
          color="primary"
          size="sm"
          :disabled="dirtyItems.length === 0 || saving"
          @click="confirmOpen = true"
        >
          <Save class="mr-1.5 h-3.5 w-3.5" />
          Save Changes ({{ dirtyItems.length }})
        </UButton>
      </div>
    </div>

    <AppErrorState
      v-if="errorMessage && !loading"
      title="Settings error"
      :message="errorMessage"
      retryable
      @retry="loadSettings()"
    />

    <div
      v-if="loading"
      class="space-y-4"
    >
      <USkeleton class="h-40 w-full" />
      <USkeleton class="h-40 w-full" />
    </div>

    <div
      v-else-if="settingsData"
      class="space-y-6"
    >
      <section
        v-for="category in settingsData.categories"
        :key="category"
        class="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
      >
        <div class="border-b border-slate-200 px-5 py-3.5 dark:border-slate-800">
          <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
            {{ humanizeCategory(category) }}
          </h2>
        </div>

        <div class="divide-y divide-slate-100 dark:divide-slate-800/80">
          <div
            v-for="item in groupedSettings[category]"
            :key="item.key"
            class="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between"
          >
            <div class="max-w-xl">
              <div class="flex items-center gap-2">
                <label
                  :for="`setting-${item.key}`"
                  class="text-sm font-medium text-slate-900 dark:text-slate-100"
                >
                  {{ item.label }}
                </label>
                <UBadge
                  v-if="item.is_secret"
                  :color="item.has_value ? 'success' : 'neutral'"
                  variant="subtle"
                  size="sm"
                >
                  <Lock class="mr-1 h-3 w-3" />
                  {{ item.has_value ? 'Encrypted Value Stored' : 'Not Configured' }}
                </UBadge>
              </div>
              <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">
                {{ item.description }}
              </p>
              <p class="mt-1 font-mono text-[11px] text-slate-400">
                {{ item.key }}
              </p>
            </div>

            <div class="w-full sm:w-72">
              <USwitch
                v-if="item.value_type === 'boolean'"
                :id="`setting-${item.key}`"
                :model-value="Boolean(draftValues[item.key])"
                @update:model-value="draftValues[item.key] = $event"
              />

              <USelect
                v-else-if="item.key === 'publishing.default_mode'"
                :id="`setting-${item.key}`"
                :model-value="String(draftValues[item.key] ?? 'semi_automatic')"
                :items="PUBLISHING_MODE_OPTIONS"
                value-key="value"
                class="w-full"
                @update:model-value="draftValues[item.key] = $event"
              />

              <UInput
                v-else-if="item.value_type === 'integer' || item.value_type === 'number'"
                :id="`setting-${item.key}`"
                :model-value="String(draftValues[item.key] ?? '')"
                type="number"
                :step="item.value_type === 'number' ? '0.5' : '1'"
                class="w-full"
                @update:model-value="draftValues[item.key] = item.value_type === 'integer' ? Number.parseInt(String($event), 10) : Number.parseFloat(String($event))"
              />

              <UInput
                v-else-if="item.is_secret"
                :id="`setting-${item.key}`"
                :model-value="String(draftValues[item.key] ?? '')"
                type="password"
                autocomplete="new-password"
                :placeholder="item.has_value ? 'Leave blank to keep stored secret' : 'Enter new secret value'"
                class="w-full"
                @update:model-value="draftValues[item.key] = String($event)"
              />

              <UInput
                v-else
                :id="`setting-${item.key}`"
                :model-value="String(draftValues[item.key] ?? '')"
                type="text"
                class="w-full"
                @update:model-value="draftValues[item.key] = String($event)"
              />
            </div>
          </div>
        </div>
      </section>
    </div>

    <AppConfirmDialog
      v-model:open="confirmOpen"
      title="Apply application settings?"
      :description="`Save ${dirtyItems.length} modified setting(s) to MySQL? Secret values are encrypted with Fernet before storage.`"
      confirm-label="Save Settings"
      :loading="saving"
      @confirm="saveChanges"
    />
  </div>
</template>
