<script setup lang="ts">
import { Archive, Lock, Pencil, Plus, RotateCcw, Save, Trash2 } from 'lucide-vue-next'
import type {
  SettingItem,
  SettingsListResponse,
  WebsiteCategory,
  WebsiteCategoryListResponse,
} from '~/types/api'
import { extractErrorMessage, humanizeCategory } from '~/utils/format'

const { request } = useApiClient()
const uiStore = useUiStore()
const toast = useToast()

const settingsData = ref<SettingsListResponse | null>(null)
const draftValues = ref<Record<string, unknown>>({})
const originalValues = ref<Record<string, unknown>>({})
const loading = ref(true)
const saving = ref(false)
const confirmOpen = ref(false)
const errorMessage = ref<string | null>(null)

// Website Categories state
const categories = ref<WebsiteCategory[]>([])
const includeArchivedCategories = ref(false)
const categoryModalOpen = ref(false)
const editingCategoryId = ref<number | null>(null)
const savingCategory = ref(false)
const categoryForm = ref({
  name: '',
  description: '',
  sort_order: 100,
})

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

async function loadCategories() {
  try {
    const res = await request<WebsiteCategoryListResponse>('/api/v1/website-categories', {
      query: { include_archived: includeArchivedCategories.value },
    })
    categories.value = res.items
  }
  catch (err) {
    toast.add({
      title: 'Failed to load categories',
      description: extractErrorMessage(err, 'Could not fetch website categories.'),
      color: 'error',
    })
  }
}

function openCreateCategoryModal() {
  editingCategoryId.value = null
  categoryForm.value = { name: '', description: '', sort_order: 100 }
  categoryModalOpen.value = true
}

function openEditCategoryModal(cat: WebsiteCategory) {
  editingCategoryId.value = cat.id
  categoryForm.value = {
    name: cat.name,
    description: cat.description || '',
    sort_order: cat.sort_order,
  }
  categoryModalOpen.value = true
}

async function saveCategory() {
  if (!categoryForm.value.name.trim()) {
    return
  }
  savingCategory.value = true
  try {
    const body = {
      name: categoryForm.value.name.trim(),
      description: categoryForm.value.description.trim() || null,
      sort_order: Number(categoryForm.value.sort_order) || 100,
    }
    if (editingCategoryId.value === null) {
      await request('/api/v1/website-categories', { method: 'POST', body })
      toast.add({ title: 'Category created', color: 'success' })
    }
    else {
      await request(`/api/v1/website-categories/${editingCategoryId.value}`, {
        method: 'PATCH',
        body,
      })
      toast.add({ title: 'Category updated', color: 'success' })
    }
    categoryModalOpen.value = false
    await Promise.all([loadCategories(), uiStore.refreshGlobalSelectors()])
  }
  catch (err) {
    toast.add({
      title: 'Category save failed',
      description: extractErrorMessage(err, 'Could not save category.'),
      color: 'error',
    })
  }
  finally {
    savingCategory.value = false
  }
}

async function toggleArchiveCategory(cat: WebsiteCategory) {
  try {
    await request(`/api/v1/website-categories/${cat.id}`, {
      method: 'PATCH',
      body: { is_archived: !cat.is_archived },
    })
    toast.add({
      title: cat.is_archived ? 'Category restored' : 'Category archived',
      color: 'success',
    })
    await Promise.all([loadCategories(), uiStore.refreshGlobalSelectors()])
  }
  catch (err) {
    toast.add({
      title: 'Update failed',
      description: extractErrorMessage(err, 'Could not update category state.'),
      color: 'error',
    })
  }
}

async function deleteCategory(cat: WebsiteCategory) {
  try {
    await request(`/api/v1/website-categories/${cat.id}`, { method: 'DELETE' })
    toast.add({ title: 'Category deleted', color: 'success' })
    await Promise.all([loadCategories(), uiStore.refreshGlobalSelectors()])
  }
  catch (err) {
    toast.add({
      title: 'Cannot delete category',
      description: extractErrorMessage(err, 'Category may still be assigned to websites.'),
      color: 'error',
    })
  }
}

watch(includeArchivedCategories, () => {
  void loadCategories()
})

