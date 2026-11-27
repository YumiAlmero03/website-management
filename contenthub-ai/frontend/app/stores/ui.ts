import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { Website, WebsiteCategory, WebsiteCategoryListResponse, WebsiteListResponse } from '~/types/api'

export const useUiStore = defineStore('ui', () => {
  const sidebarCollapsed = ref(false)
  const mobileSidebarOpen = ref(false)
  const globalSearchQuery = ref('')

  const selectedWebsiteId = ref<number | null>(null)
  const websitesCatalog = ref<Website[]>([])
  const categoriesCatalog = ref<WebsiteCategory[]>([])
  const filtersLoaded = ref(false)

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function setMobileSidebarOpen(open: boolean) {
    mobileSidebarOpen.value = open
  }

  function closeMobileSidebar() {
    mobileSidebarOpen.value = false
  }

  function setWebsiteFilter(websiteId: number | null) {
    selectedWebsiteId.value = websiteId
  }

  async function refreshGlobalSelectors() {
    try {
      const [sitesRes, catsRes] = await Promise.all([
        $fetch<WebsiteListResponse>('/api/v1/websites', {
          credentials: 'include',
          query: { page: 1, page_size: 100 },
        }),
        $fetch<WebsiteCategoryListResponse>('/api/v1/website-categories', {
          credentials: 'include',
          query: { include_archived: false },
        }),
      ])
      websitesCatalog.value = sitesRes.items
      categoriesCatalog.value = catsRes.items
      if (
        selectedWebsiteId.value !== null
        && !sitesRes.items.some((s) => s.id === selectedWebsiteId.value)
      ) {
        selectedWebsiteId.value = null
      }
      filtersLoaded.value = true
    }
    catch {
      // Keep selectors empty safely if backend is unavailable or unauthenticated.
    }
  }

  return {
    sidebarCollapsed,
    mobileSidebarOpen,
    globalSearchQuery,
    selectedWebsiteId,
    websitesCatalog,
    categoriesCatalog,
    filtersLoaded,
    toggleSidebar,
    setMobileSidebarOpen,
    closeMobileSidebar,
    setWebsiteFilter,
    refreshGlobalSelectors,
  }
})
