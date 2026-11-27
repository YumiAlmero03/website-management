import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useUiStore } from '~/stores/ui'

describe('ui store global brand and website selectors', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('cascades brand and website filters accurately', () => {
    const store = useUiStore()
    store.websitesCatalog = [
      {
        id: 10,
        brand_id: 1,
        brand_name: 'Brand A',
        name: 'Site A1',
        domain: 'a1.example.com',
        website_type: 'wordpress',
        discovery_method: 'auto',
        rss_url: null,
        sitemap_url: null,
        llms_url: null,
        api_endpoint: null,
        article_url_patterns: [],
        excluded_url_patterns: [],
        scan_interval_minutes: 360,
        auto_scan: true,
        auto_generate: false,
        initial_scan_completed: false,
        baseline_mode: 'import_existing',
        baseline_after_date: null,
        baseline_limit: null,
        last_scanned_at: null,
        last_successful_scan_at: null,
        next_scan_at: null,
        status: 'active',
        article_count: 0,
        created_at: '2026-11-26T00:00:00Z',
        updated_at: '2026-11-26T00:00:00Z',
      },
      {
        id: 20,
        brand_id: 2,
        brand_name: 'Brand B',
        name: 'Site B1',
        domain: 'b1.example.com',
        website_type: 'nuxt',
        discovery_method: 'sitemap',
        rss_url: null,
        sitemap_url: null,
        llms_url: null,
        api_endpoint: null,
        article_url_patterns: [],
        excluded_url_patterns: [],
        scan_interval_minutes: 360,
        auto_scan: true,
        auto_generate: false,
        initial_scan_completed: false,
        baseline_mode: 'import_existing',
        baseline_after_date: null,
        baseline_limit: null,
        last_scanned_at: null,
        last_successful_scan_at: null,
        next_scan_at: null,
        status: 'active',
        article_count: 0,
        created_at: '2026-11-26T00:00:00Z',
        updated_at: '2026-11-26T00:00:00Z',
      },
    ]

    store.setWebsiteFilter(20)
    expect(store.selectedWebsiteId).toBe(20)
    expect(store.selectedBrandId).toBe(2)
    expect(store.filteredWebsitesCatalog).toHaveLength(1)

    // Switching brand clears incompatible website selection.
    store.setBrandFilter(1)
    expect(store.selectedBrandId).toBe(1)
    expect(store.selectedWebsiteId).toBeNull()
    expect(store.filteredWebsitesCatalog[0]?.id).toBe(10)
  })
})
