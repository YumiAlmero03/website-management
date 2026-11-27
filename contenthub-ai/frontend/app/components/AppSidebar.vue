<script setup lang="ts">
import { PanelLeftClose, PanelLeftOpen, ShieldCheck, X } from 'lucide-vue-next'
import { SIDEBAR_MODULES, type NavModuleItem } from '~/utils/navigation'

const route = useRoute()
const uiStore = useUiStore()

function isActive(item: NavModuleItem): boolean {
  if (item.to === '/') {
    return route.path === '/'
  }
  return route.path === item.to || route.path.startsWith(`${item.to}/`)
}

function handleNavClick() {
  uiStore.closeMobileSidebar()
}
</script>

<template>
  <!-- Mobile backdrop -->
  <div
    v-if="uiStore.mobileSidebarOpen"
    class="fixed inset-0 z-40 bg-slate-950/50 lg:hidden"
    aria-hidden="true"
    @click="uiStore.closeMobileSidebar()"
  />

  <aside
    :class="[
      'fixed inset-y-0 left-0 z-50 flex flex-col border-r border-slate-200 bg-white transition-all duration-150 dark:border-slate-800 dark:bg-slate-900 lg:static lg:z-auto',
      uiStore.sidebarCollapsed ? 'lg:w-16' : 'lg:w-64',
      uiStore.mobileSidebarOpen ? 'w-64 translate-x-0' : '-translate-x-full lg:translate-x-0',
    ]"
    aria-label="Primary sidebar navigation"
  >
    <!-- Brand header -->
    <div class="flex h-14 items-center justify-between border-b border-slate-200 px-3 dark:border-slate-800">
      <NuxtLink
        to="/"
        class="flex min-w-0 items-center gap-2.5"
        @click="handleNavClick"
      >
        <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-teal-600 text-white">
          <ShieldCheck
            class="h-4 w-4"
            aria-hidden="true"
          />
        </div>
        <div
          v-if="!uiStore.sidebarCollapsed || uiStore.mobileSidebarOpen"
          class="min-w-0"
        >
          <p class="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
            ContentHub AI
          </p>
          <p class="truncate text-[11px] text-slate-500 dark:text-slate-400">
            Phase 2.1 Website Hub
          </p>
        </div>
      </NuxtLink>

      <button
        type="button"
        class="rounded-md p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100 lg:hidden"
        aria-label="Close navigation menu"
        @click="uiStore.closeMobileSidebar()"
      >
        <X class="h-4 w-4" />
      </button>

      <button
        type="button"
        class="hidden rounded-md p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100 lg:inline-flex"
        :aria-label="uiStore.sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'"
        @click="uiStore.toggleSidebar()"
      >
        <PanelLeftOpen
          v-if="uiStore.sidebarCollapsed"
          class="h-4 w-4"
        />
        <PanelLeftClose
          v-else
          class="h-4 w-4"
        />
      </button>
    </div>

    <!-- Navigation links (14 modules) -->
    <nav class="flex-1 space-y-0.5 overflow-y-auto px-2 py-3">
      <NuxtLink
        v-for="item in SIDEBAR_MODULES"
        :key="item.id"
        :to="item.to"
        :title="uiStore.sidebarCollapsed ? item.label : undefined"
        :class="[
          'group flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors',
          isActive(item)
            ? 'bg-teal-50 text-teal-800 dark:bg-teal-950/60 dark:text-teal-200'
            : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800/70 dark:hover:text-slate-100',
          uiStore.sidebarCollapsed ? 'lg:justify-center lg:px-2' : '',
        ]"
        @click="handleNavClick"
      >
        <AppIcon
          :name="item.icon"
          :class="[
            'h-4 w-4 shrink-0',
            isActive(item)
              ? 'text-teal-700 dark:text-teal-300'
              : 'text-slate-400 group-hover:text-slate-600 dark:text-slate-500 dark:group-hover:text-slate-300',
          ]"
        />
        <span
          v-if="!uiStore.sidebarCollapsed || uiStore.mobileSidebarOpen"
          class="min-w-0 flex-1 truncate"
        >
          {{ item.label }}
        </span>
        <span
          v-if="(!uiStore.sidebarCollapsed || uiStore.mobileSidebarOpen) && !item.implemented"
          class="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400"
        >
          P{{ item.phase }}
        </span>
      </NuxtLink>
    </nav>

    <!-- Footer metadata -->
    <div
      v-if="!uiStore.sidebarCollapsed || uiStore.mobileSidebarOpen"
      class="border-t border-slate-200 px-3 py-2.5 text-[11px] text-slate-500 dark:border-slate-800 dark:text-slate-400"
    >
      Private Single-Admin Instance
    </div>
  </aside>
</template>
