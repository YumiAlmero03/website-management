<script setup lang="ts">
import { AlertCircle, ArrowRight, CheckCircle2, Sparkles } from 'lucide-vue-next'
import type {
  AiGenerationJob,
  AiProviderItem,
  ContentDetail,
  ContentListItem,
  GenerateSocialDestinationsPreview,
} from '~/types/api'
import { CONTEXT_MODE_OPTIONS, getJobStatusMeta } from '~/utils/ai'
import { extractErrorMessage } from '~/utils/format'

const props = defineProps<{
  open: boolean
  content: ContentListItem | ContentDetail | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  generated: [job: AiGenerationJob]
}>()

const { request } = useApiClient()
const toast = useToast()

const loadingPreview = ref(false)
const destinations = ref<GenerateSocialDestinationsPreview | null>(null)
const providers = ref<AiProviderItem[]>([])
const loadError = ref<string | null>(null)

const contextMode = ref('optimized')
const selectedProviderId = ref<string>('default')
const forceRegenerate = ref(false)

const submitting = ref(false)
const activeJob = ref<AiGenerationJob | null>(null)
let pollHandle: ReturnType<typeof setInterval> | null = null

function clearPoll() {
  if (pollHandle) {
    clearInterval(pollHandle)
    pollHandle = null
  }
}

async function loadPreview() {
  if (!props.content) {
    return
  }
  loadingPreview.value = true
  loadError.value = null
  activeJob.value = null
  clearPoll()
  try {
    const [destRes, provRes] = await Promise.all([
      request<GenerateSocialDestinationsPreview>(
        `/api/v1/contents/${props.content.id}/social-destinations`,
      ),
      request<AiProviderItem[]>('/api/v1/ai/providers'),
    ])
    destinations.value = destRes
    providers.value = provRes
  }
  catch (err) {
    loadError.value = extractErrorMessage(err, 'Could not load configured social destinations.')
  }
  finally {
    loadingPreview.value = false
  }
}

function startPolling(jobId: number) {
  clearPoll()
  pollHandle = setInterval(async () => {
    try {
      const updated = await request<AiGenerationJob>(`/api/v1/ai/jobs/${jobId}`)
      activeJob.value = updated
      if (['completed', 'partially_completed', 'failed', 'cancelled'].includes(updated.status)) {
        clearPoll()
        emit('generated', updated)
      }
    }
    catch {
      clearPoll()
    }
  }, 1500)
}

async function triggerGeneration() {
  if (!props.content) {
    return
  }
  submitting.value = true
  try {
    const job = await request<AiGenerationJob>(
      `/api/v1/contents/${props.content.id}/generate-social`,
      {
        method: 'POST',
        body: {
          provider_id: selectedProviderId.value === 'default' ? null : Number(selectedProviderId.value),
          context_mode: contextMode.value,
          force_regenerate: forceRegenerate.value,
          trigger_type: 'manual',
        },
      },
    )
    activeJob.value = job
    toast.add({
      title: `Generation job #${job.id} queued`,
      description: 'Processing Gemini structured social batch in background.',
      color: 'success',
    })
    startPolling(job.id)
  }
  catch (err) {
    toast.add({
      title: 'Generation blocked',
      description: extractErrorMessage(err, 'Could not queue social draft generation.'),
      color: 'error',
    })
  }
  finally {
    submitting.value = false
  }
}

watch(
  () => [props.open, props.content?.id],
  ([isOpen]) => {
    if (isOpen && props.content) {
      void loadPreview()
    }
    else {
      clearPoll()
    }
  },
)

onUnmounted(() => {
  clearPoll()
})
</script>

