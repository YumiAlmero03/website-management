<script setup lang="ts">
import { Copy } from 'lucide-vue-next'
import type { SocialPostItem, SocialPostRevisionItem } from '~/types/api'
import { extractErrorMessage, formatDateTime } from '~/utils/format'

const props = defineProps<{
  open: boolean
  post: SocialPostItem | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

const { request } = useApiClient()
const toast = useToast()

const revisions = ref<SocialPostRevisionItem[]>([])
const loading = ref(false)
const errorMessage = ref<string | null>(null)

async function loadRevisions() {
  if (!props.post) {
    return
  }
  loading.value = true
  errorMessage.value = null
  try {
    revisions.value = await request<SocialPostRevisionItem[]>(
      `/api/v1/social-posts/${props.post.id}/revisions`,
    )
  }
  catch (err) {
    errorMessage.value = extractErrorMessage(err, 'Could not load draft revision history.')
  }
  finally {
    loading.value = false
  }
}

async function copySnapshot(text: string, version: number) {
  try {
    await navigator.clipboard.writeText(text)
    toast.add({ title: `Copied version v${version}`, color: 'success' })
  }
  catch {
    toast.add({ title: 'Clipboard blocked', color: 'warning' })
  }
}

watch(
  () => [props.open, props.post?.id],
  ([isOpen]) => {
    if (isOpen && props.post) {
      void loadRevisions()
    }
  },
)
</script>

<template>
  <UModal
    :open="open"
    :title="`Draft Version History (${post?.social_profile_name || ''})`"
    @update:open="emit('update:open', $event)"
  >
    <template #body>
      <div class="max-h-[70vh] space-y-3 overflow-y-auto text-xs">
        <USkeleton
          v-if="loading"
          class="h-32 w-full"
        />
        <AppErrorState
          v-else-if="errorMessage"
          title="Revisions unavailable"
          :message="errorMessage"
          retryable
          @retry="loadRevisions()"
        />
        <div
          v-for="rev in revisions"
          :key="rev.id"
          class="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700"
        >
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="flex items-center gap-2">
              <span class="font-semibold">v{{ rev.version_number }}</span>
              <UBadge
                :color="rev.change_type === 'manual_edit' ? 'info' : 'neutral'"
                variant="subtle"
                size="xs"
              >
                {{ rev.change_type }}
              </UBadge>
              <span
                v-if="rev.generation_model"
                class="font-mono text-[10px] text-slate-400"
              >
                {{ rev.generation_model }}
              </span>
            </div>
            <div class="flex items-center gap-2">
              <span class="text-[11px] text-slate-500">{{ formatDateTime(rev.created_at) }}</span>
              <UButton
                color="neutral"
                variant="ghost"
                size="xs"
                @click="copySnapshot(rev.assembled_content, rev.version_number)"
              >
                <Copy class="h-3.5 w-3.5" />
              </UButton>
            </div>
          </div>
          <p
            v-if="rev.notes"
            class="text-[11px] text-slate-500"
          >
            {{ rev.notes }}
          </p>
          <pre class="overflow-x-auto whitespace-pre-wrap rounded bg-slate-50 p-2.5 font-sans text-xs text-slate-800 dark:bg-slate-950/60 dark:text-slate-200">{{ rev.assembled_content }}</pre>
        </div>
      </div>
    </template>
  </UModal>
</template>
