<script setup lang="ts">
import { AlertTriangle, RefreshCw } from 'lucide-vue-next'

defineProps<{
  title?: string
  message: string
  retryable?: boolean
}>()

const emit = defineEmits<{
  retry: []
}>()
</script>

<template>
  <div
    role="alert"
    class="rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-900/60 dark:bg-red-950/30"
  >
    <div class="flex items-start gap-3">
      <AlertTriangle
        class="mt-0.5 h-5 w-5 shrink-0 text-red-600 dark:text-red-400"
        aria-hidden="true"
      />
      <div class="min-w-0 flex-1">
        <h3 class="text-sm font-semibold text-red-900 dark:text-red-200">
          {{ title || 'Unable to load data' }}
        </h3>
        <p class="mt-1 text-xs text-red-700 dark:text-red-300">
          {{ message }}
        </p>
        <div
          v-if="retryable"
          class="mt-3"
        >
          <UButton
            color="error"
            variant="soft"
            size="xs"
            @click="emit('retry')"
          >
            <RefreshCw class="mr-1 h-3.5 w-3.5" />
            Retry
          </UButton>
        </div>
      </div>
    </div>
  </div>
</template>