<template>
  <UModal
    :open="open"
    title="Generate Social Media Drafts"
    @update:open="emit('update:open', $event)"
  >
    <template #body>
      <div class="space-y-4 text-xs">
        <div
          v-if="content"
          class="rounded-md bg-slate-50 p-3 dark:bg-slate-950/60"
        >
          <p class="font-semibold text-slate-900 dark:text-slate-100">
            {{ content.title }}
          </p>
          <p class="mt-0.5 truncate font-mono text-[11px] text-slate-500">
            {{ content.canonical_url }}
          </p>
        </div>

        <USkeleton
          v-if="loadingPreview"
          class="h-28 w-full"
        />

        <AppErrorState
          v-else-if="loadError"
          title="Could not load destinations"
          :message="loadError"
          retryable
          @retry="loadPreview()"
        />

        <template v-else-if="destinations">
          <!-- No Configured Profiles State -->
          <div
            v-if="destinations.eligible_profiles.length === 0"
            class="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200"
          >
            <div class="flex items-start gap-2">
              <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
              <p class="font-medium">
                {{ destinations.empty_message || "No social profiles configured for content generation. Configure your website's social profiles first." }}
              </p>
            </div>
            <UButton
              :to="destinations.configure_url"
              color="primary"
              size="xs"
              @click="emit('update:open', false)"
            >
              Configure Website Social Profiles
              <ArrowRight class="ml-1 h-3.5 w-3.5" />
            </UButton>
          </div>

          <!-- Eligible Destinations Auto-Selected -->
          <template v-else>
            <div class="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
              <p class="font-semibold text-slate-800 dark:text-slate-200">
                Automatic Website Destinations ({{ destinations.eligible_profiles.length }})
              </p>
              <p class="text-[11px] text-slate-500">
                Drafts are generated automatically for all active social profiles enabled on {{ destinations.website_name }}.
              </p>
              <div class="flex flex-wrap gap-1.5 pt-1">
                <UBadge
                  v-for="prof in destinations.eligible_profiles"
                  :key="prof.id"
                  color="info"
                  variant="subtle"
                  size="xs"
                >
                  {{ prof.platform_display_name }}: {{ prof.profile_name }} ({{ prof.language }})
                </UBadge>
              </div>
            </div>

            <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label class="mb-1 block font-medium">Token Context Mode</label>
                <select
                  v-model="contextMode"
                  class="h-9 w-full rounded-md border border-slate-200 bg-white px-2.5 text-xs dark:border-slate-700 dark:bg-slate-900"
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
              <div>
                <label class="mb-1 block font-medium">Gemini Configuration</label>
                <select
                  v-model="selectedProviderId"
                  class="h-9 w-full rounded-md border border-slate-200 bg-white px-2.5 text-xs dark:border-slate-700 dark:bg-slate-900"
                >
                  <option value="default">Active Default Gemini Config</option>
                  <option
                    v-for="prov in providers"
                    :key="prov.id"
                    :value="String(prov.id)"
                  >
                    {{ prov.name }} ({{ prov.selected_model }})
                  </option>
                </select>
              </div>
            </div>

            <label class="flex cursor-pointer items-center gap-2 rounded-md border border-slate-200 px-3 py-2 dark:border-slate-700">
              <input v-model="forceRegenerate" type="checkbox">
              <span>Force regenerate (bypass cache & refresh non-manual AI drafts)</span>
            </label>

            <!-- Active Background Job Progress -->
            <div
              v-if="activeJob"
              class="space-y-2 rounded-lg border border-teal-200 bg-teal-50/70 p-3 dark:border-teal-900/50 dark:bg-teal-950/30"
            >
              <div class="flex items-center justify-between">
                <span class="font-semibold">Job #{{ activeJob.id }}</span>
                <UBadge
                  :color="getJobStatusMeta(activeJob.status).color"
                  variant="subtle"
                  size="xs"
                >
                  {{ getJobStatusMeta(activeJob.status).label }}
                </UBadge>
              </div>
              <p
                v-if="activeJob.defer_reason || activeJob.error_message"
                class="text-[11px] text-amber-800 dark:text-amber-200"
              >
                {{ activeJob.defer_reason || activeJob.error_message }}
              </p>
              <div
                v-if="['completed', 'partially_completed'].includes(activeJob.status)"
                class="flex items-center justify-between pt-1"
              >
                <span class="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-300">
                  <CheckCircle2 class="h-3.5 w-3.5" />
                  Drafts ready for administrator review.
                </span>
                <UButton
                  :to="`/social-media?website_id=${destinations.website_id}&website_content_id=${content?.id}`"
                  color="primary"
                  size="xs"
                  @click="emit('update:open', false)"
                >
                  Open Social Drafts
                </UButton>
              </div>
            </div>

            <div class="flex justify-end gap-2 pt-2">
              <UButton
                color="neutral"
                variant="outline"
                size="xs"
                @click="emit('update:open', false)"
              >
                Close
              </UButton>
              <UButton
                color="primary"
                size="xs"
                :loading="submitting"
                :disabled="providers.length === 0"
                @click="triggerGeneration"
              >
                <Sparkles class="mr-1 h-3.5 w-3.5" />
                {{ providers.length === 0 ? 'Configure Gemini First' : 'Generate Social Drafts' }}
              </UButton>
            </div>
          </template>
        </template>
      </div>
    </template>
  </UModal>
</template>
