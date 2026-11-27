import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { Brand, BrandListResponse, Website, WebsiteListResponse } from '~/types/api'

export const useUiStore = defineStore('ui', () => {
  const sidebarCollapsed = ref(false)
  const mobileSidebarOpen = ref(false)
  const globalSearchQuery = ref('')

  const selectedBrandId = ref<number | null>(null)
  const selectedWebsiteId = ref<number | null>(null)
  const brandsCatalog = ref<Brand[]>([])
  const websitesCatalog = ref<Website[]>([])
  const filtersLoaded = ref(false)

  const filteredWebsitesCatalog = computed(() => {
    if (selectedBrandId.value === null) {
      return websitesCatalog.value
    }
    return websitesCatalog.value.filter((site) => site.brand_id === selectedBrandId.value)
  })

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function setMobileSidebarOpen(open: boolean) {
    mobileSidebarOpen.value = open
  }

  function closeMobileSidebar() {
    mobileSidebarOpen.value = false
  }

  function setBrandFilter(brandId: number | null) {
    selectedBrandId.value = brandId
    if (selectedWebsiteId.value !== null && brandId !== null) {
      const stillValid = websitesCatalog.value.some(
        (site) => site.id === selectedWebsiteId.value && site.brand_id === brandId,
      )
      if (!stillValid) {
        selectedWebsiteId.value = null
      }
    }
  }

  function setWebsiteFilter(websiteId: number | null) {
    selectedWebsiteId.value = websiteId
    if (websiteId !== null) {
      const site = websitesCatalog.value.find((s) => s.id === websiteId)
      if (site && selectedBrandId.value !== site.brand_id) {
        selectedBrandId.value = site.brand_id
      }
    }
  }

  async function refreshGlobalSelectors() {
    try {
      const [brandsRes, sitesRes] = await Promise.all([
        $fetch<BrandListResponse>('/api/v1/brands', {
          credentials: 'include',
          query: { page: 1, page_size: 100 },
        }),
        $fetch<WebsiteListResponse>('/api/v1/websites', {
          credentials: 'include',
          query: { page: 1, page_size: 100 },
        }),
      ])
      brandsCatalog.value = brandsRes.items
      websitesCatalog.value = sitesRes.items
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
    selectedBrandId,
    selectedWebsiteId,
    brandsCatalog,
    websitesCatalog,
    filteredWebsitesCatalog,
    filtersLoaded,
    toggleSidebar,
    setMobileSidebarOpen,
    closeMobileSidebar,
    setBrandFilter,
    setWebsiteFilter,
    refreshGlobalSelectors,
  }
})
