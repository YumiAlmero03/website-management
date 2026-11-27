<script setup lang="ts">
import { Moon, ShieldCheck, Sun } from 'lucide-vue-next'

const colorMode = useColorMode()
const isDark = computed(() => colorMode.value === 'dark')

function toggleColorMode() {
  colorMode.preference = isDark.value ? 'light' : 'dark'
}
</script>

<template>
  <div class="flex min-h-screen flex-col bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
    <header class="flex h-14 items-center justify-between border-b border-slate-200 bg-white px-4 dark:border-slate-800 dark:bg-slate-900 sm:px-6">
      <div class="flex items-center gap-2.5">
        <div class="flex h-8 w-8 items-center justify-center rounded-md bg-teal-600 text-white">
          <ShieldCheck
            class="h-4 w-4"
            aria-hidden="true"
          />
        </div>
        <span class="text-sm font-semibold">ContentHub AI</span>
      </div>

      <ClientOnly>
        <button
          type="button"
          class="rounded-md border border-slate-200 p-1.5 text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          :aria-label="isDark ? 'Switch to light mode' : 'Switch to dark mode'"
          @click="toggleColorMode"
        >
          <Sun
            v-if="isDark"
            class="h-4 w-4"
          />
          <Moon
            v-else
            class="h-4 w-4"
          />
        </button>
        <template #fallback>
          <div class="h-8 w-8 rounded-md border border-slate-200 dark:border-slate-700" />
        </template>
      </ClientOnly>
    </header>

    <main class="flex flex-1 items-center justify-center p-4 sm:p-6">
      <slot />
    </main>
  </div>
</template>
