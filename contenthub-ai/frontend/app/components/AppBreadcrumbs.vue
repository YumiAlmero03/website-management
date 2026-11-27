<script setup lang="ts">
import { ChevronRight } from 'lucide-vue-next'
import { findModuleByRoute } from '~/utils/navigation'

const route = useRoute()

const currentModule = computed(() => findModuleByRoute(route.path))
</script>

<template>
  <nav
    aria-label="Breadcrumb"
    class="flex items-center gap-1.5 text-sm"
  >
    <NuxtLink
      to="/"
      class="font-medium text-slate-500 transition-colors hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
    >
      ContentHub AI
    </NuxtLink>
    <template v-if="currentModule && currentModule.to !== '/'">
      <ChevronRight
        class="h-4 w-4 text-slate-400"
        aria-hidden="true"
      />
      <span class="font-semibold text-slate-900 dark:text-slate-100">
        {{ currentModule.label }}
      </span>
    </template>
    <template v-else>
      <ChevronRight
        class="h-4 w-4 text-slate-400"
        aria-hidden="true"
      />
      <span class="font-semibold text-slate-900 dark:text-slate-100">
        Dashboard
      </span>
    </template>
  </nav>
</template>
