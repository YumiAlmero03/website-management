<script setup lang="ts">
defineProps<{
  title: string
  value: string | number
  subtitle?: string
  icon?: string
  status?: string
  statusLabel?: string
}>()
</script>

<template>
  <div class="rounded-lg border border-slate-200 bg-white p-4 shadow-xs dark:border-slate-800 dark:bg-slate-900">
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <p class="text-xs font-medium tracking-wide text-slate-500 uppercase dark:text-slate-400">
          {{ title }}
        </p>
        <p class="mt-2 truncate text-2xl font-semibold text-slate-900 dark:text-slate-100">
          {{ value }}
        </p>
      </div>
      <div class="flex items-center gap-2">
        <HealthStatusBadge
          v-if="status"
          :status="status"
          :label="statusLabel"
        />
        <div
          v-if="icon"
          class="flex h-8 w-8 items-center justify-center rounded-md bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
        >
          <AppIcon
            :name="icon"
            class="h-4 w-4"
          />
        </div>
      </div>
    </div>
    <p
      v-if="subtitle"
      class="mt-2 text-xs text-slate-500 dark:text-slate-400"
    >
      {{ subtitle }}
    </p>
  </div>
</template>
