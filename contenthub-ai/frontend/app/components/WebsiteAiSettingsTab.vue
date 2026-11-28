<script setup lang="ts">
import { AlertTriangle, CheckCircle, History, Save, Sparkles } from 'lucide-vue-next'
import type {
  KnowledgeProfile,
  KnowledgeProfileRevision,
  Website,
} from '~/types/api'
import { CONTEXT_MODE_OPTIONS } from '~/utils/ai'
import { extractErrorMessage, formatDateTime } from '~/utils/format'

const props = defineProps<{
  website: Website
}>()

const emit = defineEmits<{
  updated: [website: Website]
}>()

const { request } = useApiClient()
const toast = useToast()

const profile = ref<KnowledgeProfile | null>(null)
const revisions = ref<KnowledgeProfileRevision[]>([])
const loading = ref(true)
const errorMessage = ref<string | null>(null)

const savingAutoConfig = ref(false)
const savingProfile = ref(false)
const generating = ref(false)
const forceRefresh = ref(false)
const preserveOverrides = ref(true)
const revisionsOpen = ref(false)

const autoForm = ref({
  auto_generate: false,
  auto_generate_require_published_at: true,
  auto_generate_context_mode: 'optimized',
})

const knowledgeForm = ref({
  brand_name: '',
  brand_description: '',
  website_category: '',
  business_overview: '',
  target_audience: '',
  target_country: '',
  primary_language: 'en',
  recommended_writing_tone: '',
  products_text: '',
  features_text: '',
  keywords_text: '',
  pillars_text: '',
  restrictions: '',
  administrator_notes: '',
})

function syncForms() {
  autoForm.value = {
    auto_generate: props.website.auto_generate,
    auto_generate_require_published_at: props.website.auto_generate_require_published_at,
    auto_generate_context_mode: props.website.auto_generate_context_mode || 'optimized',
  }
  const kp = profile.value
  if (!kp) {
    return
  }
  knowledgeForm.value = {
    brand_name: kp.brand_name,
    brand_description: kp.brand_description || '',
    website_category: kp.website_category || '',
    business_overview: kp.business_overview || '',
    target_audience: kp.target_audience || '',
    target_country: kp.target_country || '',
    primary_language: kp.primary_language,
    recommended_writing_tone: kp.recommended_writing_tone || '',
    products_text: kp.products_and_services.join(', '),
    features_text: kp.main_features.join(', '),
    keywords_text: kp.main_keywords.join(', '),
    pillars_text: kp.content_pillars.join(', '),
    restrictions: kp.relevant_publishing_restrictions || '',
    administrator_notes: kp.administrator_notes || '',
  }
}

