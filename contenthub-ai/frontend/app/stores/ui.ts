import { ref } from 'vue'
import { defineStore } from 'pinia'
import type {
  ContentApprovalStats,
  Website,
  WebsiteCategory,
  WebsiteCategoryListResponse,
  WebsiteListResponse,
} from '~/types/api'

export const useUiStore = defineStore('ui', () => {
  const sidebarCollapsed = ref(false)
  const mobileSidebarOpen = ref(false)
  const globalSearchQuery = ref('')

  const selectedWebsiteId = ref<number | null>(null)
  const websitesCatalog = ref<Website[]>([])
  const categoriesCatalog = ref<WebsiteCategory[]>([])
  const pendingApprovalsCount = ref<number>(0)
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
    void refreshPendingApprovalsCount()
  }

  function setPendingApprovalsCount(count: number) {
    pendingApprovalsCount.value = Math.max(0, count)
  }

  async function refreshPendingApprovalsCount() {
    try {
      const stats = await $fetch<ContentApprovalStats>('/api/v1/content-approvals/stats', {
        credentials: 'include',
        query: selectedWebsiteId.value !== null ? { website_id: selectedWebsiteId.value } : undefined,
      })
      pendingApprovalsCount.value = (stats.pending_review || 0) + (stats.needs_rereview || 0)
    }
    catch {
      // Ignore if unauthenticated yet.
    }
  }

  async function refreshGlobalSelectors() {
    try {
      const [sitesRes, catsRes, appStats] = await Promise.all([
        $fetch<WebsiteListResponse>('/api/v1/websites', {
          credentials: 'include',
          query: { page: 1, page_size: 100 },
        }),
        $fetch<WebsiteCategoryListResponse>('/api/v1/website-categories', {
          credentials: 'include',
          query: { include_archived: false },
        }),
        $fetch<ContentApprovalStats>('/api/v1/content-approvals/stats', {
          credentials: 'include',
          query: selectedWebsiteId.value !== null ? { website_id: selectedWebsiteId.value } : undefined,
        }).catch(() => null),
      ])
      websitesCatalog.value = sitesRes.items
      categoriesCatalog.value = catsRes.items
      if (appStats) {
        pendingApprovalsCount.value = (appStats.pending_review || 0) + (appStats.needs_rereview || 0)
      }
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
    pendingApprovalsCount,
    filtersLoaded,
    toggleSidebar,
    setMobileSidebarOpen,
    closeMobileSidebar,
    setWebsiteFilter,
    setPendingApprovalsCount,
    refreshPendingApprovalsCount,
    refreshGlobalSelectors,
  }
})