onMounted(() => {
  void Promise.all([loadSettings(), loadCategories()])
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

      <!-- Custom Website Categories Management -->
      <section class="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div class="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-3.5 dark:border-slate-800">
          <div>
            <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Website Categories
            </h2>
            <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
              Administrator-defined classification labels for websites. Unused categories can be deleted; active categories can be archived.
            </p>
          </div>
          <div class="flex items-center gap-3">
            <label class="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300">
              <USwitch v-model="includeArchivedCategories" />
              <span>Show Archived</span>
            </label>
            <UButton
              color="primary"
              size="xs"
              @click="openCreateCategoryModal"
            >
              <Plus class="mr-1 h-3.5 w-3.5" />
              New Category
            </UButton>
          </div>
        </div>

        <div class="overflow-x-auto">
          <table class="min-w-full divide-y divide-slate-200 text-left text-xs dark:divide-slate-800">
            <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950/60 dark:text-slate-400">
              <tr>
                <th class="px-5 py-2.5 font-medium">Name</th>
                <th class="px-4 py-2.5 font-medium">Description</th>
                <th class="px-4 py-2.5 font-medium">Websites</th>
                <th class="px-4 py-2.5 font-medium">Status</th>
                <th class="px-5 py-2.5 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800/80">
              <tr
                v-for="cat in categories"
                :key="cat.id"
                class="hover:bg-slate-50/70 dark:hover:bg-slate-800/40"
              >
                <td class="px-5 py-2.5 font-medium text-slate-900 dark:text-slate-100">
                  {{ cat.name }}
                  <span class="ml-1 font-mono text-[10px] text-slate-400">{{ cat.slug }}</span>
                </td>
                <td class="px-4 py-2.5 text-slate-500 dark:text-slate-400">
                  {{ cat.description || '—' }}
                </td>
                <td class="px-4 py-2.5 font-mono text-slate-700 dark:text-slate-300">
                  {{ cat.website_count }}
                </td>
                <td class="px-4 py-2.5">
                  <UBadge
                    :color="cat.is_archived ? 'neutral' : 'success'"
                    variant="subtle"
                    size="xs"
                  >
                    {{ cat.is_archived ? 'Archived' : 'Active' }}
                  </UBadge>
                </td>
                <td class="px-5 py-2.5">
                  <div class="flex items-center justify-end gap-1.5">
                    <UButton
                      color="neutral"
                      variant="ghost"
                      size="xs"
                      aria-label="Edit category"
                      @click="openEditCategoryModal(cat)"
                    >
                      <Pencil class="h-3.5 w-3.5" />
                    </UButton>
                    <UButton
                      color="neutral"
                      variant="ghost"
                      size="xs"
                      :title="cat.is_archived ? 'Unarchive category' : 'Archive category'"
                      @click="toggleArchiveCategory(cat)"
                    >
                      <Archive class="h-3.5 w-3.5" />
                    </UButton>
                    <UButton
                      color="error"
                      variant="ghost"
                      size="xs"
                      :disabled="cat.website_count > 0"
                      :title="cat.website_count > 0 ? 'Reassign websites before deleting' : 'Delete unused category'"
                      @click="deleteCategory(cat)"
                    >
                      <Trash2 class="h-3.5 w-3.5" />
                    </UButton>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>

    <UModal
      v-model:open="categoryModalOpen"
      :title="editingCategoryId === null ? 'New Website Category' : 'Edit Website Category'"
    >
      <template #body>
        <form
          class="space-y-4"
          @submit.prevent="saveCategory"
        >
          <div>
            <label class="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300">
              Category Name *
            </label>
            <UInput
              v-model="categoryForm.name"
              placeholder="e.g., Sports Web, Casino, E-commerce"
              required
              class="w-full"
            />
          </div>
          <div>
            <label class="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300">
              Description
            </label>
            <UInput
              v-model="categoryForm.description"
              placeholder="Optional short note"
              class="w-full"
            />
          </div>
          <div>
            <label class="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300">
              Sort Order
            </label>
            <UInput
              v-model="categoryForm.sort_order"
              type="number"
              class="w-32"
            />
          </div>
          <div class="flex justify-end gap-2 pt-2">
            <UButton
              color="neutral"
              variant="outline"
              size="sm"
              @click="categoryModalOpen = false"
            >
              Cancel
            </UButton>
            <UButton
              type="submit"
              color="primary"
              size="sm"
              :loading="savingCategory"
            >
              Save Category
            </UButton>
          </div>
        </form>
      </template>
    </UModal>

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
