<script setup lang="ts">
import { Inbox } from 'lucide-vue-next'

defineProps<{
  title: string
  description: string
}>()
</script>

<template>
  <div class="flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50/70 px-6 py-10 text-center dark:border-slate-700 dark:bg-slate-900/50">
    <div class="flex h-10 w-10 items-center justify-center rounded-full bg-slate-200/80 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
      <Inbox
        class="h-5 w-5"
        aria-hidden="true"
      />
    </div>
    <h3 class="mt-3 text-sm font-semibold text-slate-900 dark:text-slate-100">
      {{ title }}
    </h3>
    <p class="mt-1 max-w-md text-xs text-slate-500 dark:text-slate-400">
      {{ description }}
    </p>
    <div
      v-if="$slots.actions"
      class="mt-4"
    >
      <slot name="actions" />
    </div>
  </div>
</template>
