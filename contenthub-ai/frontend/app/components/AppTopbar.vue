<script setup lang="ts">
import { LogOut, Menu, Moon, Search, Sun } from 'lucide-vue-next'
import { filterModulesByQuery, type NavModuleItem } from '~/utils/navigation'

const router = useRouter()
const authStore = useAuthStore()
const uiStore = useUiStore()
const colorMode = useColorMode()
const toast = useToast()

const searchOpen = ref(false)
const logoutDialogOpen = ref(false)
const loggingOut = ref(false)
const searchContainer = ref<HTMLElement | null>(null)

const searchResults = computed<NavModuleItem[]>(() => filterModulesByQuery(uiStore.globalSearchQuery))
const isDark = computed(() => colorMode.value === 'dark')

const websiteSelectValue = computed({
  get: () => (uiStore.selectedWebsiteId !== null ? String(uiStore.selectedWebsiteId) : 'all'),
  set: (val: string) => {
    uiStore.setWebsiteFilter(val === 'all' ? null : Number(val))
  },
})

function toggleColorMode() {
  colorMode.preference = isDark.value ? 'light' : 'dark'
}

function selectSearchResult(item: NavModuleItem) {
  uiStore.globalSearchQuery = ''
  searchOpen.value = false
  router.push(item.to)
}

function handleDocumentClick(event: MouseEvent) {
  if (searchContainer.value && !searchContainer.value.contains(event.target as Node)) {
    searchOpen.value = false
  }
}

async function confirmLogout() {
  loggingOut.value = true
  try {
    await authStore.logout()
    logoutDialogOpen.value = false
    toast.add({
      title: 'Signed out',
      description: 'Your administrator session has been revoked.',
      color: 'neutral',
    })
    await navigateTo('/login')
  }
  finally {
    loggingOut.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleDocumentClick)
  if (authStore.isAuthenticated && !uiStore.filtersLoaded) {
    void uiStore.refreshGlobalSelectors()
  }
})

onUnmounted(() => {
  document.removeEventListener('click', handleDocumentClick)
})
</script>

<template>
  <header class="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-slate-200 bg-white/95 px-4 backdrop-blur-xs dark:border-slate-800 dark:bg-slate-900/95">
    <div class="flex min-w-0 items-center gap-3">
      <button
        type="button"
        class="rounded-md p-1.5 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800 lg:hidden"
        aria-label="Open navigation menu"
        @click="uiStore.setMobileSidebarOpen(true)"
      >
        <Menu class="h-5 w-5" />
      </button>

      <AppBreadcrumbs />
    </div>

    <div class="flex items-center gap-2">
      <!-- Global module search -->
      <div
        ref="searchContainer"
        class="relative hidden w-48 md:block lg:w-56"
      >
        <div class="relative">
          <Search
            class="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-slate-400"
            aria-hidden="true"
          />
          <input
            v-model="uiStore.globalSearchQuery"
            type="search"
            placeholder="Jump to module..."
            aria-label="Global navigation search"
            class="w-full rounded-md border border-slate-200 bg-slate-50 py-1.5 pr-3 pl-8 text-xs text-slate-900 placeholder:text-slate-400 focus:border-teal-500 focus:bg-white focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 dark:focus:bg-slate-900"
            @focus="searchOpen = true"
          >
        </div>

        <div
          v-if="searchOpen && uiStore.globalSearchQuery.trim()"
          class="absolute right-0 z-50 mt-1.5 w-72 rounded-md border border-slate-200 bg-white py-1 shadow-lg dark:border-slate-700 dark:bg-slate-900"
        >
          <template v-if="searchResults.length > 0">
            <button
              v-for="item in searchResults"
              :key="item.id"
              type="button"
              class="flex w-full items-start gap-2.5 px-3 py-2 text-left hover:bg-slate-50 dark:hover:bg-slate-800"
              @click="selectSearchResult(item)"
            >
              <AppIcon
                :name="item.icon"
                class="mt-0.5 h-4 w-4 shrink-0 text-slate-400"
              />
              <div class="min-w-0 flex-1">
                <div class="flex items-center justify-between gap-2">
                  <span class="text-xs font-medium text-slate-900 dark:text-slate-100">{{ item.label }}</span>
                  <span class="text-[10px] text-slate-400">
                    {{ item.implemented ? 'Active' : `Phase ${item.phase}` }}
                  </span>
                </div>
                <p class="truncate text-[11px] text-slate-500 dark:text-slate-400">
                  {{ item.description }}
                </p>
              </div>
            </button>
          </template>
          <p
            v-else
            class="px-3 py-2 text-xs text-slate-500 dark:text-slate-400"
          >
            No matching modules found.
          </p>
        </div>
      </div>

      <!-- Active Phase 2.1 Global Website Selector -->
      <div class="hidden items-center gap-1.5 xl:flex">
        <select
          v-model="websiteSelectValue"
          aria-label="Global website filter"
          class="h-8 max-w-52 rounded-md border border-slate-200 bg-slate-50 px-2 text-xs text-slate-700 focus:border-teal-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
        >
          <option value="all">All Websites</option>
          <option
            v-for="site in uiStore.websitesCatalog"
            :key="site.id"
            :value="String(site.id)"
          >
            {{ site.name }} ({{ site.brand_name }})
          </option>
        </select>
      </div>

      <!-- Light / Dark theme toggle -->
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

      <!-- Admin account & sign out -->
      <div
        v-if="authStore.user"
        class="flex items-center gap-2 border-l border-slate-200 pl-2 dark:border-slate-800"
      >
        <div class="hidden text-right sm:block">
          <p class="max-w-36 truncate text-xs font-medium text-slate-900 dark:text-slate-100">
            {{ authStore.user.display_name }}
          </p>
          <p class="max-w-36 truncate text-[11px] text-slate-500 dark:text-slate-400">
            {{ authStore.user.email }}
          </p>
        </div>
        <UButton
          color="neutral"
          variant="outline"
          size="xs"
          aria-label="Sign out"
          @click="logoutDialogOpen = true"
        >
          <LogOut class="h-3.5 w-3.5" />
          <span class="hidden sm:inline">Sign Out</span>
        </UButton>
      </div>
    </div>
  </header>

  <AppConfirmDialog
    v-model:open="logoutDialogOpen"
    title="Sign out of ContentHub AI?"
    description="Your current server-side administrator session will be immediately revoked."
    confirm-label="Sign Out"
    confirm-color="error"
    :loading="loggingOut"
    @confirm="confirmLogout"
  />
</template>
