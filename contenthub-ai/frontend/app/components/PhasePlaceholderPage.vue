<script setup lang="ts">
import { ArrowLeft, CheckCircle2, Clock } from 'lucide-vue-next'
import { SIDEBAR_MODULES, type NavModuleItem } from '~/utils/navigation'

const props = defineProps<{
  moduleId: string
}>()

const moduleInfo = computed<NavModuleItem | undefined>(() =>
  SIDEBAR_MODULES.find((item) => item.id === props.moduleId),
)
</script>

<template>
  <div class="mx-auto max-w-4xl space-y-6">
    <div class="rounded-lg border border-slate-200 bg-white p-6 shadow-xs dark:border-slate-800 dark:bg-slate-900">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div class="flex items-start gap-3">
          <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200">
            <AppIcon
              :name="moduleInfo?.icon || 'LayoutDashboard'"
              class="h-5 w-5"
            />
          </div>
          <div>
            <div class="flex flex-wrap items-center gap-2">
              <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">
                {{ moduleInfo?.label || 'Planned Module' }}
              </h1>
              <UBadge
                color="neutral"
                variant="subtle"
                size="sm"
              >
                <Clock class="mr-1 h-3 w-3" />
                Scheduled for Phase {{ moduleInfo?.phase || 2 }}
              </UBadge>
              <HealthStatusBadge
                status="not_implemented"
                label="Not Yet Implemented"
              />
            </div>
            <p class="mt-1.5 text-sm text-slate-600 dark:text-slate-400">
              {{ moduleInfo?.description }}
            </p>
          </div>
        </div>

        <UButton
          to="/"
          color="neutral"
          variant="outline"
          size="sm"
        >
          <ArrowLeft class="mr-1 h-4 w-4" />
          Back to Dashboard
        </UButton>
      </div>

      <div class="mt-6 rounded-md border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950/50">
        <p class="text-xs font-semibold tracking-wide text-slate-700 uppercase dark:text-slate-300">
          Why this screen is intentionally inactive in Phase 1
        </p>
        <p class="mt-1 text-xs leading-relaxed text-slate-600 dark:text-slate-400">
          ContentHub AI is delivered in strict phases and never displays fabricated metrics or placeholder
          success flows. This module's MySQL tables, backend services, and UI controls will be built in
          <strong>Phase {{ moduleInfo?.phase || 2 }}</strong> after Phase 1 foundation review.
        </p>
      </div>

      <div
        v-if="moduleInfo?.plannedCapabilities?.length"
        class="mt-6"
      >
        <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
          Planned Phase {{ moduleInfo.phase }} Capabilities
        </h2>
        <ul class="mt-3 space-y-2">
          <li
            v-for="(capability, idx) in moduleInfo.plannedCapabilities"
            :key="idx"
            class="flex items-start gap-2 text-sm text-slate-600 dark:text-slate-300"
          >
            <CheckCircle2
              class="mt-0.5 h-4 w-4 shrink-0 text-teal-600 dark:text-teal-400"
              aria-hidden="true"
            />
            <span>{{ capability }}</span>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>
