<script setup lang="ts">
import { FilePlus2 } from 'lucide-vue-next'
import type { SocialPostItem, SocialProfileItem } from '~/types/api'
import { extractErrorMessage } from '~/utils/format'

const props = defineProps<{ profile: SocialProfileItem }>()
const { request } = useApiClient()
const open = ref(false)
const saving = ref(false)
const caption = ref('')
const error = ref<string | null>(null)
const draft = ref<SocialPostItem | null>(null)
const needsImage = computed(() => props.profile.default_media_required
  || ['instagram', 'pinterest'].includes(props.profile.platform_key))

function openComposer() {
  caption.value = 'Test post from ContentHub AI.'
  error.value = null
  draft.value = null
  open.value = true
}

async function createDraft() {
  if (saving.value || draft.value || !caption.value.trim()) return
  saving.value = true
  error.value = null
  try {
    draft.value = await request<SocialPostItem>(`/api/v1/social-profiles/${props.profile.id}/test-post`, {
      method: 'POST',
      body: { caption: caption.value.trim() },
    })
  }
  catch (err) {
    error.value = extractErrorMessage(err, 'Could not create the test draft.')
  }
  finally {
    saving.value = false
  }
}
</script>

<template>
  <UButton color="neutral" variant="outline" size="xs" @click="openComposer">
    <FilePlus2 class="h-3.5 w-3.5" />
    Test Post
  </UButton>

  <UModal
    v-model:open="open"
    :dismissible="!saving"
    :close="!saving"
    :title="`Test post for ${profile.profile_name}`"
    :description="profile.platform_display_name"
  >
    <template #body>
      <div v-if="draft" class="space-y-3">
        <UAlert color="success" title="Test draft created" description="Open the draft to review and approve it before publishing." />
        <div class="flex justify-end">
          <UButton :to="{ path: '/social-media', query: { post_id: String(draft.id) } }" @click="open = false">
            Open Draft
          </UButton>
        </div>
      </div>
      <form v-else class="space-y-3" @submit.prevent="createDraft">
        <p class="text-sm text-slate-500 dark:text-slate-400">
          Save an unpublished draft for this profile. Approving and publishing happen in Social Media.
        </p>
        <UFormField label="Test caption" required>
          <UTextarea v-model="caption" class="w-full" :rows="3" :maxlength="16000" :disabled="saving" required />
        </UFormField>
        <p v-if="needsImage" class="text-xs text-slate-500 dark:text-slate-400">
          Attach an image in the draft editor before publishing to this profile.
        </p>
        <UAlert v-if="error" color="error" :title="error" />
        <div class="flex justify-end gap-2">
          <UButton type="button" color="neutral" variant="outline" :disabled="saving" @click="open = false">Cancel</UButton>
          <UButton type="submit" :disabled="!caption.trim()" :loading="saving">Create Test Draft</UButton>
        </div>
      </form>
    </template>
  </UModal>
</template>