function parseList(raw: string): string[] {
  return raw
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

function getProvenanceColor(field: string): 'info' | 'primary' | 'neutral' {
  const source = profile.value?.field_provenance?.[field]
  if (source === 'admin') {
    return 'info'
  }
  if (source === 'ai_generated') {
    return 'primary'
  }
  return 'neutral'
}

async function loadProfile() {
  loading.value = true
  errorMessage.value = null
  try {
    profile.value = await request<KnowledgeProfile>(
      `/api/v1/websites/${props.website.id}/knowledge-profile`,
    )
    syncForms()
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Failed to load website knowledge profile.')
  }
  finally {
    loading.value = false
  }
}

async function saveAutomationConfig() {
  savingAutoConfig.value = true
  try {
    const updated = await request<Website>(`/api/v1/websites/${props.website.id}`, {
      method: 'PATCH',
      body: autoForm.value,
    })
    emit('updated', updated)
    toast.add({ title: 'AI automation preferences saved', color: 'success' })
  }
  catch (err) {
    toast.add({
      title: 'Save failed',
      description: extractErrorMessage(err, 'Could not save website AI preferences.'),
      color: 'error',
    })
  }
  finally {
    savingAutoConfig.value = false
  }
}

async function generateKnowledgeProfile() {
  generating.value = true
  try {
    profile.value = await request<KnowledgeProfile>(
      `/api/v1/websites/${props.website.id}/knowledge-profile/generate`,
      {
        method: 'POST',
        body: {
          force_refresh: forceRefresh.value,
          preserve_manual_overrides: preserveOverrides.value,
        },
      },
    )
    syncForms()
    toast.add({
      title: `Knowledge profile v${profile.value.profile_version} synthesized`,
      description: 'Prioritized website pages were summarized without sending full crawl URLs.',
      color: 'success',
    })
  }
  catch (err) {
    toast.add({
      title: 'Knowledge synthesis failed',
      description: extractErrorMessage(err, 'Ensure a default Gemini API provider is configured.'),
      color: 'error',
    })
  }
  finally {
    generating.value = false
  }
}

async function saveKnowledgeProfile(approve: boolean) {
  savingProfile.value = true
  try {
    const f = knowledgeForm.value
    profile.value = await request<KnowledgeProfile>(
      `/api/v1/websites/${props.website.id}/knowledge-profile`,
      {
        method: 'PATCH',
        body: {
          brand_name: f.brand_name.trim(),
          brand_description: f.brand_description.trim() || null,
          website_category: f.website_category.trim() || null,
          business_overview: f.business_overview.trim() || null,
          target_audience: f.target_audience.trim() || null,
          target_country: f.target_country.trim() || null,
          primary_language: f.primary_language.trim() || 'en',
          recommended_writing_tone: f.recommended_writing_tone.trim() || null,
          products_and_services: parseList(f.products_text),
          main_features: parseList(f.features_text),
          main_keywords: parseList(f.keywords_text),
          content_pillars: parseList(f.pillars_text),
          relevant_publishing_restrictions: f.restrictions.trim() || null,
          administrator_notes: f.administrator_notes.trim() || null,
          approve,
        },
      },
    )
    syncForms()
    toast.add({
      title: approve ? 'Knowledge profile approved' : 'Knowledge overrides saved',
      description: `Manual edits saved as admin overrides (v${profile.value.profile_version}).`,
      color: 'success',
    })
  }
  catch (err) {
    toast.add({
      title: 'Save failed',
      description: extractErrorMessage(err, 'Could not update website knowledge profile.'),
      color: 'error',
    })
  }
  finally {
    savingProfile.value = false
  }
}

async function openRevisions() {
  revisionsOpen.value = true
  try {
    revisions.value = await request<KnowledgeProfileRevision[]>(
      `/api/v1/websites/${props.website.id}/knowledge-profile/revisions`,
    )
  }
  catch (err) {
    toast.add({
      title: 'Could not load revisions',
      description: extractErrorMessage(err, 'Failed to fetch version history.'),
      color: 'error',
    })
  }
}

watch(
  () => props.website,
  () => {
    syncForms()
  },
)

watch(
  () => props.website.id,
  () => {
    void loadProfile()
  },
)

onMounted(() => {
  void loadProfile()
})
</script>

<template>
  <div class="space-y-6 text-xs">
    <!-- Auto-Scan Draft Trigger Policy -->
    <section class="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <div class="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 pb-3 dark:border-slate-800">
        <div>
          <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Automated Social Draft Generation Rules
          </h2>
          <p class="mt-0.5 text-slate-500 dark:text-slate-400">
            Controls whether incremental scans automatically queue Gemini draft jobs for newly discovered blog posts. Historical baseline imports never auto-trigger Gemini.
          </p>
        </div>
        <UButton
          color="primary"
          size="xs"
          :loading="savingAutoConfig"
          @click="saveAutomationConfig"
        >
          <Save class="mr-1 h-3.5 w-3.5" />
          Save Automation Rules
        </UButton>
      </div>

      <div class="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
        <label class="flex cursor-pointer items-start gap-2.5 rounded-md border border-slate-200 p-3 dark:border-slate-700">
          <USwitch v-model="autoForm.auto_generate" size="xs" />
          <div>
            <p class="font-medium">Auto-Generate New Blog Drafts</p>
            <p class="text-[11px] text-slate-500">
              Runs only when baseline scan completed and profile has Auto-Scan Drafts enabled.
            </p>
          </div>
        </label>

        <label class="flex cursor-pointer items-start gap-2.5 rounded-md border border-slate-200 p-3 dark:border-slate-700">
          <USwitch v-model="autoForm.auto_generate_require_published_at" size="xs" />
          <div>
            <p class="font-medium">Require Published Date</p>
            <p class="text-[11px] text-slate-500">
              Skips undated blog archives from automatic generation to protect free-tier quota.
            </p>
          </div>
        </label>

        <div class="rounded-md border border-slate-200 p-3 dark:border-slate-700">
          <label class="mb-1 block font-medium">Auto-Generation Context Mode</label>
          <select
            v-model="autoForm.auto_generate_context_mode"
            class="h-8 w-full rounded-md border border-slate-200 bg-white px-2 text-xs dark:border-slate-700 dark:bg-slate-900"
          >
            <option
              v-for="opt in CONTEXT_MODE_OPTIONS"
              :key="opt.value"
              :value="opt.value"
            >
              {{ opt.label }}
            </option>
          </select>
        </div>
      </div>
    </section>

    <!-- Knowledge Profile Workspace -->
    <AppErrorState
      v-if="errorMessage && !loading"
      title="Knowledge profile unavailable"
      :message="errorMessage"
      retryable
      @retry="loadProfile()"
    />

    <USkeleton
      v-else-if="loading"
      class="h-72 w-full"
    />

    <section
      v-else-if="profile"
      class="space-y-4 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
    >
      <div class="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 pb-3 dark:border-slate-800">
        <div>
          <div class="flex flex-wrap items-center gap-2">
            <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Website Knowledge Profile (v{{ profile.profile_version }})
            </h2>
            <HealthStatusBadge
              :status="profile.status === 'approved' ? 'ok' : profile.is_outdated ? 'warning' : 'neutral'"
              :label="profile.status"
            />
          </div>
          <p class="mt-0.5 text-slate-500 dark:text-slate-400">
            Reused compactly across prompts to prevent re-reading entire site content per post.
            <span v-if="profile.last_generated_at"> · Last synthesized {{ formatDateTime(profile.last_generated_at) }}</span>
          </p>
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <label class="flex cursor-pointer items-center gap-1.5 rounded-md border border-slate-200 px-2 py-1 text-[11px] dark:border-slate-700">
            <input v-model="preserveOverrides" type="checkbox">
            <span>Preserve Manual Edits</span>
          </label>
          <label class="flex cursor-pointer items-center gap-1.5 rounded-md border border-slate-200 px-2 py-1 text-[11px] dark:border-slate-700">
            <input v-model="forceRefresh" type="checkbox">
            <span>Force Refresh</span>
          </label>
          <UButton
            v-if="profile.profile_version > 0"
            color="neutral"
            variant="outline"
            size="xs"
            @click="openRevisions"
          >
            <History class="mr-1 h-3.5 w-3.5" />
            Revisions
          </UButton>
          <UButton
            color="neutral"
            variant="outline"
            size="xs"
            :loading="generating"
            @click="generateKnowledgeProfile"
          >
            <Sparkles class="mr-1 h-3.5 w-3.5 text-teal-600" />
            Generate with Gemini
          </UButton>
        </div>
      </div>

      <div
        v-if="profile.is_outdated"
        class="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200"
      >
        <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" />
        <span>
          Core homepage, product, or policy pages changed since this profile was synthesized. Click <strong>Generate with Gemini</strong> manually when ready to update.
        </span>
      </div>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <div class="mb-1 flex items-center justify-between">
            <label class="font-medium">Brand Name</label>
            <UBadge :color="getProvenanceColor('brand_name')" variant="subtle" size="xs">
              {{ profile.field_provenance.brand_name || 'extracted' }}
            </UBadge>
          </div>
          <UInput v-model="knowledgeForm.brand_name" size="sm" />
        </div>
        <div>
          <div class="mb-1 flex items-center justify-between">
            <label class="font-medium">Recommended Writing Tone</label>
            <UBadge :color="getProvenanceColor('recommended_writing_tone')" variant="subtle" size="xs">
              {{ profile.field_provenance.recommended_writing_tone || 'extracted' }}
            </UBadge>
          </div>
          <UInput v-model="knowledgeForm.recommended_writing_tone" size="sm" />
        </div>
        <div>
          <div class="mb-1 flex items-center justify-between">
            <label class="font-medium">Target Audience</label>
            <UBadge :color="getProvenanceColor('target_audience')" variant="subtle" size="xs">
              {{ profile.field_provenance.target_audience || 'extracted' }}
            </UBadge>
          </div>
          <UInput v-model="knowledgeForm.target_audience" size="sm" />
        </div>
        <div>
          <div class="mb-1 flex items-center justify-between">
            <label class="font-medium">Primary Language & Country</label>
            <UBadge :color="getProvenanceColor('primary_language')" variant="subtle" size="xs">
              {{ profile.field_provenance.primary_language || 'extracted' }}
            </UBadge>
          </div>
          <div class="grid grid-cols-2 gap-2">
            <UInput v-model="knowledgeForm.primary_language" size="sm" placeholder="Language" />
            <UInput v-model="knowledgeForm.target_country" size="sm" placeholder="Country" />
          </div>
        </div>
      </div>

      <div>
        <div class="mb-1 flex items-center justify-between">
          <label class="font-medium">Business Overview</label>
          <UBadge :color="getProvenanceColor('business_overview')" variant="subtle" size="xs">
            {{ profile.field_provenance.business_overview || 'extracted' }}
          </UBadge>
        </div>
        <UTextarea v-model="knowledgeForm.business_overview" :rows="3" size="sm" />
      </div>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <div class="mb-1 flex items-center justify-between">
            <label class="font-medium">Products & Services (Comma separated)</label>
            <UBadge :color="getProvenanceColor('products_and_services')" variant="subtle" size="xs">
              {{ profile.field_provenance.products_and_services || 'extracted' }}
            </UBadge>
          </div>
          <UTextarea v-model="knowledgeForm.products_text" :rows="2" size="sm" />
        </div>
        <div>
          <div class="mb-1 flex items-center justify-between">
            <label class="font-medium">Main Features (Comma separated)</label>
            <UBadge :color="getProvenanceColor('main_features')" variant="subtle" size="xs">
              {{ profile.field_provenance.main_features || 'extracted' }}
            </UBadge>
          </div>
          <UTextarea v-model="knowledgeForm.features_text" :rows="2" size="sm" />
        </div>
        <div>
          <div class="mb-1 flex items-center justify-between">
            <label class="font-medium">Content Pillars (Comma separated)</label>
            <UBadge :color="getProvenanceColor('content_pillars')" variant="subtle" size="xs">
              {{ profile.field_provenance.content_pillars || 'extracted' }}
            </UBadge>
          </div>
          <UInput v-model="knowledgeForm.pillars_text" size="sm" />
        </div>
        <div>
          <div class="mb-1 flex items-center justify-between">
            <label class="font-medium">Main Keywords (Comma separated)</label>
            <UBadge :color="getProvenanceColor('main_keywords')" variant="subtle" size="xs">
              {{ profile.field_provenance.main_keywords || 'extracted' }}
            </UBadge>
          </div>
          <UInput v-model="knowledgeForm.keywords_text" size="sm" />
        </div>
      </div>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <div class="mb-1 flex items-center justify-between">
            <label class="font-medium">Publishing Restrictions</label>
            <UBadge :color="getProvenanceColor('relevant_publishing_restrictions')" variant="subtle" size="xs">
              {{ profile.field_provenance.relevant_publishing_restrictions || 'extracted' }}
            </UBadge>
          </div>
          <UTextarea v-model="knowledgeForm.restrictions" :rows="2" size="sm" />
        </div>
        <div>
          <div class="mb-1 flex items-center justify-between">
            <label class="font-medium">Administrator Notes (Permanent)</label>
            <UBadge :color="getProvenanceColor('administrator_notes')" variant="subtle" size="xs">
              {{ profile.field_provenance.administrator_notes || 'admin' }}
            </UBadge>
          </div>
          <UTextarea v-model="knowledgeForm.administrator_notes" :rows="2" size="sm" />
        </div>
      </div>

      <div
        v-if="profile.source_content_references.length > 0"
        class="rounded-md bg-slate-50 p-3 dark:bg-slate-950/50"
      >
        <p class="mb-2 font-medium text-slate-700 dark:text-slate-300">
          Compact Source Pages Used for Synthesis ({{ profile.source_content_references.length }})
        </p>
        <div class="flex flex-wrap gap-1.5">
          <NuxtLink
            v-for="src in profile.source_content_references"
            :key="src.content_id"
            :to="`/content-library/${src.content_id}`"
            class="rounded border border-slate-200 bg-white px-2 py-1 text-[11px] hover:border-teal-500 dark:border-slate-700 dark:bg-slate-900"
          >
            {{ src.content_type }} · {{ src.title }}
          </NuxtLink>
        </div>
      </div>

      <div class="flex justify-end gap-2 border-t border-slate-100 pt-3 dark:border-slate-800">
        <UButton
          color="neutral"
          variant="outline"
          size="xs"
          :loading="savingProfile"
          @click="saveKnowledgeProfile(false)"
        >
          <Save class="mr-1 h-3.5 w-3.5" />
          Save Manual Overrides
        </UButton>
        <UButton
          color="primary"
          size="xs"
          :loading="savingProfile"
          @click="saveKnowledgeProfile(true)"
        >
          <CheckCircle class="mr-1 h-3.5 w-3.5" />
          Save & Approve Profile
        </UButton>
      </div>
    </section>

    <UModal
      v-model:open="revisionsOpen"
      title="Knowledge Profile Revisions"
    >
      <template #body>
        <div class="max-h-96 space-y-2.5 overflow-y-auto text-xs">
          <div
            v-for="rev in revisions"
            :key="rev.id"
            class="rounded border border-slate-200 p-3 dark:border-slate-700"
          >
            <div class="flex items-center justify-between font-semibold">
              <span>Version {{ rev.profile_version }} ({{ rev.change_source }})</span>
              <span class="font-normal text-slate-500">{{ formatDateTime(rev.created_at) }}</span>
            </div>
            <p class="mt-1 text-slate-600 dark:text-slate-300">
              {{ String(rev.snapshot_json.business_overview || 'Manual update snapshot') }}
            </p>
          </div>
        </div>
      </template>
    </UModal>
  </div>
</template>
