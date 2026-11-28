import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useUiStore } from '~/stores/ui'

const emptyCounts = {
  total_discovered: 0,
  total_extracted: 0,
  homepage: 0,
  page: 0,
  game_page: 0,
  blog_index: 0,
  blog_post: 0,
  category: 0,
  tag: 0,
  archive: 0,
  custom: 0,
  pending: 0,
  failed: 0,
  updated: 0,
  excluded: 0,
}

describe('ui store global website selector and category catalog', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('tracks selected website and category catalog cleanly without a separate brand selector', () => {
    const store = useUiStore()
    store.categoriesCatalog = [
      {
        id: 2,
        name: 'Casino',
        slug: 'casino',
        description: null,
        is_archived: false,
        sort_order: 20,
        website_count: 1,
        created_at: '2026-11-27T00:00:00Z',
        updated_at: '2026-11-27T00:00:00Z',
      },
    ]
    store.websitesCatalog = [
      {
        id: 10,
        category_id: 2,
        category_name: 'Casino',
        name: 'Bygame Casino',
        brand_name: 'Bygame',
        brand_slug: 'bygame',
        logo_url: null,
        brand_description: null,
        target_audience: null,
        target_country: 'Philippines',
        primary_language: 'Taglish',
        secondary_languages: [],
        tone: null,
        target_keywords: [],
        restricted_keywords: [],
        default_hashtags: [],
        default_cta: null,
        writing_guidelines: null,
        ai_instructions: null,
        domain: 'bygame.ph',
        website_type: 'nuxt',
        discovery_method: 'auto',
        single_source_only: false,
        rss_url: null,
        sitemap_url: null,
        llms_url: null,
        api_endpoint: null,
        article_url_patterns: [],
        excluded_url_patterns: [],
        scan_interval_minutes: 1440,
        crawl_batch_size: 100,
        crawl_max_urls_per_run: 1000,
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
        content_counts: emptyCounts,
        created_at: '2026-11-27T00:00:00Z',
        updated_at: '2026-11-27T00:00:00Z',
      },
    ]

    store.setWebsiteFilter(10)
    expect(store.selectedWebsiteId).toBe(10)
    expect(store.categoriesCatalog[0]?.name).toBe('Casino')

    store.setWebsiteFilter(null)
    expect(store.selectedWebsiteId).toBeNull()
  })
})
